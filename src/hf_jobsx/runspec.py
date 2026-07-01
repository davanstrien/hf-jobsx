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
    strip the leading ``# ``/``#`` from each line.
    """
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

    Raises ``ValueError`` if the header exists but its TOML is malformed, so the CLI can
    fail loudly (a broken header is a bug worth surfacing, not swallowing).
    """
    block = extract_script_block(text)
    if block is None:
        return {}
    try:
        data = tomllib.loads(block)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"malformed PEP 723 header TOML: {exc}") from exc
    table = data.get("tool", {}).get("hf-jobs", {})
    return table or {}


def read_script_text(script: str) -> str:
    """Read a script's text for header parsing. The single I/O boundary.

    Local file -> its contents. ``http(s)`` URL -> fetched via the huggingface_hub
    session (so auth + retries + proxies are handled). Anything else (a bare command
    like ``lighteval``, or a missing path) -> ``""``, i.e. "no header", letting native
    ``hf jobs uv run`` own the real error.
    """
    if script.startswith(("http://", "https://")):
        from huggingface_hub.utils import build_hf_headers, get_session

        response = get_session().get(script, headers=build_hf_headers())
        response.raise_for_status()
        return response.text
    path = Path(script)
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


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
        out.flags += ["--env", f"{k}={v}"]
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
