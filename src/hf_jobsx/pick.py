"""Interactive jump-picker. (SPEC §3 pick.py)

Prefer `fzf` if on PATH: pipe `id\\tstatus\\timage\\tcreated` lines, read selection,
os.execvp into `hf jobs <action> <id>`. Built-in fallback only if fzf missing.

Render @N prefix per line — the picker teaches the selector (the core product loop):
browse + enter first time, type `hf jobsx logs -f @2` once you remember the index.

--action logs|ssh|cancel|inspect (default logs). cancel adds a confirm.

NOT YET IMPLEMENTED (Phase 2).
"""

from __future__ import annotations

import shutil


def pick_and_run(*, action: str, namespace: str | None, token: str | None) -> None:
    """List jobs (consume native `hf jobs ps` shape), fzf, exec chosen action. TODO Phase 2."""
    if shutil.which("fzf") is None:
        # POC: require fzf. Built-in fallback is optional; don't over-invest.
        pass
    raise NotImplementedError("Phase 2")
