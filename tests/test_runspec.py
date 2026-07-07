"""Pure unit tests for runspec: PEP 723 header extraction, [tool.hf-jobs] parsing,
and header+override resolution into native `hf jobs uv run` flags.

No network, no cluster — everything here is string -> dict -> argv.
"""

import pytest

from hf_jobsx import runspec

# A realistic header modeled on ocr/unlimited-ocr-vllm.py: the recipe MUST launch on a
# pinned vLLM image with the image's own interpreter + PYTHONPATH, or every row is an
# error sentinel. vllm/torch come from the image, so they are NOT in `dependencies`.
UNLIMITED_HEADER = '''\
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "datasets>=4.0.0",
#     "huggingface-hub",
#     "pillow",
#     "tqdm",
#     "toolz",
# ]
#
# [tool.hf-jobs]
# image = "vllm/vllm-openai:unlimited-ocr"
# flavor = "l4x1"
# python = "/usr/bin/python3"
# env = { PYTHONPATH = "/usr/local/lib/python3.12/dist-packages" }
# secrets = ["HF_TOKEN"]
# ///

"""Docstring after the header should not be parsed."""
import sys
'''

NO_HFJOBS_HEADER = """\
# /// script
# requires-python = ">=3.11"
# dependencies = ["datasets", "pillow"]
#
# [tool.uv]
# prerelease = "allow"
# ///
print("hello")
"""


def test_extract_block_none_when_absent():
    assert runspec.extract_script_block("print('no header here')\n") is None


def test_parse_runtime_empty_when_no_hfjobs_table():
    # A [tool.uv] block is present but no [tool.hf-jobs] — must not leak uv's config.
    assert runspec.parse_runtime(NO_HFJOBS_HEADER) == {}


def test_parse_runtime_reads_all_fields():
    table = runspec.parse_runtime(UNLIMITED_HEADER)
    assert table == {
        "image": "vllm/vllm-openai:unlimited-ocr",
        "flavor": "l4x1",
        "python": "/usr/bin/python3",
        "env": {"PYTHONPATH": "/usr/local/lib/python3.12/dist-packages"},
        "secrets": ["HF_TOKEN"],
    }


def test_resolve_header_only_builds_expected_flags():
    header = runspec.parse_runtime(UNLIMITED_HEADER)
    resolved = runspec.resolve(header, {"env": {}, "secrets": []})
    assert resolved.flags == [
        "--image",
        "vllm/vllm-openai:unlimited-ocr",
        "--flavor",
        "l4x1",
        "--python",
        "/usr/bin/python3",
        "--env",
        'PYTHONPATH="/usr/local/lib/python3.12/dist-packages"',
        "--secrets",
        "HF_TOKEN",
    ]


def test_timeout_in_header_raises_as_unknown_key():
    # timeout is deliberately NOT a header key (run/data-dependent + a spend cap).
    # A stray one must fail loudly as an unknown key, not silently emit a flag.
    with pytest.raises(ValueError, match="unknown key"):
        runspec.parse_runtime(_header('[tool.hf-jobs]\nimage = "x"\ntimeout = "2h"'))


def test_override_beats_header():
    header = runspec.parse_runtime(UNLIMITED_HEADER)
    resolved = runspec.resolve(header, {"flavor": "a100-large", "env": {}, "secrets": []})
    # header flavor l4x1 must be replaced, not appended
    assert "--flavor" in resolved.flags
    assert resolved.flags[resolved.flags.index("--flavor") + 1] == "a100-large"
    assert "l4x1" not in resolved.flags
    assert any("flavor = a100-large  (override)" == line for line in resolved.echo)


def test_env_merges_and_override_key_wins():
    header = {"env": {"PYTHONPATH": "/img/site-packages", "KEEP": "1"}}
    resolved = runspec.resolve(
        header, {"env": {"PYTHONPATH": "/override", "EXTRA": "2"}, "secrets": []}
    )
    env_flags = [resolved.flags[i + 1] for i, f in enumerate(resolved.flags) if f == "--env"]
    assert 'PYTHONPATH="/override"' in env_flags  # override wins
    assert 'KEEP="1"' in env_flags  # header-only survives
    assert 'EXTRA="2"' in env_flags  # override-only added
    assert not any(v.endswith('"/img/site-packages"') for v in env_flags)


