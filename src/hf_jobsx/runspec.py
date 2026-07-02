"""Read a `[tool.hf-jobs]` runtime block from a PEP 723 script header and turn it
into native `hf jobs uv run` flags.

Motivation: some UV script recipes MUST launch with a specific runtime — a pinned
Docker image, a specific interpreter, a `PYTHONPATH`, a hardware flavor — because the
model's architecture only exists in that build (e.g. `vllm/vllm-openai:unlimited-ocr`
with `--python /usr/bin/python3 -e PYTHONPATH=/usr/local/lib/python3.12/dist-packages`).
Today those flags live only in the docstring/README, so a caller who omits them gets a
silent, corrupt run (every row an error sentinel) instead of a clear failure.

This module lets the launch parameters travel *with* the script, in the PEP 723 header,
as a `[tool.*]` sub-table — the same, spec-sanctioned mechanism `uv` already uses for
`[tool.uv]`. `uv` (and everything else) ignores tool tables it doesn't own, so a
`[tool.hf-jobs]` block is invisible to a normal `uv run`.

    # /// script
    # requires-python = ">=3.11"
    # dependencies = ["datasets", "huggingface-hub", "pillow", "tqdm", "toolz"]
    #
    # [tool.hf-jobs]
    # image = "vllm/vllm-openai:unlimited-ocr"
    # flavor = "l4x1"
    # python = "/usr/bin/python3"
    # env = { PYTHONPATH = "/usr/local/lib/python3.12/dist-packages" }
    # secrets = ["HF_TOKEN"]
    # ///

Deliberately excluded: `timeout` (scales with the caller's data + is a spend cap, so not
script-inherent — pass `--timeout` per run), and run/user-specific params like `namespace`,
`volumes`, and `labels`. The header carries only *where/whether* a script runs, never *how
much it spends over time*.

Design: PURE except for `read_script_text` (the one I/O boundary). Everything else is
string → dict → argv, so it can be unit-tested without a network or a cluster.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

try:  # tomllib is stdlib on 3.11+; fall back to tomli on 3.10.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on py<3.11
    import tomli as tomllib  # type: ignore[no-redef]

# PEP 723 reference regex (https://peps.python.org/pep-0723/#reference-implementation).
_PEP723_RE = re.compile(r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$")

# Keys we translate into native `hf jobs uv run` flags. Everything else in the block
# is surfaced as a warning rather than silently dropped.
KNOWN_KEYS = {"image", "flavor", "python", "env", "secrets"}

# Scalar key -> native long flag.
_SCALAR_FLAGS = (
    ("image", "--image"),
    ("flavor", "--flavor"),
    ("python", "--python"),
)


@dataclass
class Resolved:
    """The outcome of merging a header block with CLI overrides."""

    flags: list[str] = field(default_factory=list)  # native flag argv (no script)
    echo: list[str] = field(default_factory=list)  # human-readable "key = val (source)"
    warnings: list[str] = field(default_factory=list)


def extract_script_block(text: str) -> str | None:
    """Return the decoded TOML body of the PEP 723 ``script`` block, or ``None``.

    Follows the PEP 723 reference implementation: match the first ``script`` block and
    strip the leading ``# ``/``#`` from each line. Line endings are normalized first —
    the reference regex anchors on ``\\n``, so a CRLF script (written on Windows, or
    fetched over HTTP) would otherwise silently parse as "no header".
    """
    text = text.replace("\r\n", "\n")
    for match in _PEP723_RE.finditer(text):
        if match.group("type") != "script":
            continue
        return "".join(
            line[2:] if line.startswith("# ") else line[1:]
            for line in match.group("content").splitlines(keepends=True)
        )
    return None


def parse_runtime(text: str) -> dict:
    """Extract the ``[tool.hf-jobs]`` table from a script's text. ``{}`` if absent.

    Raises ``ValueError`` if the header exists but is unusable — malformed TOML, a
    ``tool``/``hf-jobs`` value that isn't a table, or known keys with the wrong TOML
    type — so the CLI can fail loudly (a broken header is a bug worth surfacing, not
    swallowing). All header validation happens here, at parse time, so every bad
    header surfaces as one clean error instead of a traceback later in ``resolve``.
    """
    block = extract_script_block(text)
    if block is None:
        return {}
    try:
        data = tomllib.loads(block)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"malformed PEP 723 header TOML: {exc}") from exc
    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        raise ValueError(
            f"malformed PEP 723 header: `tool` must be a table, got {type(tool).__name__}"
        )
    table = tool.get("hf-jobs", {})
    if not isinstance(table, dict):
        raise ValueError(
            f"malformed PEP 723 header: `[tool.hf-jobs]` must be a table, "
            f"got {type(table).__name__}"
        )
    _validate_header(table)
    return table or {}


def _validate_header(table: dict) -> None:
    """Reject wrong-typed ``[tool.hf-jobs]`` values with an actionable message.

    TOML happily encodes ``flavor = 4`` or ``env = { DEBUG = true }``; silently
    Python-stringifying those (``--flavor 4``, ``--env DEBUG=True``) hands the job a
    value the author never wrote. Require TOML strings and say so.
    """
    for key, _ in _SCALAR_FLAGS:
        value = table.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(
                f'[tool.hf-jobs] `{key}` must be a TOML string — quote it, e.g. {key} = "{value}"'
            )
    env = table.get("env")
    if env is not None:
        if not isinstance(env, dict):
            raise ValueError('`env` must be a table, e.g. env = { PYTHONPATH = "/x" }')
        for k, v in env.items():
            if not isinstance(v, str):
                raise ValueError(
                    f'[tool.hf-jobs] `env.{k}` must be a TOML string — quote it, e.g. {k} = "{v}"'
                )
    secrets = table.get("secrets")
    if secrets is not None and not isinstance(secrets, str):
        if not isinstance(secrets, list) or not all(isinstance(s, str) for s in secrets):
            raise ValueError(
                '`secrets` must be a name or list of names, e.g. secrets = ["HF_TOKEN"]'
            )


def _is_hf_url(url: str) -> bool:
    """True iff *url*'s hostname exactly matches the configured HF endpoint's hostname.

    Exact hostname equality, never substring/suffix matching on the raw URL:
    ``evil.com/huggingface.co``, ``nothuggingface.co``, and
    ``huggingface.co.evil.com`` must all be non-matches.
    """
    from huggingface_hub import constants

    endpoint_host = urlparse(constants.ENDPOINT).hostname
    url_host = urlparse(url).hostname
    return endpoint_host is not None and url_host is not None and url_host == endpoint_host


def read_script_text(script: str, token: str | None = None) -> str:
    """Read a script's text for header parsing. The single I/O boundary.

    Local file -> its contents. ``http(s)`` URL -> fetched via the huggingface_hub
    session (so retries + proxies are handled). Auth headers (bearer token) are
    attached ONLY when the URL's host is the configured HF endpoint — sending the
    user's token to arbitrary hosts would leak it. ``token`` overrides the ambient
    credentials for that fetch (mirrors the CLI's ``--token``). Anything else (a bare
    command like ``lighteval``, or a missing path) -> ``""``, i.e. "no header",
    letting native ``hf jobs uv run`` own the real error.
    """
    if script.startswith(("http://", "https://")):
        from huggingface_hub.utils import build_hf_headers, get_session

        headers = build_hf_headers(token=token) if _is_hf_url(script) else None
        response = get_session().get(script, headers=headers)
        response.raise_for_status()
        return response.text
    path = Path(script)
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _dotenv_quote(value: str) -> str:
    """Encode an env value so native ``hf jobs uv run`` reads it back exactly.

    Native re-parses each ``--env KEY=VALUE`` token with huggingface_hub's dotenv
    grammar (``huggingface_hub.utils._dotenv.load_dotenv``), whose UNQUOTED form
    treats ``#`` as a comment start — ``QUERY=a#b`` arrives as ``a``. Emit the
    double-quoted form instead, escaped per that parser's unescape rules (it applies
    ``\\n``, ``\\t``, ``\\"``, ``\\\\``, then ``\\$`` as sequential replaces).

    Those sequential replaces cannot represent a literal backslash followed by ``n``
    or ``t`` (the earlier ``\\n``/``\\t`` replace always fires first); raise rather
    than deliver a silently corrupted value.
    """
    if re.search(r"\\[nt]", value):
        raise ValueError(
            f"env value {value!r} cannot be passed through native hf jobs: its dotenv "
            "parser mangles a literal backslash followed by 'n' or 't'"
        )
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _coerce_env(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError('`env` must be a table, e.g. env = { PYTHONPATH = "/x" }')
    return {str(k): str(v) for k, v in value.items()}


def _coerce_secrets(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise ValueError('`secrets` must be a name or list of names, e.g. secrets = ["HF_TOKEN"]')


def resolve(header: dict, overrides: dict) -> Resolved:
    """Merge a header block with CLI overrides into native flags. PURE.

    Precedence: an explicit CLI override always wins over the header; the header wins
    over nothing (an unset value is simply omitted, so native applies its own default).
    `env` merges per-key (override keys win); `secrets` unions (order-preserving).
    """
    out = Resolved()

    unknown = set(header) - KNOWN_KEYS
    if unknown:
        out.warnings.append(f"ignoring unknown [tool.hf-jobs] key(s): {', '.join(sorted(unknown))}")

    for key, flag in _SCALAR_FLAGS:
        override = overrides.get(key)
        if override is not None:
            out.flags += [flag, str(override)]
            out.echo.append(f"{key} = {override}  (override)")
        elif header.get(key) is not None:
            out.flags += [flag, str(header[key])]
            out.echo.append(f"{key} = {header[key]}  (header)")

    env: dict[str, str] = {}
    env_sources: dict[str, str] = {}
    if header.get("env") is not None:
        for k, v in _coerce_env(header["env"]).items():
            env[k], env_sources[k] = v, "header"
    for k, v in (overrides.get("env") or {}).items():
        env[k], env_sources[k] = str(v), "override"
    for k, v in env.items():
        # Double-quoted dotenv form: native re-parses the value, and unquoted `#`
        # starts a comment there (see _dotenv_quote).
        out.flags += ["--env", f"{k}={_dotenv_quote(v)}"]
        out.echo.append(f"env {k} = {v}  ({env_sources[k]})")

    secrets: list[str] = []
    if header.get("secrets") is not None:
        secrets += _coerce_secrets(header["secrets"])
    secrets += overrides.get("secrets") or []
    seen: set[str] = set()
    for name in secrets:
        if name in seen:
            continue
        seen.add(name)
        out.flags += ["--secrets", str(name)]
        out.echo.append(f"secret = {name}")

    return out
