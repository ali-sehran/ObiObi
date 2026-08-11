"""obiobi - a shell prompt with a small local language model behind ??ask:"""
from __future__ import annotations

import argparse
import shutil
import sys

from . import config as cfg_mod
from .backends import BackendError, build_backend
from .config import Config, os_label, user_shell
from .nl2cmd import is_ask, is_meta, strip_prefix, translate

BOLD = "\033[1m"
DIM = "\033[2m"
GREY = "\033[38;5;243m"
RED = "\033[31m"
RESET = "\033[0m"

BANNER = f"""{BOLD}obiobi{RESET} {DIM}- run a command, or ask for one in plain words:{RESET}
  {DIM}??ask:{RESET} check all installed modules and packages
  {GREY}the grey line under your input is the suggestion{RESET}
  {DIM}[Tab] accept the grey text (a suggestion, or your last matching command){RESET}
  {DIM}[Enter] run   [Ctrl-G] dismiss   [Ctrl-D] exit   ??docs   history   :help{RESET}"""


def cmd_run(cfg: Config, args) -> int:
    from . import history as hist
    from .executor import run as run_cmd
    from .ui import build_session

    try:
        backend = build_backend(cfg)
    except BackendError as exc:
        print(f"{RED}{exc}{RESET}\nRun `obiobi install` first, or "
              f"`obiobi --backend heuristic` to use the rule-based fallback.",
              file=sys.stderr)
        return 1

    session, state = build_session(cfg, backend)
    if not args.quiet:
        print(BANNER)
        for note in backend.fallback_from:
            print(f"  {DIM}skipped {note}{RESET}")
        remote = getattr(backend, "remote_host", "")
        if remote:
            print(f"  {GREY}questions are sent to {remote} "
                  f"(model {backend.detail}){RESET}")

    while True:
        try:
            text = session.prompt()
        except KeyboardInterrupt:
            state.clear()
            continue
        except EOFError:
            print("bye")
            return 0

        text = text.strip()
        state.clear()
        if not text:
            continue
        if text in (":q", ":quit", "exit", "quit"):
            return 0
        if text in (":help", "?"):
            print(BANNER)
            continue
        if text == ":backend":
            print(backend.label)
            continue
        if text == ":dry":
            cfg.dry_run = not cfg.dry_run
            print(f"dry-run {'on' if cfg.dry_run else 'off'}")
            continue
        if text.lower() in ("??docs", ":docs"):
            if not state.log:
                print(f"{DIM}nothing asked yet this session{RESET}")
            else:
                print(f"{GREY}wrote {hist.write_docs(state.log)}{RESET}")
            continue
        if is_meta(text):        # history [n]
            parts = text.split()
            n = int(parts[1]) if parts[1:2] and parts[1].isdigit() else 25
            # Number by real position in the history file, so these line up
            # with what `history` prints in your own terminal instead of
            # restarting at 1 every time.
            rows = hist.numbered(n)
            for i, cmd in rows:
                print(f"{DIM}{i:5d}{RESET}  {cmd}")
            if rows:
                print(f"{DIM}  entries in {hist.history_file().name}; your shell "
                      f"numbers these with its own per-session counter{RESET}")
            continue
        if is_ask(text, cfg.prefixes):
            # Enter pressed before a suggestion existed - answer synchronously.
            question = strip_prefix(text, cfg.prefixes)
            try:
                command = translate(backend, cfg, question)
            except Exception as exc:  # noqa: BLE001
                print(f"{RED}{exc}{RESET}", file=sys.stderr)
                continue
            if command:
                print(f"{GREY}  {command}{RESET}")
            continue
        run_cmd(text, cfg)


def cmd_ask(cfg: Config, args) -> int:
    from .executor import run as run_cmd

    try:
        backend = build_backend(cfg)
    except BackendError as exc:
        print(f"{RED}{exc}{RESET}", file=sys.stderr)
        return 1
    question = " ".join(args.question)
    for note in backend.fallback_from:
        print(f"{DIM}skipped {note}{RESET}", file=sys.stderr)
    if is_ask(question, cfg.prefixes):
        question = strip_prefix(question, cfg.prefixes)
    try:
        command = translate(backend, cfg, question)
    except Exception as exc:  # noqa: BLE001 - network, auth, model, all the same here
        print(f"{RED}{backend.label}: {exc}{RESET}", file=sys.stderr)
        return 1
    # "# cannot" is the model declining, not a command - it belongs on stderr so
    # `obiobi ask ... | sh` and friends see an empty stdout and a non-zero rc.
    if not command or command.lstrip().startswith("#"):
        print(command.lstrip("# ") or "no suggestion", file=sys.stderr)
        return 1
    if args.run:
        return run_cmd(command, cfg)

    # One-shot mode prints rather than runs, but stdout may be piped straight
    # into a shell, so a blocked command must not reach it.
    from .safety import screen
    verdict = screen(command)
    if verdict.blocked:
        print(f"{RED}refused: {verdict.reason}{RESET}", file=sys.stderr)
        return 1
    if verdict.risky:
        print(f"{DIM}⚠ {verdict.reason}{RESET}", file=sys.stderr)
    print(command)
    return 0


