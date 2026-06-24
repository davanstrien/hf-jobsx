---
title: "hf jobsx — CLI extension spec"
project: hf-jobsx
status: 🟡 planning
priority: high
type: tool
impact: 8
energy: high
next_action: "Read this spec, then scaffold the package and implement Phase 1 (selectors + logs)"
created: 2026-06-24
---

# `hf jobsx` — CLI extension (POC spec)

> **What:** A community `hf` CLI extension (`hf jobsx`) that adds ergonomic, agent-friendly layers on top of the native `hf jobs` surface — an interactive jump-picker, positional/predicate **selectors** (`@N`, `@latest`, `@status=…`), and a dense, Tufte-style live monitor (`top`) with per-resource sparklines and inline tail-log context.
>
> **Why:** Native `hf jobs` is mature for depth-on-one-job (`logs -f`, `ssh`, `inspect`, `stats`) but has **verified gaps** (see [[#Verified gaps vs native]]) in *switching between many jobs* and *ambient multi-job awareness*. The daily pain it targets: `hf jobs logs $(hf jobs ps --json | jq -r '.[1].id') -f` — i.e. selecting a job by position/property then handing its id to a command. `jobsx` makes that native.
>
> **Status:** Spec complete. Not started. Scaffold exists at `/Users/davanstrien/Documents/code/hf-jobsx`.
>
> **Strategic fit:** This is the [[Jobs-CLI-Agent-Ergonomics-Audit]] / [[Jobs-Growth-Strategy]] play. CLI+DX authority positioning, agent ergonomics, experimental playground that can graduate features upstream. Dovetails with the corgi-logs exploration (same streaming layer).

---

## 0. Source of truth & verified facts

Everything below is verified against the actual `huggingface_hub` source at `/Users/davanstrien/Documents/code/huggingface/huggingface_hub` (checkout at `v1.21.0.dev0`, post `v1.20.0` shipped 2026-06-18). **Re-ground before starting** — `jobs logs` and other features changed recently; confirm still-current.

### Public Python API we consume (all top-level importable, verified)

```python
from huggingface_hub import (
    HfApi, JobInfo, JobStatus, JobStage, JobHardware, JobHardwareInfo,
    list_jobs, inspect_job, fetch_job_logs, fetch_job_metrics,
    list_jobs_hardware, wait_for_job,
)
```

- **Do NOT** import from `huggingface_hub._jobs_api` (private). The old `jobs-dashboard` project had this as a listed blocker but it was already fixed to the public path — keep it public here from day one.
- `JobInfo.__module__` is still `huggingface_hub._jobs_api` (the class is *defined* there, *re-exported* at top level). That is the normal, stable re-export pattern. Fine.

### Metrics SSE schema (verified, `hf_api.py:11948-11961`)

`fetch_job_metrics(job_id, namespace)` yields **one dict per second**, forever (stream never ends; Ctrl-C to stop). Shape:

```json
{
  "cpu_usage_pct": 0,
  "cpu_millicores": 3500,
  "memory_used_bytes": 1417216,
  "memory_total_bytes": 15032385536,
  "rx_bps": 0,
  "tx_bps": 0,
  "gpus": {"d901cd7f": {"utilization": 0, "memory_used_bytes": 0, "memory_total_bytes": 22836000000}},
  "replica": "j6qz9"
}
```

- `cpu_usage_pct` — float, 0..100 (can exceed on burst).
- `cpu_millicores` — int. `round(cpu_millicores/1000, 1)` = vCPU.
- memory/net — byte counts + rates; compute % as `100*used/total`.
- `gpus` — a **dict** keyed by gpu id; each has `utilization` (0..100) and memory bytes. Aggregate for a single sparkline as `mean(utilization)` or `max`.

### Native streaming pattern to mirror (`jobs.py:500-535`)

`hf jobs stats` consumes N jobs concurrently with:
```python
with multiprocessing.pool.ThreadPool(len(job_ids)) as pool:
    for done, job_id, rows in iflatmap_unordered(pool, _get_jobs_stats_rows, kwargs_list=...):
        ...
```
with `KeyboardInterrupt` cleanup at `jobs.py:1270`. **Reuse this pattern** for `top` — it is the reference implementation for multi-job metrics streaming. Do NOT invent a new concurrency scheme.

### Verified gaps vs native (scout report, 2026-06-24)

| Feature | Native | Source evidence |
|---|---|---|
| Interactive picker (fzf/arrow-key list → act) | **ABSENT** | only `typer.confirm` exists in entire `cli/` (`_output.py:192`) |
| Multi-job interleaved logs (`[jobid] line`, stern-style) | **ABSENT** | `jobs_logs` is single `JobIdArg` (`jobs.py:374`); only `stats` does multi-job, metrics-only |
| JSON/NDJSON metrics (`--json` on stats) | **ABSENT — structurally** | `jobs_stats` bypasses `out`, calls `print(_tabulate(...))` directly (`jobs.py:510,529`); comment at `jobs.py:507-509` explains in-place ANSI refresh is incompatible with mode-based formatting. Strongest gap — two use cases are incompatible in one command. |
| Selectors (`@latest`, `@N`, `@status=…`, `@label=…`) as targets for logs/ssh/cancel | **ABSENT** | only literal id or `namespace/job_id` (`_parse_namespace_from_job_id`, `jobs.py:60-84`); `--filter` is `ps`-list-only (`jobs.py:547-554`) |

**Native features we lean on (do NOT reimplement):**
- `hf jobs ps --json` → clean JSON array (`jobs.py:623`, via `out.table`/`_output.py:145`). **The picker's data layer is free — consume this.** `-q` prints id-per-line.
- `hf jobs inspect --json` → full `JobInfo` JSON.
- `hf jobs wait <id>... --timeout` → batch multi-job wait with exit-code semantics (`jobs.py:707`). Good composition primitive.
- `hf jobs logs -f <id> --tail N` → single-job streaming, correct `follow=True`. `top`/`pick`/`logs @N` all shell out to this rather than reimplement.
- `hf jobs ssh <id>`, `hf jobs cancel <id>`, `hf jobs hardware` (unit pricing), scheduled CRUD.
- `JobHardwareInfo.unit_cost_usd` (per minute) + `JobDurations.running_secs` → cost is **derivable client-side** (native never exposes it).

---

## 1. Command surface (POC scope)

| Command | Phase | Status | What it does |
|---|---|---|---|
| `hf jobsx top` | 3 | ⭐ star | Dense live monitor: one row per job, sparklines (cpu/gpu/net) + status glyph + runtime + accrued cost + inline last-log-line. Frame-refresh in-place (no alt screen). |
| `hf jobsx pick` | 2 | | Interactive jump: fuzzy-filter job list, `enter`→`exec hf jobs logs -f <id>`, `s`→ssh, `c`→cancel-confirm. fzf if present, else built-in. |
| `hf jobsx logs -f <selector>` | 1 | first | Resolve selector → `os.execvp` into native `hf jobs logs -f <id>`. Thin wrapper. |
| `hf jobsx ssh <selector>` | 1 | | Resolve → `exec` native `hf jobs ssh <id>`. |
| `hf jobsx cancel <selector>` | 1 | | Resolve → native `hf jobs cancel <id>` (confirm if multiple match). |
| `hf jobsx inspect <selector>` | 1 | | Resolve → native `hf jobs inspect <id>`. |
| `hf jobsx resolve <selector>` | 1 | debug | Print resolved job id(s) + the `@N` each maps to. Essential for dev + teaching the selector. |

**Explicitly deferred (document in roadmap, do NOT build in POC):**
- `hf jobsx tail @all` / `tail <selector>` — multi-job interleaved log mux. Needs N-stream log threads. Harder; later.
- `hf jobsx watch <selector> --json` — the one **agent enabler** (NDJSON metrics). Ships right after `top` reuses its metrics substrate. Trivial once `top` exists — it's `top`'s ring-buffer feeder without the renderer.
- `hf jobsx doctor` / `logs --summarize` — agent-in-the-loop (LLM summarizes a traceback). Bigger idea; not v1.
- Cost totals, scheduled management, batch cancel by selector.

**Design stance: dumb pipe, smart edges.** `jobsx` owns *ergonomics and composition* (selection, addressing, dense view) and **delegates everything to native** via `exec`. It does not reimplement listing/running/SSH/logs-rendering. This is simultaneously the Unix-correct, agent-correct, and positioning-correct stance.

---

## 2. Selector grammar & resolution

The single most important module (`hf_jobsx/selectors.py`). Every command that takes a job reference accepts a selector.

### Grammar (BNF-ish)

```
selector      := single | list
list          := single ( "," single )*

single        := position
               | "latest"
               | status_pred
               | label_pred
               | "running"
               | "me"                      # all jobs in my namespace
               | literal_id
               | namespaced_id

position      := "@" INT                  # @0, @1, @2 ... 0 = most recent
status_pred   := "status=" STAGE          # status=running, status=error
label_pred    := "label=" KEY [ "=" VAL ] # label=exp, label=model=llama
literal_id    := HEXID                    # 24-hex job id, raw
namespaced_id := NAME "/" HEXID

# sugar
"running"     := "status=running"
"latest"      := "@0"
```

All selector keywords are case-insensitive. Stages are the real `JobStage` members: `COMPLETED, CANCELED, ERROR, DELETED, SCHEDULING, RUNNING` (no PENDING — that was the old dashboard's bug). Match case-insensitively.

### Resolution semantics

1. **Fresh snapshot every resolve.** Call `list_jobs(namespace)` once, sort by `created_at` desc. This snapshot is the universe for `@N`, `@latest`, `@status`, `@label`, `@me`.
2. **`@N` is positional in that sorted list**, 0-indexed. `@0` ≡ `@latest`. Stable for the lifetime of one command invocation.
3. **Predicate selectors** (`@status=…`, `@label=…`, `@running`, `@me`) may match **multiple** jobs. Behavior depends on command:
   - **Single-target commands** (`logs`, `ssh`, `cancel`, `inspect`): require exactly one match. If 0 → error "no jobs match `<selector>`"; if >1 → error listing the matches with their `@N` so the user can disambiguate (`@3` etc.).
   - **Multi commands** (`top`, `pick`, future `tail`/`watch`): multiple is fine / the point.
4. **Literal ids pass through** unchanged (after `_parse_namespace_from_job_id`-style split).
5. A list selector (`@2,@5,@7` or `@status=running,@latest`) resolves to the union, de-duplicated, order-preserving.

### How the picker/`top` teach the selector

`pick` and `top` **render the `@N` index next to each row**. First time: browse + enter. Third time: you remember it was `@2`, type `hf jobsx logs -f @2`. Interactive mode onboards into compositional mode — one product, two richness levels. This is the core product loop and it's free.

### `resolve` command

```
$ hf jobsx resolve @running
@0  abc123de  RUNNING   baseline-train   a10g-small   2h14
@2  ghi789ab  RUNNING   big-train        a10g-large   5h02
@4  mno99900  RUNNING   distill          cpu-basic    0m12

$ hf jobsx logs -f @2     # then you use what resolve taught you
```

`resolve` is the selector's REPL and the primary debugging tool. Always implement it first.

### Namespace handling

- Default namespace = `whoami()["name"]` (lazy, never call at import; see [[#jobs_clientpy]]).
- `hf jobsx top --namespace my-org` / env `HF_JOBSX_NAMESPACE` override.
- selectors resolve within the active namespace; `namespace/id` literal overrides per-token.

---

## 3. Module layout (the scaffold mirrors this)

```
src/hf_jobsx/
├── __init__.py          # version, public nothing (extension is a CLI)
├── __main__.py          # `hf-jobsx` console-script entry → cli.main()
├── cli.py               # argparse subcommand dispatch (pick typer? see §4)
├── selectors.py         # grammar, parse, resolve — PURE, fully unit-tested
├── jobs_client.py       # thin wrapper around huggingface_hub public API
├── metrics.py           # metrics stream consumer + ring buffer + cost calc — PURE core + threads
├── render.py            # `top` view: sparkline rendering, ANSI in-place refresh, frame loop
├── pick.py              # interactive picker (fzf shell-out, built-in fallback)
└── fake.py              # HF_JOBSX_FAKE deterministic generator for dev + screenshots
```

No god objects. Pure functions (`selectors`, `metrics` math, sparkline) are unit-tested; I/O and concurrency (`jobs_client`, `render`, `pick`) are integration/manual-tested.

### `selectors.py` (pure — test first, test hardest)

Public API:
```python
def resolve_selectors(specs: list[str], jobs: list[JobInfo], *, namespace: str) -> list[JobInfo]:
    """Resolve a list of selector tokens to job ids. Raises SelectorError on ambiguity."""

def index_jobs(jobs: list[JobInfo]) -> dict[int, JobInfo]:
    """Sort by created_at desc, assign @N (0-indexed)."""

class SelectorError(Exception): ...
```

- Sort key: `job.created_at` descending (None-safe; treat None as oldest).
- `@N` bounds check → `SelectorError(f"@{n} out of range (have {len(jobs)} jobs)")`.
- Label predicate: `job.labels` is `dict[str,str] | None`. `label=k` matches key presence; `label=k=v` matches exact.
- Status predicate: compare `job.status.stage.upper()` to the parsed stage `.upper()`.
- **Tests are the spec here.** Cases: `@0`, `@latest`, out-of-range, `@status=error` (0/1/many matches), `@label=exp`, `@label=model=llama` (value with `=`), comma-list, dedup, literal id passthrough, `namespace/id`, case-insensitivity, empty namespace.

### `jobs_client.py` (thin I/O wrapper)

```python
class JobsClient:
    def __init__(self, token=None, namespace=None): ...
    @property
    def namespace(self) -> str: ...   # LAZY whoami, cache result. Never at import.
    def list_jobs(self) -> list[JobInfo]: ...
    def get_job(self, job_id: str) -> JobInfo: ...        # inspect_job
    def fetch_logs(self, job_id, *, follow, tail=None): Iterable[str]: ...
    def fetch_metrics(self, job_id) -> Iterable[dict]: ... # stream, never ends
    def hardware_pricing(self) -> dict[str, JobHardwareInfo]: ...  # list_jobs_hardware, cached
```

- **Lazy namespace** is non-negotiable: auth/network failures must become user-facing errors at command time, not crashes at import. (The old dashboard learned this the hard way — [[hf_jobs]] notes the lazy-namespace fix.)
- `hardware_pricing` cached on the instance (call once per process; pricing changes infrequently).

### `metrics.py` (pure core + the streaming substrate)

Pure (unit-tested):
```python
@dataclass
class Sample:
    ts: float
    cpu_pct: float
    mem_pct: float
    gpu_pct: float | None     # None if no GPUs
    net_bps: int              # rx+tx

def parse_sample(raw: dict, *, ts: float | None=None) -> Sample: ...
def agg_gpu(gpus: dict) -> float | None: ...               # mean utilization
def push(ring: deque[Sample], s: Sample, maxlen: int=48) -> deque[Sample]: ...
def accrued_cost(job: JobInfo, pricing: dict[str, JobHardwareInfo]) -> float | None:
    # running_secs (or finished-started) * unit_cost_usd_for_flavor / 60
    # None if flavor unknown or durations missing.  APPROXIMATE — document loudly.
def to_sparkline(ring: deque[Sample], attr: str, *, width: int=8) -> str: ...  # ▁▂▃▅▇▇▇
```

Streaming substrate (the architectural correction — this is where the old project was wrong):
```python
class MetricsFanIn:
    """One daemon thread per job, each consuming fetch_metrics() SSE.
    Pushes (job_id, Sample) onto a thread-safe queue. Main thread drains on frame clock."""
    def start(self, job_ids: list[str]): ...
    def stop(self): ...   # signal + join; metrics SSE never ends so threads must be killed
    def samples(self) -> Iterator[tuple[str, Sample]]: ...
```

- **Threads are daemons** (metrics SSE never ends; on Ctrl-C the process exits). Use a `threading.Event` stop-flag + best-effort join(0.5). Accept that a thread blocked in socket `recv()` may linger — daemon status makes this safe. **Document this trade-off** (it's the honest version of what the old project's `consume_with_timeout` pretended to fully solve).
- Reference impl to mirror: `jobs.py:500-535` (`iflatmap_unordered` + ThreadPool + KeyboardInterrupt at 1270). Reuse the pattern; don't reinvent.

**Cost caveat (put in `--help` and README):** `accrued_cost` is a **client-side estimate** (`flavor × running_secs × unit_cost_usd`), not server billing. For running jobs it ticks up live; for finished jobs it's a fixed final estimate. Real billing lives in Hub settings. Label the column `~$` to signal approximation.

### `render.py` (`top` — the star, the social artifact)

Responsibilities:
1. Maintain per-job `deque[Sample]` ring buffers (cpu/gpu/net) of `~48` samples.
2. Maintain per-job last-seen log line (cheap: poll `fetch_logs(tail=1)` every ~3s, or skip if too costly in POC).
3. Frame loop: every `500ms`–`1s`, redraw the whole table **in-place** (no alt screen — follow `stats`' `_clear_line` pattern so scrollback survives and Ctrl-C is clean).
4. Honor terminal width: drop columns gracefully (cost first, then sparklines shrink, then status glyph stays last).

Layout (the mockup that becomes the gif):
```
 HF Jobs                                                       3 running / 1 error
 ──────────────────────────────────────────────────────────────────────────────────────
  cpu       gpu       net      id       job           st  run    $      last
  ▁▂▃▅▇▇▇   ▃▅▇▉▇▅▃   ▁▂▃▅     abc123   baseline      ●   2h14   1.42   step 14024 | loss 0.187
  ▇▇▇▇▇▇▇   ▇▇▇▇▇▇▇   ▂▃▅▆     ghi789   big-train     ●   5h02   8.71   step 31200 | loss 0.094
  ▁▁▁▁▁▁▁   ▁▁▁▁▁▁▁   ▁▁▁▁     def456   eval          ○   0m     —      queued
  ▃▄▅▆▇▉█   █▉▇▆▅▄▃   ▂▅▇▉     jkl012   distill       ✕   1h30   0.88   RuntimeError: CUDA OOM
 ──────────────────────────────────────────────────────────────────────────────────────
  @0 abc123   @1 ghi789   @2 def456   @3 jkl012                  enter:logs  s:ssh  c:cancel  q:quit
```

- **Status glyphs:** `●`=RUNNING, `○`=SCHEDULING, `✕`=ERROR, `■`=CANCELED, `✓`=COMPLETED, `🗑`=DELETED. (Real `JobStage` members — no phantom PENDING.)
- **Sparklines:** block elements `▁▂▃▄▅▆▇█` (8 buckets). Older→newer left→right. Scale per-metric to its own max so a flat metric doesn't vanish. Color: green normal, yellow when sustained >85%, red when 0% while RUNNING (stall signal — the "GPU flatlined" hero moment).
- **Inline tail line:** last log line, truncated to remaining width. This is the semantic-context win over native `stats` (which shows GPU% but not that the step froze). Strip ANSI/timestamps from the log line.
- **`@N` footer:** always render the index mapping — the teaching loop.
- **No alt screen, no borders, no chrome.** One rule line top and bottom. That's the Tufte discipline: max data-ink, direct labels, word-sized history. (The old dashboard's `border: solid $primary` + section titles + loading spinners is exactly what NOT to do.)

Refresh mechanics (copy `stats`):
```python
LINE_UP = "\033[1A"; LINE_CLEAR = "\x1b[2K"
def clear_lines(n): for _ in range(n): print(LINE_UP, end=LINE_CLEAR)
```
Print table; next frame `clear_lines(rendered_height)` then reprint. Track rendered height to clear correctly (variable job count makes this fiddly — test it).

### `pick.py`

- Prefer `fzf` if on PATH: pipe `id\tstatus\timage\tcreated` lines to `fzf --delimiter=\t --with-nth 2.. --header ...`, read selection, `os.execvp("hf", ["hf","jobs","logs","-f", chosen_id])`.
- `--action logs|ssh|cancel|inspect` (default `logs`). `cancel` adds a confirm.
- No fzf → minimal built-in: raw/canonical mode interactive list, `j/k` move, `enter` select, `s`/`c` hotkeys. Only build this if fzf missing; don't over-invest.
- Show `@N` prefix on each line (teaching loop).

### `fake.py` — **essential for the social post**

`HF_JOBSX_FAKE=1` swaps `JobsClient` for a deterministic fake:
- 5–8 fake jobs (mix of RUNNING/SCHEDULING/ERROR/COMPLETED), realistic names.
- A metrics simulator: per-job `Sample` generators with realistic shapes — one steadily climbing, one flatlined (the OOM hero), one ramping, one idle. Deterministic seed so the gif is reproducible.
- Fake log lines that advance ("step 14024 | loss 0.187" ticking up; "RuntimeError: CUDA OOM" for the error job).

**This is how you make a clean gif without burning GPU compute.** Build it early — it's also how you develop `top` without a live cluster. Default the demo screenshots to fake mode; document real usage separately.

---

## 4. CLI framework choice

The native CLI uses **typer**. For consistency and discoverability, use **typer** too. But: extensions are standalone console scripts invoked by `hf`'s dispatch — they do NOT run inside the native typer app. So `hf_jobsx/__main__.py` has its own typer app:

```python
import typer
app = typer.Typer(help="hf jobsx — ergonomic HF Jobs CLI extension")
# app.command()(top), app.command()(pick), etc.
def main(): app()
```

Console-script entry point **must be named `hf-jobsx`** (extension convention — `hf jobsx` dispatches to the installed `hf-jobsx` binary). `pyproject.toml`:
```toml
[project.scripts]
hf-jobsx = "hf_jobsx.__main__:main"
```

**Do NOT** put an executable file named `hf-jobsx` at the repo root — the installer checks for a root binary *first* and would treat the repo as a shell-script extension. Just `pyproject.toml` + `src/`.

---

## 5. Packaging

Python extension (isolated venv on install — deps won't conflict with user's system).

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "hf-jobsx"
version = "0.1.0"
description = "Ergonomic HF Jobs CLI extension: jump-picker, selectors, dense live monitor"
requires-python = ">=3.10"
dependencies = ["huggingface-hub>=0.25.0"]
# rich is OPTIONAL — only add if the built-in picker needs it. Keep POC deps minimal.
license = "Apache-2.0"

[project.scripts]
hf-jobsx = "hf_jobsx.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/hf_jobsx"]
```

Install (dev): `hf extensions install <owner>/hf-jobsx --force` (after pushing to GitHub), or test locally with `pipx install -e .` / `uv run hf-jobsx`. Repo **must** be named `hf-jobsx` on GitHub. Add topic `hf-extension` for discoverability via `hf extensions search`.

Manifest description: set `description` in pyproject (the installer reads it) — no separate `manifest.json` needed for Python extensions.

---

## 6. Phased build plan

Each phase ships a working thing. Commit per phase.

### Phase 0 — Scaffold + packaging (~2h)
- [x] Repo `hf-jobsx`, pyproject, `src/hf_jobsx/` package, typer app with `--help` only.
- [ ] `hf jobsx` resolves (via local install / `uv run`) and prints help. `hf jobsx resolve --help` listed.
- [ ] CI: pytest + ruff (copy pattern from any HF repo).

### Phase 1 — Selectors + thin wrappers (~1 day)
- [ ] `selectors.py` fully implemented + **exhaustive unit tests** (the cases in §3). This is the foundation; get it bulletproof.
- [ ] `jobs_client.py` (lazy namespace, list_jobs, inspect, hardware_pricing cache).
- [ ] `resolve` command working against live `list_jobs`.
- [ ] `logs`/`ssh`/`cancel`/`inspect` selector wrappers (resolve → `os.execvp` into native `hf jobs <cmd>`).
- [ ] Manual test matrix: real job ids, `@0`, `@status=error` ambiguous error, `@label=…`, comma-list.

### Phase 2 — `pick` (~½ day)
- [ ] fzf shell-out path. Built-in fallback only if time.
- [ ] `@N` prefix rendered; `--action` flag; `enter`/`s`/`c`.
- [ ] This is the first "feels magical" moment — demo it.

### Phase 3 — `top` (the star, ~2–3 days)
- [ ] `metrics.py` pure core (Sample, ring buffer, cost, sparkline) + **unit tests**.
- [ ] `MetricsFanIn` streaming substrate (mirror `stats` pattern). Verify multi-job fan-in works against a cluster with 2+ running jobs.
- [ ] `render.py` frame loop + in-place ANSI refresh + layout + status glyphs + sparkline coloring + tail-line polling.
- [ ] `fake.py` deterministic generator.
- [ ] **The gif.** Side-by-side: `hf jobs stats` (snapshot, no history) vs `hf jobsx top` (sparklines + tail context + `@N`). The OOM-row-turning-red is the hero frame.

### Phase 4 (post-POC, document only)
- [ ] `watch --json` (agent enabler) — strip the renderer off `top`'s feeder, emit NDJSON. ~½ day.
- [ ] `tail @all` multi-log mux.
- [ ] Cost totals, batch cancel by selector, scheduled support.

---

## 7. Testing strategy

Pragmatic (like the old dashboard intended but didn't always execute):

- **Unit-test hard the pure core:** `selectors.py` (exhaustive — ambiguity, bounds, dedup, case), `metrics.py` math (parse_sample, agg_gpu, cost, sparkline bucketing, ring buffer overflow). These have zero I/O; no excuse not to cover them.
- **Do NOT unit-test** the typer wiring or `render`'s ANSI output beyond smoke ("renders without crashing at 80x24 and 200x24").
- **Concurrency:** document a manual test matrix (2+ running jobs, Ctrl-C clean exit, job transitions RUNNING→COMPLETED mid-view). The honest stance: thread-leak in metrics SSE is *managed* (daemon threads), not *eliminated* — say so in code comments + README.
- **`HF_JOBSX_FAKE=1`** doubles as a test fixture and the screenshot generator. Use it in a couple of "render doesn't crash on N fake jobs" smoke tests.

---

## 8. The social / visibility plan

Goal: ship `top` as a distinctive, on-brand artifact.

- **The post:** a gif. Native `hf jobs stats` on the left (snapshot table, no history), `hf jobsx top` on the right (sparklines + tail + `@N`). Caption: the `jq` line → `hf jobsx logs -f @2` before/after.
- **Hero moment:** the CUDA-OOM row going red while GPU sparkline flatlines. `fake.py` makes this reproducible.
- **Channels:** [[Impact/social-platform-strategy]] — LinkedIn (main, open-model/benchmark framing doesn't apply; frame as "DX for distributed training"), X (demo-first + "one command" CTA), Bluesky cross-post + GLAM angle.
- **Upstream play:** `watch --json` and the selector grammar are the two features worth proposing as native `hf jobs` enhancements (issues, per the May contribution policy — exploratory/ergonomic = PR-worthy, incremental wire-up = issue). Tag Lucain + Julien. This is the [[Jobs-Growth-Strategy]] move.

---

## 9. Honest risks & decision log

- **Concurrency honesty:** metrics SSE never ends; threads blocked in `recv()` may linger on exit. Daemon threads make this safe-but-unexamined. The old dashboard's `consume_with_timeout` *pretended* to fully solve this and didn't (it only worked for interruptible blocks). We acknowledge the trade-off openly. → see §3 `metrics.py`.
- **Cost is an estimate.** `~$` label. Don't imply it's billing.
- **`@N` drift:** the index is a snapshot; if a job is created between `resolve` and `logs`, `@2` shifts. Acceptable for a CLI; document it. (Could add `--frozen` snapshot semantics later; not now.)
- **Why not evolve the old `jobs-dashboard`?** Its architecture is wrong (refetch-all-logs-every-2s instead of streaming; inspector not monitor), its differentiators eroded (`hf jobs ssh` shipped 2026-06-18 killing the SSH angle; web dashboard materialized), and its data model is one-job-at-a-time. This is a clean restart that gets streaming right and targets the actual pain (switching/monitoring, not inspecting). See [[hf_jobs]] for the full post-mortem.
- **Extension can't be `hf jobs <cmd>`.** Top-level only (`hf jobsx`). The `x` signals experimental and mirrors `hf jobs` for muscle memory. If a feature graduates upstream, it becomes real `hf jobs <cmd>`.

---

## 10. Picking-it-up checklist (for future-me / delegated session)

1. Re-ground: `read` `cli/jobs.py` + `_jobs_api.py` in the hub checkout — confirm gaps + metrics schema still hold. (10 min.)
2. `cd /Users/davanstrien/Documents/code/hf-jobsx` — scaffold exists; run `uv run hf-jobsx --help` to confirm packaging.
3. Start Phase 1 (`selectors.py` + tests). It's pure, fast, and is the foundation everything trusts.
4. Keep `fake.py` close — develop `top` against fakes, verify against a real cluster last.

---

## Related
- [[hf_jobs]] — old dashboard post-mortem (architecture wrong, focus off)
- [[Jobs-CLI-Agent-Ergonomics-Audit]]
- [[Jobs-Growth-Strategy]]
- [[Jobs-Adoption-Research-2026-06-02]]
- [[hf_jobs#Contribution policy (May 2026)]]
