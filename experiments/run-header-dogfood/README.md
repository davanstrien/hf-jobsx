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
      `davanstrien/run-header-dogfood-test`, `--max-samples 5 --timeout 20m`, job
      `6a47821433c08a2c0dae2d63`. RESULT: _pending — fill in on completion._

## UX verdict

_To fill after the run + fresh-eyes subagent review._