def cmd_doctor(cfg: Config, args) -> int:
    print(f"{BOLD}os{RESET}        {os_label()}")
    print(f"{BOLD}shell{RESET}     {user_shell()}")
    print(f"{BOLD}python{RESET}    {sys.version.split()[0]} ({sys.executable})")
    print(f"{BOLD}config{RESET}    {cfg_mod.CONFIG_FILE} "
          f"({'found' if cfg_mod.CONFIG_FILE.exists() else 'not created yet'})")
    print(f"{BOLD}models{RESET}    {cfg_mod.MODELS_DIR}")
    for p in sorted(cfg_mod.MODELS_DIR.glob('*.gguf')) if cfg_mod.MODELS_DIR.exists() else []:
        print(f"            - {p.name} ({p.stat().st_size >> 20} MiB)")
    for mod in ("prompt_toolkit", "llama_cpp"):
        try:
            __import__(mod)
            print(f"{BOLD}{mod:<9}{RESET} ok")
        except ImportError:
            print(f"{BOLD}{mod:<9}{RESET} {DIM}missing{RESET}")
    print(f"{BOLD}ollama{RESET}    {shutil.which('ollama') or DIM + 'not found' + RESET}")
    from . import index
    tools = index.load()
    print(f"{BOLD}index{RESET}     "
          f"{index.summary(tools) if tools['commands'] else DIM + 'not built (run: obiobi index)' + RESET}")
    from . import history as hist
    sync = (f"{len(hist.read())} entries, live-shared with your terminal"
            if hist.live_sync_enabled() else
            f"{DIM}{len(hist.read())} entries; your terminal only re-reads it on "
            f"restart. To share live, add to your rc:{RESET}\n"
            f"            {hist.LIVE_SYNC.get(hist.shell_name(), '')}")
    print(f"{BOLD}history{RESET}   {hist.history_file()}")
    print(f"{BOLD}          {RESET}{sync}")
    print(f"{BOLD}endpoint{RESET}  {cfg.api_base or DIM + 'not configured' + RESET}"
          f"{'  model ' + cfg.api_model if cfg.api_base else ''}")
    key = cfg.resolve_api_key()
    shown = f"{cfg_mod.mask(key)}  from {cfg.key_source()}" if key else f"{DIM}not set{RESET}"
    print(f"{BOLD}api key{RESET}   {shown}")
    try:
        print(f"{BOLD}backend{RESET}   {build_backend(cfg).label}")
    except BackendError as exc:
        print(f"{BOLD}backend{RESET}   {RED}{exc}{RESET}")
    return 0


def cmd_config(cfg: Config, args) -> int:
    import dataclasses

    if args.reset:
        from .wizard import run
        return run(cfg)

    fields = {f.name: f.type for f in dataclasses.fields(cfg)}
    for pair in args.set:
        if "=" not in pair:
            print(f"{RED}expected KEY=VALUE, got {pair!r}{RESET}", file=sys.stderr)
            return 2
        key, value = pair.split("=", 1)
        key = key.strip()
        if key not in fields:
            print(f"{RED}unknown setting {key!r}{RESET}  known: "
                  f"{', '.join(sorted(fields))}", file=sys.stderr)
            return 2
        current = getattr(cfg, key)
        if isinstance(current, bool):
            value = value.strip().lower() in ("1", "true", "yes", "on")
        elif isinstance(current, int):
            value = int(value)
        elif isinstance(current, list):
            value = [v for v in (p.strip() for p in value.split(",")) if v]
        setattr(cfg, key, value)
    if args.set:
        print(f"saved {cfg.save()}")
        # `pip install obiobi && obiobi config --set ...` should be the whole
        # setup, so the first config build also learns the machine.
        from . import index
        if not index.load()["commands"]:
            tools = index.build()
            print(f"{DIM}indexed {index.summary(tools)} -> {index.save(tools)}{RESET}")

    if args.forget_key:
        print("removed the saved key" if cfg_mod.forget_api_key()
              else "no saved key")
    if args.set_key:
        import getpass
        try:
            key = (sys.stdin.readline() if not sys.stdin.isatty()
                   else getpass.getpass(f"{BOLD}API key{RESET} (not echoed): "))
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if not key.strip():
            print(f"{RED}nothing entered{RESET}", file=sys.stderr)
            return 2
        path = cfg_mod.store_api_key(key)
        print(f"{GREY}saved to {path} (mode 600){RESET}")

    key, source = cfg.resolve_api_key(), cfg.key_source()
    live = cfg_mod.relevant_fields(cfg)
    unused = [n for n in sorted(fields) if n not in live]

    print(f"{BOLD}settings{RESET}  {cfg_mod.CONFIG_FILE}")
    for name in sorted(live):
        value = getattr(cfg, name)
        shown = value if value != "" else f"{DIM}not set{RESET}"
        print(f"  {name:<14} {shown}")
    if args.all:
        # Still listed, but marked - these belong to a backend you are not on.
        for name in unused:
            print(f"  {DIM}{name:<14} {getattr(cfg, name)}   "
                  f"(unused with backend={cfg.backend}){RESET}")
    elif unused:
        print(f"{DIM}  ({len(unused)} more for other backends: "
              f"obiobi config --all){RESET}")

    print(f"\n{BOLD}api key{RESET}   "
          f"{cfg_mod.mask(key) + '  from ' + source if key else RED + 'not set' + RESET}")
    if not key:
        print(f"{DIM}  save one for every session:  obiobi config --set-key{RESET}")
        print(f"{DIM}  or export ${cfg.api_key_env} in your shell rc{RESET}")
    print(f"{DIM}  the key is never written to config.json, so that file is "
          f"safe to share{RESET}")
    print(f"{DIM}  reconnect to a different model or provider: "
          f"{RESET}{DIM}obiobi config --reset{RESET}")
    if not cfg.api_base and cfg.backend in ("api", "auto"):
        print(f"\n{DIM}no endpoint yet. For OpenRouter's free tier:{RESET}\n"
              f"  obiobi config --set backend=api "
              f"--set api_base=https://openrouter.ai/api/v1 \\\n"
              f"                --set api_model=nvidia/nemotron-3-nano-30b-a3b:free "
              f"--set api_key_env=OPENROUTER_API_KEY")
    return 0


