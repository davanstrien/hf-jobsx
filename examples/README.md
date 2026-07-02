# Examples

Self-contained UV scripts that carry a `[tool.hf-jobs]` runtime block in their PEP 723 header,
for trying and testing `hf jobsx run`. Each header is invisible to `uv run` and everything else —
it only affects `hf jobsx run` (see the [`run` section](../README.md#run--launch-a-uv-script-with-its-runtime-baked-into-the-header)).

| File | Runtime it declares | Notes |
|---|---|---|
| [`hello-jobs.py`](hello-jobs.py) | `cpu-basic`, a `GREETING` env var | Cheap enough to actually launch. Good first end-to-end test. |
| [`image-mode-vllm.py`](image-mode-vllm.py) | pinned vLLM image + interpreter + `PYTHONPATH` + `HF_TOKEN` | The motivating case — mirrors real `uv-scripts/ocr` recipes. `--dry-run` demo (needs the image + a GPU to run for real). |

```bash
# print the resolved `hf jobs uv run` command without launching anything
# (launch flags like --dry-run go BEFORE the script; everything after it goes to the script)
hf jobsx run --dry-run examples/hello-jobs.py
hf jobsx run --dry-run examples/image-mode-vllm.py in_ds out_ds --max-samples 10

# actually launch the cheap one on cpu-basic (--name goes to the script)
hf jobsx run examples/hello-jobs.py --name Daniel
```

Running from a checkout (before installing as an extension):

```bash
uv run hf-jobsx run --dry-run examples/hello-jobs.py
```
