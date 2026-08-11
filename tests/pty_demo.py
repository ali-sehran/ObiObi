"""Runs obiobi in a real pty and prints what the terminal actually received.

    python3 tests/pty_demo.py          # readable, colours stripped
    python3 tests/pty_demo.py --raw    # keep the ANSI codes
"""
import os
import pty
import re
import select
import sys
import time

ASK = "??ask: check all installed modules and packages"
SCRIPT = [(0.9, ASK), (1.2, "\t"), (0.5, "\r"), (1.5, "\x04")]  # type, Tab, Enter, Ctrl-D
ANSI = re.compile(rb"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][A-Z0-9]|\x1b[=>]|\r")


def main() -> int:
    raw = "--raw" in sys.argv
    env = dict(os.environ, TERM="xterm-256color", COLUMNS="100", LINES="24",
               OBIOBI_BACKEND="heuristic")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, [sys.executable, "-m", "obiobi"], env)

    out = bytearray()
    start = time.time()
    step = 0
    deadline = start + SCRIPT[0][0]
    while time.time() - start < 8:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
        if step < len(SCRIPT) and time.time() >= deadline:
            os.write(fd, SCRIPT[step][1].encode())
            step += 1
            if step < len(SCRIPT):
                deadline = time.time() + SCRIPT[step][0]
            else:
                deadline = float("inf")
    os.close(fd)

    data = bytes(out)
    sys.stdout.write("=" * 78 + "\n")
    sys.stdout.buffer.write(data if raw else ANSI.sub(b"", data))
    sys.stdout.write("\n" + "=" * 78 + "\n")
    if b"pip list" in data:
        print("OK: the suggestion reached the terminal")
    if b"38;5;243" in data or b"767676" in data or b"#767676" in data:
        print("OK: grey styling emitted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
