# /// script
# requires-python = ">=3.11"
# dependencies = ["datasets", "huggingface-hub", "pillow", "tqdm", "toolz"]
#
# [tool.hf-jobs]
# # The model's architecture ships only in this vendor vLLM image, and uv must reuse the
# # image's interpreter + site-packages (a fresh venv lacks it -> every output row an error
# # sentinel). These are exactly the submit-time params `uv` itself cannot see.
# image = "vllm/vllm-openai:unlimited-ocr"
# flavor = "l4x1"
# python = "/usr/bin/python3"
# env = { PYTHONPATH = "/usr/local/lib/python3.12/dist-packages" }
# secrets = ["HF_TOKEN"]
# ///
"""Illustrative example of the image-mode case `hf jobsx run` exists for.

This mirrors the real `uv-scripts/ocr` recipes (e.g. `unlimited-ocr-vllm.py`) that MUST launch
on a pinned vendor image with the image's own interpreter + PYTHONPATH. It needs that image and
a GPU to run for real, so treat it as a `--dry-run` demo of how the header collapses the launch:

    # what you'd otherwise have to remember and not fat-finger:
    hf jobs uv run --flavor l4x1 -s HF_TOKEN --image vllm/vllm-openai:unlimited-ocr \\
      --python /usr/bin/python3 -e PYTHONPATH=/usr/local/lib/python3.12/dist-packages \\
      image-mode-vllm.py in_ds out_ds --max-samples 10

    # with the header, the runtime travels with the script (--dry-run BEFORE the
    # script — anything after it goes to the script itself):
    hf jobsx run --dry-run examples/image-mode-vllm.py in_ds out_ds --max-samples 10
"""

raise SystemExit(
    "This is a --dry-run demo of the image-mode header; it needs the pinned vLLM image + a GPU "
    "to run for real. See the real recipes in uv-scripts/ocr."
)
