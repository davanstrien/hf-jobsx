# hf-jobsx

A community [`hf` CLI extension](https://huggingface.co/docs/huggingface_hub/en/guides/cli-extensions) for working with [Hugging Face Jobs](https://huggingface.co/docs/hub/jobs).

It adds ergonomic layers on top of the mature native `hf jobs` surface:

- **Selectors** — address jobs by position or predicate instead of copying IDs:
  `@latest`, `@0`, `@status=running`, `@label=exp`, `@running`
- **`top`** — a dense, Tufte-style live monitor: per-job CPU/GPU/net sparklines, status, runtime, estimated cost, and the inline last log line, all in one glance. Drill into a job's logs/ssh with a keypress and navigate back.
- **`pick`** — *(coming soon)* interactive jump-picker.

> **Status:** beta. `top`, the selector commands, and back-navigation work. `pick` is a stub. Tested against `huggingface_hub` ≥ 0.25. See [SPEC.md](SPEC.md) for the full design and roadmap.

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
