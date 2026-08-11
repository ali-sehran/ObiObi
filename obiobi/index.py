"""What is installed on this machine, as a plain list of names.

Names only. Nothing here executes an unknown binary to find out what it does -
running a stranger just to read its banner is how you end up with a keychain
prompt from `docker-credential-osxkeychain`. A name is enough: the model
already knows what `docker` is, it only needs to know you have it.

Three sources, all cheap and all read-only:

    $PATH scan             every executable name, from a directory listing
    importlib.metadata     installed python distributions
    npm ls -g / brew list  packages from the managers you already use

`/usr/bin` and friends are filtered out of the list sent to the model. Every
machine has `awk`; what matters is that this one has `docker` and `kubectl`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import DATA_DIR

INDEX_FILE = DATA_DIR / "tools.json"

# The base OS. Listing these tells the model nothing it does not assume.
SYSTEM_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/libexec",
               "/System/", "/var/run/com.apple", "/Library/Apple")

# Version-suffixed duplicates, dotfiles, and per-tool shims: noise.
SKIP = re.compile(r"^(\[|\.|_|[0-9])|(-config|-shim)$|\d+\.\d+$")


def _is_system(directory: str) -> bool:
    return any(directory == d.rstrip("/") or directory.startswith(d)
               for d in SYSTEM_DIRS)


def path_executables(user_only: bool = True) -> set:
    """Executable names on $PATH. `user_only` drops the base OS directories."""
    found = set()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or (user_only and _is_system(d)):
            continue
        try:
            with os.scandir(d) as it:
                for e in it:
                    if not SKIP.search(e.name) and os.access(e.path, os.X_OK):
                        found.add(e.name)
        except OSError:      # missing or unreadable PATH entry - normal
            continue
    return found


def _run(cmd: list, timeout: int) -> str:
    """Run one known package manager. Never an arbitrary binary."""
    if not shutil.which(cmd[0]):
        return ""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, stdin=subprocess.DEVNULL,
                             errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout


_PY_DUMP = ("import json;from importlib.metadata import distributions;"
            "print(json.dumps(sorted({d.metadata['Name'] for d in distributions()"
            " if d.metadata['Name']})))")


def python_packages() -> set:
    """Whatever `import` can see, asked of the user's python - not obiobi's venv.

    ponytail: only the first python3 on $PATH, which is the one a suggested
    `python3 ...` would actually run. Machines with pyenv or several venvs get
    one of them indexed; loop over the others if that turns out to matter.
    """
    for exe in ("python3", "python"):
        raw = _run([exe, "-c", _PY_DUMP], 20)
        try:
            return set(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return set()


def npm_packages() -> set:
    try:
        return set(json.loads(_run(["npm", "ls", "-g", "--depth=0", "--json"],
                                   30)).get("dependencies") or {})
    except (json.JSONDecodeError, AttributeError):
        return set()


def brew_packages() -> set:
    return set(_run(["brew", "list", "--formula"], 30).split())


def build() -> dict:
    """{"commands": [...], "packages": [...]} - names, sorted, no duplicates."""
    commands = path_executables()
    packages = set()
    for source in (python_packages, npm_packages, brew_packages):
        packages |= source()
    return {"commands": sorted(commands),
            "packages": sorted(packages - commands)}


def save(index: dict) -> Path:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, indent=0, sort_keys=True))
    return INDEX_FILE


def load() -> dict:
    try:
        data = json.loads(INDEX_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"commands": [], "packages": []}
    if isinstance(data, dict) and "commands" in data:
        return data
    return {"commands": sorted(data) if data else [], "packages": []}


def summary(index: dict) -> str:
    return (f"{len(index.get('commands', []))} commands, "
            f"{len(index.get('packages', []))} packages")


def prompt_lines(index: dict, limit: int = 500) -> list:
    """The two lines handed to the model, truncated honestly if huge."""
    out = []
    for label, names in (("Commands", index.get("commands") or []),
                         ("Packages", index.get("packages") or [])):
        if not names:
            continue
        shown, extra = names[:limit], max(0, len(names) - limit)
        tail = f", and {extra} more" if extra else ""
        out.append(f"{label} installed here: {', '.join(shown)}{tail}")
    return out
