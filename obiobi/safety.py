"""Screen generated shell commands before they can be run.

Two levels:
  BLOCKED - never offered, the suggestion is replaced by an explanation.
  RISKY   - offered, but shown with a warning and needs an explicit y/N.
"""
from __future__ import annotations

import re
from typing import NamedTuple

BLOCKED: list[tuple[str, str]] = [
    (r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+(/|/\*|~|\$HOME)\s*$", "recursive delete of / or $HOME"),
    (r":\s*\(\s*\)\s*\{.*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bmkfs(\.\w+)?\b", "formats a filesystem"),
    (r"\bdd\b[^|]*\bof=/dev/r?(sd|nvme|disk|hd)", "raw write to a block device"),
    (r"\b(tee|dd)\b[^|]*/dev/r?(sd|nvme|disk|hd)", "raw write to a block device"),
    (r">\s*/dev/r?(sd|nvme|disk|hd)\w*", "raw write to a block device"),
    (r"\bchmod\s+(-R\s+)?777\s+/\s*$", "world-writable root"),
    (r"\b(curl|wget)\b[^|;]*\|\s*(sudo\s+)?(ba|z|k)?sh", "pipes a download straight into a shell"),
    (r"\bhistory\s+-c\b.*\brm\b", "wipes history and deletes files"),
    (r"\b(shred|wipefs)\b.*\s/dev/", "destroys a device"),
]

RISKY: list[tuple[str, str]] = [
    (r"^\s*sudo\b|\ssudo\s", "runs with sudo"),
    (r"\brm\b", "deletes files"),
    (r"\b(kill|pkill|killall)\b", "kills processes"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "changes machine power state"),
    (r"\b(apt|apt-get|dnf|yum|pacman|brew|pip3?|npm|pipx)\s+(install|remove|uninstall|upgrade|erase|-S)\b",
     "installs or removes software"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|push\s+.*--force|push\s+.*-f\b)", "discards git work"),
    (r"\b(mv|cp)\b.*\s/(etc|usr|var|boot|System)\b", "writes into a system directory"),
    (r"\bchmod\b|\bchown\b", "changes permissions or ownership"),
    (r"\btruncate\b|\b>\s*/etc/", "overwrites a system file"),
    (r"\bdocker\s+(rm|rmi|system\s+prune|volume\s+rm)\b", "removes containers, images or volumes"),
    (r"\bcrontab\s+-r\b", "removes all cron jobs"),
    (r"\bdd\b[^|]*\bof=", "overwrites a file or device with dd"),
    (r"\bfind\b[^|]*\s-delete\b", "deletes matched files"),
]


class Verdict(NamedTuple):
    level: str  # "ok" | "risky" | "blocked"
    reason: str

    @property
    def blocked(self) -> bool:
        return self.level == "blocked"

    @property
    def risky(self) -> bool:
        return self.level == "risky"


def screen(command: str) -> Verdict:
    cmd = (command or "").strip()
    if not cmd:
        return Verdict("ok", "")
    for pattern, reason in BLOCKED:
        if re.search(pattern, cmd, re.IGNORECASE):
            return Verdict("blocked", reason)
    for pattern, reason in RISKY:
        if re.search(pattern, cmd, re.IGNORECASE):
            return Verdict("risky", reason)
    return Verdict("ok", "")