def test_secrets_union_dedupes_preserving_order():
    header = {"secrets": ["HF_TOKEN", "WANDB_API_KEY"]}
    resolved = runspec.resolve(header, {"env": {}, "secrets": ["HF_TOKEN", "OPENAI_API_KEY"]})
    names = [resolved.flags[i + 1] for i, f in enumerate(resolved.flags) if f == "--secrets"]
    assert names == ["HF_TOKEN", "WANDB_API_KEY", "OPENAI_API_KEY"]


def test_secrets_scalar_string_is_accepted():
    resolved = runspec.resolve({"secrets": "HF_TOKEN"}, {"env": {}, "secrets": []})
    assert resolved.flags == ["--secrets", "HF_TOKEN"]


def test_unknown_key_raises_and_lists_valid_keys():
    with pytest.raises(ValueError, match="unknown key") as exc:
        runspec.parse_runtime(_header('[tool.hf-jobs]\ngpu = "h100"\nimage = "x"'))
    # the message must name the offending key and point at the valid set
    assert "gpu" in str(exc.value)
    assert "flavor" in str(exc.value)


def test_no_header_yields_no_flags():
    resolved = runspec.resolve({}, {"env": {}, "secrets": []})
    assert resolved.flags == []
    assert resolved.echo == []


def test_malformed_toml_raises_valueerror():
    bad = "# /// script\n# [tool.hf-jobs\n# image = broken\n# ///\n"
    with pytest.raises(ValueError, match="malformed PEP 723 header"):
        runspec.parse_runtime(bad)


def test_bad_env_type_raises():
    with pytest.raises(ValueError, match="`env` must be a table"):
        runspec.resolve({"env": "PYTHONPATH=/x"}, {"env": {}, "secrets": []})


# --------------------------------------------------------------------------- #
# CRLF line endings (a Windows-authored or HTTP-fetched script must still parse)
# --------------------------------------------------------------------------- #


def test_crlf_header_is_parsed():
    crlf = '# /// script\r\n# [tool.hf-jobs]\r\n# flavor = "l4x1"\r\n# ///\r\n'
    assert runspec.parse_runtime(crlf) == {"flavor": "l4x1"}


# --------------------------------------------------------------------------- #
# non-table / wrong-typed header shapes -> clean ValueError, never AttributeError
# --------------------------------------------------------------------------- #


def _header(body: str) -> str:
    lines = "".join(f"# {line}\n" for line in body.splitlines())
    return f"# /// script\n{lines}# ///\n"


def test_hfjobs_not_a_table_raises():
    with pytest.raises(ValueError, match="must be a table"):
        runspec.parse_runtime(_header('[tool]\nhf-jobs = "oops"'))


def test_tool_not_a_table_raises():
    with pytest.raises(ValueError, match="`tool` must be a table"):
        runspec.parse_runtime(_header('tool = "x"'))


def test_env_not_a_table_raises_at_parse_time():
    # Validation must happen in parse_runtime (guarded by cli.run), not leak from
    # resolve() as a raw traceback.
    with pytest.raises(ValueError, match="`env` must be a table"):
        runspec.parse_runtime(_header('[tool.hf-jobs]\nenv = "PYTHONPATH=/x"'))


def test_non_string_scalar_raises_with_quote_hint():
    with pytest.raises(ValueError, match="`flavor` must be a TOML string"):
        runspec.parse_runtime(_header("[tool.hf-jobs]\nflavor = 4"))


def test_non_string_env_value_raises_with_quote_hint():
    # env = { DEBUG = true } must NOT silently become --env DEBUG=True.
    with pytest.raises(ValueError, match="`env.DEBUG` must be a TOML string"):
        runspec.parse_runtime(_header("[tool.hf-jobs]\nenv = { DEBUG = true }"))


def test_non_string_secrets_item_raises():
    with pytest.raises(ValueError, match="`secrets` must be a name or list of names"):
        runspec.parse_runtime(_header('[tool.hf-jobs]\nsecrets = ["HF_TOKEN", 3]'))


# --------------------------------------------------------------------------- #
# env value quoting: round-trip through the ACTUAL native parser
# --------------------------------------------------------------------------- #

# Native `hf jobs uv run` re-parses each --env token with huggingface_hub's dotenv
# grammar, whose unquoted form treats `#` as a comment start. These tests import the
# real installed parser (test-only; runtime code never touches these private modules)
# so any upstream grammar change breaks loudly here.


