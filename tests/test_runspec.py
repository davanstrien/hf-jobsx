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
# timeout = "2h"
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
        "timeout": "2h",
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
        "--timeout",
        "2h",
        "--env",
        "PYTHONPATH=/usr/local/lib/python3.12/dist-packages",
        "--secrets",
        "HF_TOKEN",
    ]
    assert not resolved.warnings


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
    assert "PYTHONPATH=/override" in env_flags  # override wins
    assert "KEEP=1" in env_flags  # header-only survives
    assert "EXTRA=2" in env_flags  # override-only added
    assert "PYTHONPATH=/img/site-packages" not in env_flags


def test_secrets_union_dedupes_preserving_order():
    header = {"secrets": ["HF_TOKEN", "WANDB_API_KEY"]}
    resolved = runspec.resolve(header, {"env": {}, "secrets": ["HF_TOKEN", "OPENAI_API_KEY"]})
    names = [resolved.flags[i + 1] for i, f in enumerate(resolved.flags) if f == "--secrets"]
    assert names == ["HF_TOKEN", "WANDB_API_KEY", "OPENAI_API_KEY"]


def test_secrets_scalar_string_is_accepted():
    resolved = runspec.resolve({"secrets": "HF_TOKEN"}, {"env": {}, "secrets": []})
    assert resolved.flags == ["--secrets", "HF_TOKEN"]


def test_unknown_key_warns_but_does_not_crash():
    resolved = runspec.resolve({"gpu": "h100", "image": "x"}, {"env": {}, "secrets": []})
    assert resolved.flags == ["--image", "x"]
    assert any("gpu" in w for w in resolved.warnings)


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
