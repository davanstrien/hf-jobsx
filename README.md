# hf-jobsx

A community [`hf` CLI extension](https://huggingface.co/docs/huggingface_hub/en/guides/cli-extensions) for working with [Hugging Face Jobs](https://huggingface.co/docs/hub/jobs).

It adds ergonomic layers on top of the mature native `hf jobs` surface:

- **Selectors** — address jobs by position or predicate instead of copying IDs:
  `@latest`, `@0`, `@status=running`, `@label=exp`, `@running`
- **`top`** — a dense, Tufte-style live monitor: per-job CPU/GPU/net sparklines, status, runtime, estimated cost, and the inline last log line, all in one glance. Drill into a job's logs/ssh with a keypress and navigate back.
- **`run`** — launch a UV script with its runtime (image, flavor, interpreter, env, secrets) declared once in a `[tool.hf-jobs]` header, so you don't retype the launch flags every time. See [below](#run--launch-a-uv-script-with-its-runtime-baked-into-the-header).
- **`pick`** — *(coming soon)* interactive jump-picker.

> **Status:** beta. `run`, `top`, the selector commands, and back-navigation work. `pick` is a stub. Tested against `huggingface_hub` ≥ 0.25. See [SPEC.md](SPEC.md) for the full design and roadmap.

## Demo

![hf-jobsx demo](demo/hf-jobsx-demo.gif)

A 30s walkthrough: the `jq` ritual → selectors → the `top` monitor with sparklines,
inline tail-logs, and clickthrough. Generated deterministically from fake data
(no compute needed) — see [`demo/make_cast.py`](demo/make_cast.py) to regenerate or tweak.

Play the source cast locally for full fidelity (text, copy-pasteable):

```bash
asciinema play demo/hf-jobsx-demo.cast
```

## Install

```bash
hf extensions install davanstrien/hf-jobsx
```

Then use it as `hf jobsx <command>` (note: HF extensions are top-level, so it's `hf jobsx`, not `hf jobs`).

Requires the `hf` CLI (`pip install huggingface_hub` or [`uv tool install huggingface_hub`](https://huggingface.co/docs/huggingface_hub/en/quick-start)) and `hf auth login`.

## Commands

### Selectors

Every job command accepts a selector instead of a literal ID:

| Selector | Meaning |
|---|---|
| `@0` / `@latest` | the most recent job |
| `@N` | the Nth most recent (0-indexed) |
| `@running` | jobs in the RUNNING stage |
| `@status=error` | jobs in a given stage (`running`, `completed`, `error`, `canceled`, `scheduling`, `deleted`) |
| `@label=exp` / `@label=model=llama` | jobs with a label (key, or key=value) |
| `@me` | all your jobs |
| `a1b2c3d4…` | a literal job ID (also `namespace/id`) |

Combine with commas: `hf jobsx logs -f @0,@2`.

```bash
# The thing this exists for — replace the jq dance:
hf jobsx logs -f @latest          # was: hf jobs logs $(hf jobs ps --json | jq -r '.[0].id') -f

hf jobsx ssh @running             # ssh into your latest running job
hf jobsx cancel @status=error     # (confirm prompt — cancels if exactly one matches)
hf jobsx inspect @0
hf jobsx resolve @me              # show what a selector resolves to (the selector REPL)
```

Single-target commands (`logs`/`ssh`/`cancel`/`inspect`) require exactly one match; if a selector matches several, they error with the list and their `@N` so you can narrow it.

### `top` — live monitor

```bash
hf jobsx top            # running jobs only (a monitor is for active work)
hf jobsx top --all      # include scheduling / error / completed too
```

A dense, single-screen view that refreshes in place:

```
 HF Jobs                                                       3 running / 1 error
 ──────────────────────────────────────────────────────────────────────────────────────
        cpu      gpu      net     id         job              st   run  ~cost  last log
 ▶@0  ▁▃▃▅▅▆▆█ ▁▃▃▄▄▆▆█ ▁▁▃▃▆▆██  a1b2c3d4   baseline         ●  2h14  ~$0.14  step 14010 | loss 0.0493 | lr 2e-5
  @1  ▁▃▃▅▅▇▇█ ▁▂▂▅▅▆▆█ ▁▃▃▅▅▆▆█  b2c3d4e5   big-train        ●  5h0m  ~$0.63  step 31049 | loss 0.0930 | grad_nor…
  @2                              c3d4e5f6   eval             ○    0s      —     (no logs yet)
 ──────────────────────────────────────────────────────────────────────────────────────
  enter logs  ·  s ssh  ·  ↑/↓ or j/k move  ·  q quit
```

Keys: `j`/`k` or arrows to move, `Enter` to follow the selected job's logs, `s` then `Enter` for ssh, `q`/`Esc` to quit. After a drill, `Ctrl-C` the stream and you **return to the monitor** (it doesn't quit). `~cost` is a client-side estimate (runtime × per-flavor price), not Hub billing.

What it shows that native `hf jobs stats` doesn't: **per-resource history** (sparklines, not just the current value) and the **inline tail log** — so "GPU flatlined" reads as "GPU flatlined *and the step froze*", and an OOM shows the error inline next to the job.

### `run` — launch a UV script with its runtime baked into the header

Some recipes *must* launch on a specific image/interpreter/`PYTHONPATH`/flavor — because the model's architecture only exists in that pinned build. Today those launch flags live in the script's docstring, so a caller who omits them gets a **silent, corrupt run** (every row an error sentinel) instead of a clear failure:

```bash
# the incantation you have to know and not fat-finger:
hf jobs uv run --flavor l4x1 -s HF_TOKEN --image vllm/vllm-openai:unlimited-ocr \
  --python /usr/bin/python3 -e PYTHONPATH=/usr/local/lib/python3.12/dist-packages \
  unlimited-ocr-vllm.py in_ds out_ds --max-samples 10
```

`run` lets those parameters **travel with the script** in a `[tool.hf-jobs]` block in the PEP 723 header — the same spec-sanctioned `[tool.*]` mechanism `uv` already uses for `[tool.uv]`, so `uv run` (and everything else) ignores it:

```python
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
```

Then the launch is just:

```bash
hf jobsx run unlimited-ocr-vllm.py in_ds out_ds --max-samples 10
```

`run` reads the header, echoes the resolved runtime, and delegates the actual launch to native `hf jobs uv run`. Explicit flags override the header (`--image`, `--flavor`, `-p/--python`, `-e/--env KEY[=VALUE]`, `-s/--secrets NAME`); launch flags go **before** the script (docker-style), and everything after the script is passed through to the script verbatim. Use `--dry-run` to print the resolved command without launching:

```bash
hf jobsx run --flavor a100-large --dry-run unlimited-ocr-vllm.py in out
```

Runnable examples (a cheap `cpu-basic` one and the vLLM image-mode case) live in [`examples/`](examples/).

> **Scope:** the header carries only what's *script-inherent* — where/whether the script runs: `image`, `flavor` (a suggested default, like a Space's `suggested_hardware`; overridable), `python`, `env`, `secrets` (names). It deliberately omits **`timeout`** (a per-run cost decision that scales with your data — pass `--timeout`) and run/user-specific params (`namespace`, `volumes`, `labels`). Dependency pins stay in `[tool.uv]`, and image/model-specific knobs ride in `env` rather than growing new keys. A header prevents the *human* mistake; it doesn't make a mutable image tag reproducible — pin by digest + add an in-container self-check for that.

## Demo / develop without compute

`top` ships with a deterministic fake mode (no real jobs needed — useful for screenshots/development):

```bash
HF_JOBSX_FAKE=1 hf jobsx top
```

## Design notes

- **Delegates to native** wherever it's good: `logs`/`ssh`/`cancel`/`inspect` resolve a selector then run the real `hf jobs` command. jobsx owns selection + the monitor; native owns depth.
- Selectors are resolved against a fresh `list_jobs()` snapshot each invocation; `@N` is stable for one command but can drift if jobs are created between calls.
- Unix-like terminals only (uses termios for `top`). `top` requires a TTY.

## Limitations

- `pick` is not yet implemented.
- Multi-job log tailing (`tail @all`) and JSON metrics streaming (`watch --json`) are planned, not built — see [SPEC.md](SPEC.md).
- Arrow-key navigation in `top` may be unreliable in some terminals; `j`/`k` always work.
- `~cost` is an estimate.

## License

Apache-2.0
