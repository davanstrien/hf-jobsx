# hf-jobsx

Community `hf` CLI extension for Hugging Face Jobs: ergonomic layers on top of the mature native `hf jobs` surface.

**Status: scaffold only — not yet functional.** See `SPEC.md` for the full design, or the Obsidian note `Projects/HF Jobs/jobsx.md`.

## Planned commands

- `hf jobsx top` — dense, Tufte-style live monitor (sparklines + inline tail-log context + `@N` indexes)
- `hf jobsx pick` — fuzzy jump-picker → `hf jobs logs -f <id>`
- `hf jobsx logs -f @2` / `ssh @latest` / `cancel @status=error` — positional & predicate selectors
- `hf jobsx resolve @running` — show what a selector resolves to (also the selector REPL)

Everything delegates to native `hf jobs` for depth (logs/ssh/cancel run the real commands via `exec`).

## Dev

```bash
uv sync
uv run hf-jobsx --help        # confirms packaging works (Phase 0)
HF_JOBSX_FAKE=1 uv run hf-jobsx top   # once Phase 3 lands
```

Install as an extension (after pushing to GitHub as `hf-jobsx`):
```bash
hf extensions install <owner>/hf-jobsx
```
