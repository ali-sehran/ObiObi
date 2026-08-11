"""Turn a natural-language request into one shell command."""
from __future__ import annotations

import os
import re

from .backends import Backend
from .config import Config, os_label, user_shell

SYSTEM = """You convert a request into ONE shell command.

Environment: {os}, shell: {shell}, cwd: {cwd}

Rules:
- Reply with the command and nothing else. No prose, no markdown, no backticks.
- One line. Chain steps with && or ; if you must.
- Prefer read-only, non-interactive commands. Never invent flags.
- Prefer widely available tools over ones that may not be installed.
- If the request cannot be done with a shell command, reply exactly: # cannot
"""

# The list is what this machine has *on top of* the base OS - /usr/bin is
# filtered out of it. Saying "use only these" would therefore claim that `ls`
# and `df` do not exist, and the model answers "# cannot" to almost everything.
TOOLS_BLOCK = """
{tools}
The standard POSIX tools (ls, df, du, grep, find, awk, sed, ps, curl, tar) are
present as well. The list above is what this machine has in addition to them,
so prefer it over tools that may not be installed."""

FENCE = re.compile(r"^\s*```[\w-]*\s*|\s*```\s*$")
FENCE_BLOCK = re.compile(r"```[\w-]*[ \t]*\n(.*?)(?:```|\Z)", re.S)
LEADING_PROMPT = re.compile(r"^\s*(\$|#|>|%)\s+")


def _is_prose(line: str) -> bool:
    """'Sure!' or 'Here is the command:' are chatter; 'du -ah .' is not.

    The tell is sentence punctuation immediately after a letter - real commands
    that end in '.' or ';' have a space, slash or quote in front of it.
    """
    if len(line) < 2 or line[-1] not in ".!?:":
        return False
    return line[-2].isalpha()


def build_prompt(cfg: Config, question: str = "") -> str:
    prompt = SYSTEM.format(os=os_label(), shell=os.path.basename(user_shell()),
                           cwd=os.getcwd())
    if cfg.use_index:
        from .index import load, prompt_lines
        lines = prompt_lines(load(), cfg.index_limit)
        if lines:
            prompt += TOOLS_BLOCK.format(tools="\n".join(lines))
    return prompt


def strip_prefix(line: str, prefixes) -> str:
    """Remove the ??ask: trigger and return the bare question."""
    s = line.strip()
    for p in sorted(prefixes, key=len, reverse=True):
        if s.lower().startswith(p.lower()):
            return s[len(p):].lstrip(" :").strip()
    return s


# obiobi's own commands. They start with ?? too, so they have to be recognised
# before is_ask reads them as a question - both here and in the key bindings,
# or Enter fills the line instead of submitting it.
META = ("??docs", ":docs", "??history", "history")


def is_meta(line: str) -> bool:
    first = line.strip().lower().split(" ")[0]
    return first in META


def is_ask(line: str, prefixes) -> bool:
    if is_meta(line):
        return False
    s = line.lstrip().lower()
    return any(s.startswith(p.lower()) for p in prefixes)


def sanitize(raw: str) -> str:
    """Pull a single runnable command out of whatever the model produced."""
    if not raw:
        return ""
    text = raw.replace("\r", "")

    # If the model wrapped the command in a fence, that block is authoritative -
    # anything outside it is commentary.
    block = FENCE_BLOCK.search(text)
    if block and block.group(1).strip():
        text = block.group(1)

    comment = ""
    for ln in (FENCE.sub("", ln).strip() for ln in text.split("\n")):
        if not ln or ln == "```":
            continue
        if ln.startswith("#"):
            # an explicit refusal is normalised; other comments are a last resort
            if "cannot" in ln.lower():
                return "# cannot"
            comment = comment or ln
            continue
        ln = LEADING_PROMPT.sub("", ln).strip().strip("`")
        if not ln or _is_prose(ln):
            continue
        return ln
    return comment


CANNOT = "# cannot"


def translate(backend: Backend, cfg: Config, question: str) -> str:
    """question -> command string. Raises whatever the backend raises.

    Small models refuse at random: the same question that answers `ls` once
    comes back `# cannot` the next time. Measured on nemotron-3-nano, one plain
    retry took wrong refusals from 1-in-6 to 0-in-6 while still refusing the
    things that genuinely have no shell command. No nudge in the retry - asking
    the model to try harder only makes it invent commands for "tell me a joke".
    """
    if not question.strip():
        return ""
    question = question.strip()
    system = build_prompt(cfg, question)
    out = sanitize(backend.generate(system, question))
    if out == CANNOT and cfg.retry_refusals:
        out = sanitize(backend.generate(system, question)) or out
    return out
