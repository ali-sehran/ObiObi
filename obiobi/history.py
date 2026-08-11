"""The user's real shell history, read and written in place.

obiobi does not keep a history of its own. It reads `~/.bash_history` or
`~/.zsh_history` directly and appends to it, so:

  * Up-Arrow in obiobi walks the commands you ran in your normal terminal
  * the grey inline suggestion is drawn from those same commands
  * anything you run in obiobi shows up in `history` in every other terminal

zsh's file is written in one of two shapes depending on `EXTENDED_HISTORY`,
so the existing file decides which one we append in - guessing wrong makes
every entry read as literal `: 1699999999:0;ls` at the prompt.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Optional

from prompt_toolkit.history import History

from .config import DATA_DIR, user_shell

# `: 1699999999:0;git status`
ZSH_META = ": "


def shell_history_file() -> Optional[Path]:
    """Where the login shell keeps its history, if we know the format."""
    env = os.environ.get("HISTFILE")
    if env:
        return Path(env).expanduser()
    name = os.path.basename(user_shell())
    if "zsh" in name:
        return Path.home() / ".zsh_history"
    if "bash" in name:
        return Path.home() / ".bash_history"
    return None            # fish and friends: unknown format, stay out of it


def _fallback() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "history"


def history_file() -> Path:
    return shell_history_file() or _fallback()


def _strip(line: str) -> str:
    """One stored line -> the command a user actually typed."""
    if line.startswith(ZSH_META) and ";" in line:
        return line.split(";", 1)[1]
    return line


def _uses_zsh_metadata(path: Path) -> bool:
    """Match whatever shape the file is already in."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    return line.startswith(ZSH_META)
    except OSError:
        pass
    return "zsh" in os.path.basename(user_shell())


def is_noise(cmd: str) -> bool:
    """Lines that must never come back as a one-Tab inline suggestion.

    Two kinds. Questions - a `??ask:` line typed into a normal shell is a
    question, not a command, and replaying it does nothing. And anything the
    safety screen blocks: `rm -rf /` already in the file must not be one
    keystroke from the prompt just because it was run once.
    """
    from .nl2cmd import is_meta
    from .safety import screen

    if cmd.lstrip().startswith("??") or is_meta(cmd):
        return True
    return screen(cmd).blocked


def read(limit: int = 0, raw: bool = False) -> list[str]:
    """Commands, oldest first. `limit` keeps only the newest N.

    `raw` keeps the noise, for anything that wants the file verbatim.
    """
    path = history_file()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out, pending = [], ""
    for line in text.splitlines():
        if not line.strip() and not pending:
            continue                      # a blank line is not a command
        body = _strip(line)
        # A trailing backslash continues the command onto the next line. Taking
        # only the first physical line used to hand the suggester half a
        # command - `docker run \` on its own does nothing.
        if body.rstrip().endswith("\\"):
            pending += body.rstrip()[:-1]
            continue
        cmd = (pending + body).strip()
        pending = ""
        if cmd and (raw or not is_noise(cmd)):
            out.append(cmd)
    if pending.strip():
        out.append(pending.strip())
    return out[-limit:] if limit else out


def numbered(limit: int = 0) -> list:
    """[(line number, command)] - positions in the history file.

    These deliberately are not the numbers your shell prints, because those
    cannot be reproduced from another process. A shell's history number is a
    per-session counter: at startup bash loads the last HISTSIZE lines and
    numbers them from 1, then keeps incrementing for every command you type.
    Measured on this machine: bash held 500 entries numbered 2..501 while the
    file had 504 lines, and a second terminal opened a minute later would
    number the same commands differently again.

    So a file position is the only number that means anything to two processes
    at once. It also matters that these are not offered as `!123` targets -
    `!123` resolves against the shell's counter, and a number from here would
    fetch the wrong command.

    Nothing is filtered: `history` should mirror what happened. The noise
    filter is for the inline suggester, which answers a different question -
    what is worth replaying, not what was run.
    """
    rows = list(enumerate(read(raw=True), 1))
    return rows[-limit:] if limit else rows


def append(command: str) -> None:
    """Add one command, in the format the file is already using."""
    command = command.strip()
    if not command:
        return
    path = history_file()
    entry = (f"{ZSH_META}{int(time.time())}:0;{command}\n"
             if _uses_zsh_metadata(path) else f"{command}\n")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        pass          # a read-only or missing HISTFILE is not worth an error


def write_docs(pairs: list, path: Optional[Path] = None) -> Path:
    """Dump this session's questions and answers to a small text file.

    Written to the current directory so it lands where you were working, and
    stamped so a second `??docs` never overwrites the first.
    """
    path = path or Path.cwd() / time.strftime("obiobi-%Y%m%d-%H%M%S.md")
    lines = [f"# obiobi session - {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"_{len(pairs)} question{'' if len(pairs) == 1 else 's'}_", ""]
    for i, (question, command) in enumerate(pairs, 1):
        lines += [f"## {i}. {question}", "", "```sh", command, "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# bash reads the history file once at startup and writes its own lines back
# only on exit, so a command obiobi appends mid-session is invisible to an
# already-open terminal, and that terminal's commands are invisible on disk.
# These make both sides flush and re-read after every command.
# `history -a; history -n` looks right and loses lines: -a advances bash's read
# offset past anything another process appended since the last read, so a
# command obiobi wrote while bash sat at its prompt is skipped for good.
# -c -r throws the in-memory list away and re-reads the file, which is the only
# ordering that cannot drop an entry.
LIVE_SYNC = {
    "bash": "PROMPT_COMMAND='history -a; history -c; history -r'",
    "zsh": "setopt INC_APPEND_HISTORY SHARE_HISTORY",
}

RC_FILES = {
    "bash": ("~/.bashrc", "~/.bash_profile"),
    "zsh": ("~/.zshrc", "~/.zprofile"),
}


def shell_name() -> str:
    name = os.path.basename(user_shell())
    return "zsh" if "zsh" in name else "bash" if "bash" in name else ""


def live_sync_enabled() -> bool:
    """Has the user wired their shell to share history as it happens?

    PROMPT_COMMAND is not exported, so a child process cannot read it - the rc
    files are the only place to look from here.
    """
    sh = shell_name()
    marker = "history -r" if sh == "bash" else "SHARE_HISTORY"
    for name in RC_FILES.get(sh, ()):
        try:
            if marker in Path(name).expanduser().read_text():
                return True
        except OSError:
            continue
    return False


class ShellHistory(History):
    """prompt_toolkit's history, backed by the real shell history file.

    Loading is one-shot: prompt_toolkit calls `load_history_strings` once per
    session and keeps the list, so a large `.zsh_history` costs one read at
    startup rather than one per keystroke. `limit` caps that list because the
    inline suggester scans it on every keystroke, and a 100k-line history would
    be felt.
    """

    def __init__(self, limit: int = 5000):
        super().__init__()
        self._limit = limit

    def load_history_strings(self) -> Iterable[str]:
        return reversed(read(self._limit))     # prompt_toolkit wants newest first

    def store_string(self, string: str) -> None:
        # obiobi's own meta commands are not shell commands; keeping them out
        # means `history` in a normal terminal stays usable.
        if string.lstrip().startswith(("??", ":")):
            return
        append(string)
