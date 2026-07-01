# hf-jobsx `run` — local test sheet
# Copy-paste these into your shell (fish-safe), or run: bash LOCAL-TEST.sh
# Branch: feat/run-header. Nothing here pushes anything.
# ---------------------------------------------------------------------------

# 0. Get on the branch + install deps
cd ~/Documents/code/hf-jobsx
git checkout feat/run-header
uv sync

# ---------------------------------------------------------------------------
# 1. FULLY LOCAL — no network, no launch, no cost
# ---------------------------------------------------------------------------

# 1a. Unit + smoke tests (68 tests) and lint
uv run pytest -q
uv run ruff check src/ tests/ examples/
uv run ruff format --check src/ tests/ examples/

# 1b. --help shows the new `run` command
uv run hf-jobsx run --help

# 1c. Dry-run the cheap example: header -> resolved `hf jobs uv run` command (launches nothing)
uv run hf-jobsx run examples/hello-jobs.py --dry-run

# 1d. Dry-run the motivating image-mode case: the 5-flag vLLM incantation, resolved from the header
uv run hf-jobsx run examples/image-mode-vllm.py in_ds out_ds --max-samples 10 --dry-run

# 1e. Explicit flag OVERRIDES the header (header says l4x1 -> we force a100-large)
uv run hf-jobsx run examples/image-mode-vllm.py --flavor a100-large --dry-run

# 1f. Script args pass through verbatim (--name is unknown to jobsx -> goes to the script)
uv run hf-jobsx run examples/hello-jobs.py --name Ada --dry-run

# 1g. A script with NO [tool.hf-jobs] block still works — just no injected flags
printf '# /// script\n# dependencies = []\n# ///\nprint("hi")\n' > /tmp/plain.py
uv run hf-jobsx run /tmp/plain.py --dry-run

# 1h. Prove `uv` itself ignores the [tool.hf-jobs] block (the whole premise)
uv run --no-project examples/hello-jobs.py --name Ada

# ---------------------------------------------------------------------------
# 2. REAL LAUNCH — this actually starts a Job on HF (cpu-basic, a few seconds, ~free)
#    Needs: hf auth login. Runs the full chain: header -> native hf jobs uv run -> container.
#    Expect to see: the GREETING env var (set from the header) + "hello, Daniel!" in the logs.
# ---------------------------------------------------------------------------

uv run hf-jobsx run examples/hello-jobs.py --name Daniel

# ---------------------------------------------------------------------------
# 3. (Optional) test the REAL `hf jobsx run` dispatch (space, not hyphen)
#    Requires the code on the repo's DEFAULT branch on GitHub — `hf extensions install`
#    only pulls the default branch, so push + merge feat/run-header first, then:
#        hf extensions install davanstrien/hf-jobsx --force
#        hf jobsx run examples/hello-jobs.py --dry-run
#    Until then, `uv run hf-jobsx ...` above exercises the identical code path.
# ---------------------------------------------------------------------------
