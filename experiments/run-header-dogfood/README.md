# Experiment: `[tool.hf-jobs]` headers on real OCR recipes

**Question:** does the header actually make launching real `uv-scripts/ocr` recipes feel
better — or is it ceremony? Copies (NOT edits) of upstream recipes from the local
`uv-scripts-for-ai` checkout, adapted here with a `[tool.hf-jobs]` block, dry-run
against their own docstring incantations, and one launched for real.

Branch-only experiment; nothing here ships. Upstream recipes untouched.

## The two strategy cases

| script | strategy | header carries | why it's the test |
|---|---|---|---|
| `unlimited-ocr-vllm.py` | B: image-mode | image + python + PYTHONPATH + flavor + secrets | The motivating case: arch exists only in Baidu's vLLM image; omitting any flag = silent corrupt run (every row an error sentinel). |
| `glm-ocr.py` | A: uv-native | flavor + secrets only | Coexistence proof: `[tool.hf-jobs]` sits directly beside the recipe's existing `[[tool.uv.index]]` + `[tool.uv]` tables. Deps stay uv's job; the header only carries what uv can't see. |

## Before / after (from the recipes' own docstrings)

Before (what the docstring tells you to type, and not fat-finger):

```bash
hf jobs uv run --flavor l4x1 -s HF_TOKEN \
    --image vllm/vllm-openai:unlimited-ocr --python /usr/bin/python3 \
    -e PYTHONPATH=/usr/local/lib/python3.12/dist-packages \
    unlimited-ocr-vllm.py in_ds out_ds --max-samples 10
```

After (runtime travels with the script; timeout stays per-run by design):

```bash
hf jobsx run --timeout 20m unlimited-ocr-vllm.py in_ds out_ds --max-samples 10
```

## Verified

- [x] Both dry-runs resolve to the docstring incantations exactly (2026-07-03).
- [x] `uv` itself parses both adapted headers without complaint (resolves the script env;
      warnings seen are vllm-nightly wheel metadata, unrelated).
- [x] Real launch: `unlimited-ocr-vllm.py` on `davanstrien/exams-ocr-gpu-test` →
      `davanstrien/run-header-dogfood-test`, `--max-samples 5 --timeout 20m`.
      **COMPLETED** (job `6a4782fefb6818a83db312e0`, 171s, ~$0.04): image booted, CUDA on
      L4, image interpreter + PYTHONPATH intact, HF_TOKEN forwarded, 5 pages OCR'd,
      parquet + dataset card pushed. First attempt (`6a478214…`) errored on a *script-level*
      arg (output column existed → added `--output-column markdown_unlimited`) — the header
      layer was invisible in that failure, which is the delegation model working.
      Total spend both attempts: ~$0.07.

## UX verdict

**Fresh-eyes subagent review (2026-07-03): adopt, 7.5/10** — "the header + provenance
echo is categorically better than docstring incantations"; both real-recipe dry-runs
reproduced the docstring commands exactly with zero flags remembered. The resolved-runtime
echo with `(header)`/`(override)` provenance tags called out as the best part of the tool.

**Top friction (ranked; #1 is blocks-adoption tier):**
1. **Unknown header keys warn-and-proceed, exit 0** — and then print the contradictory
   "no [tool.hf-jobs] block" line. A typo'd `flavour`/`hardware`/`secret` silently
   launches on default runtime while the user believes the header protected them —
   the exact silent-wrong-runtime failure the feature exists to prevent. Fix: hard-error
   on unknown keys with did-you-mean + valid-key list (special-case `timeout` → "pass
   --timeout"); never print "no block" when a block exists.
2. Missing/typo'd script path reports "no [tool.hf-jobs] block — passing through"
   (exit 0 on dry-run). Fix: local-looking `.py` path that isn't a file → "script not found".
3. No spend visibility in the echo: `--timeout` (and the 30m default) never shown;
   flavor shown without cost. Fix: echo `timeout = 30m (default)` + `~$/h` next to flavor
   (reuse `top`'s cost table) — ties into the budget-model design.

Polish list (help-text wrapping, empty `--namespace`/`--token` help rows, missing
provenance tag on the `secret =` echo line, document the dotenv double-quoting, state
"these 5 keys are the whole schema") captured in the session UX report.

Also observed in the real run: the first launch failed with the *script's own* clear
error (output column exists — needed `--output-column`), with the header layer invisible
in the failure. Delegation working as designed: jobsx owns the launch, the recipe owns
its args.
