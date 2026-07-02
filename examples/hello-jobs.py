# /// script
# requires-python = ">=3.11"
# dependencies = []
#
# [tool.hf-jobs]
# flavor = "cpu-basic"
# env = { GREETING = "hello from a [tool.hf-jobs] runtime header" }
# ///
"""Minimal `hf jobsx run` example — cheap enough to actually launch.

It carries a `[tool.hf-jobs]` block, so `hf jobsx run examples/hello-jobs.py` launches on
`cpu-basic` with a `GREETING` env var without you passing any flags. `uv run` and every other
tool ignore the block (it's a `[tool.*]` table they don't own) — it only affects `hf jobsx run`.

    hf jobsx run --dry-run examples/hello-jobs.py      # print the resolved command, don't launch
    hf jobsx run examples/hello-jobs.py --name Daniel  # actually launch on cpu-basic (cheap)
"""

import argparse
import os
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--name", default="world")
args = parser.parse_args()

print(os.environ.get("GREETING", "(no GREETING in env)"))
print(f"hello, {args.name}!")
print(f"python = {sys.executable}")