def cmd_install(cfg: Config, args) -> int:
    from .installer import install
    if getattr(args, "gguf_url", None):
        cfg.gguf_url = args.gguf_url
    if getattr(args, "ollama_model", None):
        cfg.ollama_model = args.ollama_model
    return install(cfg, args.backend or "auto")


def cmd_index(cfg: Config, args) -> int:
    from . import index
    tools = index.build()
    print(f"{BOLD}✓{RESET} indexed {index.summary(tools)} -> {index.save(tools)}")
    if args.show:
        for line in index.prompt_lines(tools, cfg.index_limit):
            print(f"  {GREY}{line}{RESET}")
    return 0


def main(argv: list[str] | None = None) -> int:
    cfg = Config.load()

    backends = ["auto", "llama-cpp", "ollama", "api", "heuristic"]

    parser = argparse.ArgumentParser(prog="obiobi", description=__doc__)
    parser.add_argument("--backend", choices=backends + ["openai"],
                        help="override the inference backend ('api' = any "
                             "OpenAI-compatible endpoint)")
    parser.add_argument("--dry-run", action="store_true", help="print commands instead of running")
    parser.add_argument("-q", "--quiet", action="store_true", help="no banner")
    sub = parser.add_subparsers(dest="cmd")

    p_install = sub.add_parser("install", help="fetch a small model and set things up")
    p_install.add_argument("--backend", choices=backends)
    p_install.add_argument("--gguf-url", help="download this .gguf instead of the default")
    p_install.add_argument("--ollama-model", help="pull this ollama model instead")
    p_install.set_defaults(func=cmd_install)

    p_cfg = sub.add_parser("config", help="show or change settings")
    p_cfg.add_argument("--set", action="append", metavar="KEY=VALUE", default=[],
                       help="e.g. --set api_base=https://api.openai.com/v1 "
                            "--set api_model=gpt-4o-mini")
    p_cfg.add_argument("--set-key", action="store_true",
                       help="prompt for an API key and save it for every session")
    p_cfg.add_argument("--forget-key", action="store_true",
                       help="delete the saved API key")
    p_cfg.add_argument("--all", action="store_true",
                       help="also show settings belonging to other backends")
    p_cfg.add_argument("--reset", action="store_true",
                       help="assisted setup: pick a local or hosted model")
    p_cfg.set_defaults(func=cmd_config)

    p_ask = sub.add_parser("ask", help="one-shot: print the command for a question")
    p_ask.add_argument("question", nargs="+")
    p_ask.add_argument("--run", action="store_true", help="execute it as well")
    p_ask.set_defaults(func=cmd_ask)

    p_index = sub.add_parser("index", help="re-scan installed commands and man pages")
    p_index.add_argument("--show", action="store_true",
                         help="print the list exactly as the model receives it")
    p_index.set_defaults(func=cmd_index)

    sub.add_parser("doctor", help="show what is installed").set_defaults(func=cmd_doctor)
    sub.add_parser("run", help="start the interactive shell (default)").set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    if getattr(args, "backend", None):
        cfg.backend = args.backend
    if args.dry_run:
        cfg.dry_run = True

    func = getattr(args, "func", cmd_run)
    try:
        return func(cfg, args) or 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
