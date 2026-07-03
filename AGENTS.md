# AGENTS.md

Guidance for AI agents (and humans) working on `hf-jobsx`.

## What this is

A community [`hf` CLI extension](https://huggingface.co/docs/huggingface_hub/en/guides/cli-extensions) for [Hugging Face Jobs](https://huggingface.co/docs/hub/jobs). Adds ergonomic layers over the mature native `hf jobs` surface:

- **Selectors** (`@N`, `@latest`, `@status=running`, `@label=exp`, …) — address jobs without copying IDs. Replaces `hf jobs logs $(hf jobs ps --json | jq …) -f` with `hf jobsx logs -f @latest`.
- **`top`** — a dense, Tufte-style live monitor (sparklines + inline tail-log + cost), with clickthrough into logs/ssh and back-navigation.

Installed as `hf extensions install davanstrien/hf-jobsx`; runs as `hf jobsx <cmd>` (extensions are top-level, not subcommands of `hf jobs`).

Full design + roadmap: **[SPEC.md](SPEC.md)** (also mirrored at `Projects/HF Jobs/jobsx.md` in Daniel's Obsidian vault).

## Commands

```bash
uv sync                                       # install deps
uv run pytest -q                              # tests (52, ~2s)
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/  # lint
uv run hf-jobsx --help                        # run locally

HF_JOBSX_FAKE=1 uv run hf-jobsx top           # monitor with deterministic fake data (no compute)
uv run hf-jobsx resolve @me                   # against real jobs
```

Lint clean + tests green is the bar before committing. Run `uv run ruff check --fix && uv run ruff format` to autofix.

## Architecture

```
src/hf_jobsx/
  cli.py         # typer app; resolve/logs/ssh/cancel/inspect exec into native hf jobs; top/pick
  selectors.py   # PURE: grammar + resolution (@N, predicates, literals). Fully unit-tested.
  jobs_client.py # thin wrapper around huggingface_hub public API. LAZY namespace.
  metrics.py     # PURE core (parse_sample, sparkline, accrued_cost) + MetricsFanIn/MonitorState
  render.py      # top: render_lines + _redraw + _monitor_session + _drill_subprocess (the hairy bit)
  runspec.py     # PURE: parse [tool.hf-jobs] PEP 723 header -> native `hf jobs uv run` flags (for `run`)
  pick.py        # STUB
  fake.py        # HF_JOBSX_FAKE=1 client (deterministic jobs + metrics sim)
```

**Design stance — dumb pipe, smart edges:** jobsx owns *selection + the monitor* (and, for `run`, *reading the header*). It **delegates depth to native** (`logs`/`ssh`/`cancel`/`inspect` resolve a selector, then `os.execvp`/subprocess into real `hf jobs`; `run` resolves the header, then `os.execvp` into `hf jobs uv run`). Do not reimplement listing/running/SSH/log-rendering.

**Streaming done right:** `top` consumes `fetch_job_metrics()` as an SSE stream into per-job ring buffers — not the refetch-whole-buffer-every-2s hack that sank the predecessor project (`jobs-dashboard`). See the module docstring in `metrics.py`.

### Gotchas (learned the hard way)

- **`JobInfo`/`JobHardwareInfo` take camelCase kwargs** (`createdAt`, `dockerImage`, `prettyName`, `unitCostMicroUSD` — note the exact `MicroUSD` casing). The type *annotations* say snake_case; the custom `__init__`s disagree. Hit KeyError twice during the build. `parse_datetime` wants the `...Z` suffix, not isoformat's `+00:00`.
- **`flavor` / `status.stage` arrive as raw strings** from the real API, not enums — but the annotations claim enums. `selectors.stage_str()`/`flavor_str()` handle both. Never assume.
- **Real `JobStage` members:** `COMPLETED, CANCELED, ERROR, DELETED, SCHEDULING, RUNNING`. There is **no `PENDING`**. (The old dashboard invented one — that was a bug.)
- **Terminal rendering in `top`:** use the alt-screen + clear-and-home-per-frame pattern in `_redraw`, with every line hard-fit to width (`_fit`, ANSI-aware) so wrapping is impossible. The cursor-up approach drifted ("pushed up") when lines wrapped. Every frame: clamp `selected` to `len(jobs)-1` (jobs vanish from the running-only view as they complete → IndexError otherwise).
- **Don't import from `huggingface_hub._jobs_api`** (private). Everything is top-level: `from huggingface_hub import JobInfo, HfApi, list_jobs, fetch_job_metrics, …`.

## Testing philosophy

Test the **pure core hard** (`selectors`, `metrics` math, `render` output shape). These have no I/O; no excuse not to cover them — and they're the foundation everything trusts.

**Manual/integration only:** the terminal/threading layer (`render`'s run loop, `_cbreak`, `MetricsFanIn`). There's no harness for it. `HF_JOBSX_FAKE=1` is how you exercise `top` without a live cluster. Build regression tests for specific bugs found (see `test_render.py`), not aspirational coverage.

Tests use the **real `JobInfo` constructor**, never `MagicMock` strings — that's how the old project shipped with two showstopper bugs no test could catch.

## Open issues

Tracked here (repo is public but small; this list is the issue tracker). Strike through when fixed.

- [ ] **`pick` is a stub** (Phase 2). fzf-based jump-picker → exec into logs/ssh. See `pick.py` + SPEC §6 Phase 2.
- [ ] **Arrow-key navigation in `top` unreliable** in some terminals; `j`/`k` always work. `_read_key` reads exactly 2 bytes after ESC; terminals that send sequences differently (or with latency) get misread. `scripts/keyprobe.py` captures raw bytes to diagnose per-terminal. Likely fix: drain bytes one-at-a-time with short waits instead of `read(2)`.
- [ ] **`_started` is a module-global** (`render.py`), never reset between runs. Harmless (each CLI invocation is a fresh process) but architecturally smelly — should be instance state on `MetricsFanIn`. The `_started_lock` is also unnecessary (only the main thread mutates it).
- [ ] **Lockless reads of `state.jobs`** in `_poll_logs_loop` / `_maybe_start_new_streams`. Safe under CPython's GIL (the list ref is replaced atomically, never mutated), but not free-threading-safe. Document or route through the lock.
- [x] ~~**No CI.**~~ GitHub Actions workflow added (`.github/workflows/ci.yml`): ruff + pytest on 3.10 (tomli fallback path) and 3.13.
- [ ] **Planned features (SPEC §1):** `tail @all` (multi-job interleaved log mux), `watch --json` (NDJSON metrics — the agent-enabler), `doctor`/`logs --summarize` (agent-in-the-loop). Each documented in SPEC; none built.
- [ ] **`_drill_subprocess` in fake mode** shells out to real `hf jobs logs <fake-id>` which 404s. Back-navigation only makes end-to-end sense against real jobs. (Acceptable for now; fake is for monitor-UI dev.)

Deferred from the 2026-07 `run` deep review (nits, not bugs — deliberately not fixed then):

- [ ] **Bare `-e KEY` diverges from native for the stored login**: native's extended environ resolves `HF_TOKEN` via `get_token()` even when the env var is unset; jobsx checks `os.environ` only, so a logged-in user gets "not set in your environment, skipping". Also: jobsx materializes the resolved value into the exec'd argv (`ps`-visible, echoed in `--dry-run`), where native resolves bare keys in-process. Fine for ordinary vars; nudge users to `-s` for anything sensitive.
- [ ] **URL scripts are fetched twice** — once client-side for the header, once by native/remote for the run. Cheap fix if it ever matters: stream + read a bounded prefix (the PEP 723 block must be at the top).
- [ ] **`resolve(header, overrides)` takes a stringly-typed dict** — a typo'd key ("secret" vs "secrets") is silently ignored. Keyword params would let the type checker catch it and drop the `{"env": {}, "secrets": []}` boilerplate from ~10 test call sites.
- [ ] **The "silent corrupt run / error sentinel" motivation story is told in ~5 places** (runspec docstring, cli docstring, README, example, test preamble). One canonical telling (README) + pointers would stop drift.

## Conventions

- Commit style: `feat(top): …`, `fix(review): …`, `docs: …`. Reference SPEC phases where relevant.
- `~cost` is an estimate (runtime × per-flavor price), NOT Hub billing. Keep the `~` prefix in the column.
- The "job" column uses `job_name()` (prefers a name-like label: `name`/`job`/`run`/`exp`), not the image — the image can't distinguish two runs of the same image.
