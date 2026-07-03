"""Diagnostic: prints the raw bytes of each key you press, so we can see exactly
what your terminal sends for arrows (and fix _read_key precisely later).

Run: uv run python3 scripts/keyprobe.py
Press keys; Ctrl-C to quit.
"""

import select
import sys
import termios
import tty

fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
print("Press keys (arrows, j, k, enter, esc). Ctrl-C to quit.")
print("Each line shows the raw bytes as \\x.. escapes.\n")
try:
    tty.setcbreak(fd)
    while True:
        rlist, _, _ = select.select([sys.stdin], [], [], None)
        if not rlist:
            continue
        ch = sys.stdin.read(1)
        # Drain any immediately-following bytes (escape sequences)
        rest = ""
        while select.select([sys.stdin], [], [], 0.02)[0]:
            rest += sys.stdin.read(1)
        raw = ch + rest
        esc = raw.encode("utf-8").decode("unicode_escape").encode("latin1").decode("unicode_escape")
        label = {
            "\x1b[A": "↑ UP",
            "\x1b[B": "↓ DOWN",
            "\x1b[C": "→ RIGHT",
            "\x1b[D": "← LEFT",
        }.get(raw, "")
        print(f"  {raw!r:20} bytes={[ord(c) for c in raw]}  {label}")
        sys.stdout.flush()
        if raw == "\x03":  # Ctrl-C
            break
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print("\n(restored)")
