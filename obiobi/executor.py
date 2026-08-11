"""Run accepted commands in the user's own shell."""
from __future__ import annotations

import os
import subprocess
import sys

from .config import Config, user_shell
from .safety import screen

DIM = "\033[2m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def shell_argv(command: str, cfg: Config) -> list:
    """How to hand `command` to the user's shell.

    A plain `bash -c` is neither a login shell nor interactive, so it reads no
    profile at all: functions and aliases you defined in ~/.bash_profile simply
    do not exist, and the command dies with "not found". `-l` sources the
    profile and they work.

    ponytail: the profile is re-sourced per command - measured at ~130 ms here
    against ~2 ms without, because that profile loads nvm. Worth it to make a
    shell behave like your shell; `login_shell=false` buys the 130 ms back.
    """
    shell = user_shell()
    if not cfg.login_shell:
        return [shell, "-c", command]
    if "bash" in os.path.basename(shell):
        # A non-interactive bash ignores aliases even once they are defined.
        command = f"shopt -s expand_aliases; {command}"
    return [shell, "-lc", command]


def confirm(question: str) -> bool:
    try:
        answer = input(f"{YELLOW}{question} [y/N] {RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def run(command: str, cfg: Config) -> int:
    command = command.strip()
    if not command or command.startswith("#"):
        return 0

    verdict = screen(command)
    if verdict.blocked:
        print(f"{RED}refused ({verdict.reason}): {command}{RESET}", file=sys.stderr)
        return 126
    if verdict.risky and cfg.confirm_risky and not cfg.dry_run:
        print(f"{YELLOW}⚠ {verdict.reason}{RESET}  {command}")
        if not confirm("run it?"):
            print(f"{DIM}skipped{RESET}")
            return 130

    if cfg.dry_run:
        print(f"{DIM}dry-run:{RESET} {command}")
        return 0

    # `cd` has to be handled in-process or it would be lost with the subprocess.
    if command.startswith("cd ") or command == "cd":
        target = os.path.expanduser(command[2:].strip() or "~")
        try:
            os.chdir(target)
        except OSError as exc:
            print(f"{RED}{exc}{RESET}", file=sys.stderr)
            return 1
        return 0

    try:
        return subprocess.run(shell_argv(command, cfg)).returncode
    except KeyboardInterrupt:
        print()
        return 130
    except OSError as exc:
        print(f"{RED}{exc}{RESET}", file=sys.stderr)
        return 1