@pytest.mark.parametrize(
    "value",
    [
        "a#b",
        'he said "hi"',
        "with spaces  and  runs",
        "back\\slash",
        "trailing\\",
        "double\\\\backslash",
        "KEY=VALUE=more",
        "dollar$sign",
        "\\$escaped-dollar",
        'mix # "q" = $x \\ end',
        "",
        "embedded\nnewline",
    ],
)
def test_env_quoting_round_trips_through_native_parser(value):
    from huggingface_hub.cli._cli_utils import parse_env_map
    from huggingface_hub.utils._dotenv import load_dotenv

    resolved = runspec.resolve({}, {"env": {"K": value}, "secrets": []})
    assert resolved.flags[0] == "--env"
    token = resolved.flags[1]
    assert load_dotenv(token) == {"K": value}
    assert parse_env_map([token]) == {"K": value}


def test_env_hash_value_regression():
    # The original bug: unquoted `--env QUERY=a#b` arrived at the job as QUERY=a.
    resolved = runspec.resolve({"env": {"QUERY": "a#b"}}, {"env": {}, "secrets": []})
    assert resolved.flags == ["--env", 'QUERY="a#b"']


def test_env_value_native_cannot_represent_raises():
    # load_dotenv unescapes with sequential replaces, so a literal backslash before
    # 'n'/'t' is unrepresentable — refuse rather than deliver a corrupted value.
    with pytest.raises(ValueError, match="cannot be passed through native"):
        runspec.resolve({}, {"env": {"P": "C:\\temp"}, "secrets": []})


@pytest.mark.parametrize("sep", ["\r", "\v", "\f", "\x1c", "\x85", "\u2028"])
def test_env_value_line_separator_chars_raise(sep):
    # Native's load_dotenv splits input with str.splitlines(), which breaks on these,
    # and its escape table can't encode them — a value containing one would arrive
    # truncated (verified: 'a\rb' round-trips as '"a'). Refuse loudly instead.
    with pytest.raises(ValueError, match="line-separator"):
        runspec.resolve({}, {"env": {"K": f"a{sep}b"}, "secrets": []})


def test_env_key_invalid_name_raises():
    # TOML bare keys allow '-', but native's dotenv KEY grammar is [A-Za-z_][A-Za-z0-9_]*;
    # 'MY-VAR="x"' parses there as bare key 'MY' resolved from the JOB environment —
    # silent drop at best, ambient-value injection at worst. Reject at parse time.
    with pytest.raises(ValueError, match="not a valid env var name"):
        runspec.parse_runtime(_header('[tool.hf-jobs]\nenv = { MY-VAR = "x" }'))


# --------------------------------------------------------------------------- #
# auth-header scoping: bearer token only for the configured HF endpoint host
# --------------------------------------------------------------------------- #


@pytest.fixture
def hf_endpoint(monkeypatch):
    from huggingface_hub import constants

    monkeypatch.setattr(constants, "ENDPOINT", "https://huggingface.co")


def test_is_hf_url_matches_endpoint_host(hf_endpoint):
    assert runspec._is_hf_url("https://huggingface.co/datasets/u/d/raw/main/s.py")
    assert runspec._is_hf_url("https://huggingface.co:443/x.py")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/huggingface.co",  # host is evil.com; path must not match
        "https://nothuggingface.co/x.py",  # suffix lookalike
        "https://huggingface.co.evil.com/x.py",  # prefix lookalike
        "https://sub.huggingface.co/x.py",  # exact host match only
        "https://gist.githubusercontent.com/u/raw/s.py",
        "http://huggingface.co/x.py",  # right host, plaintext scheme — no token on the wire
    ],
)
def test_is_hf_url_rejects_non_endpoint_hosts(url, hf_endpoint):
    assert not runspec._is_hf_url(url)


class _FakeResponse:
    text = "SCRIPT"

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return _FakeResponse()


def test_read_script_text_scopes_auth_and_honors_token(monkeypatch, hf_endpoint):
    """Bearer token goes ONLY to the HF endpoint host; --token overrides ambient creds."""
    import huggingface_hub.utils as hub_utils

    session = _FakeSession()
    monkeypatch.setattr(hub_utils, "get_session", lambda: session)

    text = runspec.read_script_text("https://huggingface.co/u/d/raw/main/s.py", token="hf_secret")
    assert text == "SCRIPT"
    _, headers = session.calls[0]
    assert headers["authorization"] == "Bearer hf_secret"

    runspec.read_script_text("https://evil.com/huggingface.co", token="hf_secret")
    _, headers = session.calls[1]
    assert headers is None  # no auth (or any HF headers) for arbitrary hosts
