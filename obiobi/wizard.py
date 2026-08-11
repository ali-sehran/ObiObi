"""`obiobi config --reset` - assisted setup.

Three ways to connect, and the answer to "which one" is usually obvious from
what is already running on the machine, so the wizard checks and recommends:

    local ollama    a daemon you already run; no key, nothing leaves the box
    local server    vLLM / LM Studio / llama-server, anything OpenAI-compatible
    hosted api      OpenRouter, OpenAI, Groq, Together

Local GGUF through llama-cpp-python is deliberately not offered. It compiles a
C extension, downloads a multi-gigabyte file and fails in interesting ways;
`ollama pull` does the same job. `obiobi install --backend llama-cpp` is still
there for anyone who wants it.

Every field arrives pre-filled with the recommended value: Enter takes it, Tab
opens the other choices, typing filters them.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config as cfg_mod
from .config import Config

BOLD = "\033[1m"
DIM = "\033[2m"
GREY = "\033[38;5;243m"
GREEN = "\033[32m"
RESET = "\033[0m"

# label -> (api_base, recommended model, key env var, needs a key)
HOSTED = {
    "openrouter": ("https://openrouter.ai/api/v1",
                   "nvidia/nemotron-3-nano-30b-a3b:free",
                   "OPENROUTER_API_KEY", True),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY", True),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile",
             "GROQ_API_KEY", True),
    "together": ("https://api.together.xyz/v1",
                 "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                 "TOGETHER_API_KEY", True),
}

LOCAL_SERVER = {
    "vllm": ("http://127.0.0.1:8000/v1", ""),
    "lm-studio": ("http://127.0.0.1:1234/v1", ""),
    "llama-server": ("http://127.0.0.1:8080/v1", ""),
    "ollama-openai-shim": (cfg_mod.OLLAMA_HOST + "/v1", "qwen2.5:0.5b-instruct"),
}


def _get(url: str, timeout: float = 1.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout,
                                    context=cfg_mod.ssl_context()) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def ollama_models() -> list:
    """Models already pulled, so the wizard can offer real choices."""
    data = _get(cfg_mod.OLLAMA_HOST + "/api/tags")
    return sorted(m.get("name", "") for m in (data or {}).get("models", []) if m.get("name"))


def local_server_models(base: str) -> list:
    data = _get(base.rstrip("/") + "/models", timeout=1.5)
    return sorted(m.get("id", "") for m in (data or {}).get("data", []) if m.get("id"))


def ask(label: str, default: str = "", options=None, secret: bool = False) -> str:
    """One question, shown as `label [recommended]:` over an empty line.

    Enter alone takes the recommendation. Tab fills it in so it can be edited,
    and offers the alternatives after it. Typing replaces it outright.

    The line starts empty on purpose: pre-filling it puts the cursor after the
    default, so anyone who types their own answer gets it welded onto the end -
    `hosted-api` + `local-server` = `hosted-apilocal-server`.
    """
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import FormattedText

    # recommendation first, so Tab lands on it before the alternatives
    choices = ([default] if default else []) + \
              [o for o in (options or []) if o != default]
    message = FormattedText([("", label),
                             ("class:dim", f" [{default}]" if default else ""),
                             ("", ": ")])
    answer = pt_prompt(
        message,
        completer=WordCompleter(choices, ignore_case=True) if choices else None,
        # menu on Tab only: complete_while_typing reserves a block of blank
        # rows under every question, which looks broken
        complete_while_typing=False,
        reserve_space_for_menu=0,
        is_password=secret,
    )
    return answer.strip() or default


def choose(label: str, options: list, default: str) -> str:
    """A selector: Enter for the recommendation, Tab to see the rest."""
    while True:
        picked = ask(label, default=default, options=options)
        if picked in options:
            return picked
        print(f"{DIM}  pick one of: {', '.join(options)}{RESET}")


def run(cfg: Config) -> int:
    print(f"{BOLD}obiobi setup{RESET} {DIM}- Enter takes the suggested value, "
          f"Tab shows the alternatives, Ctrl-C stops{RESET}\n")

    pulled = ollama_models()
    kinds = ["ollama", "local-server", "hosted-api"]
    hint = {
        "ollama": (f"{GREEN}found, {len(pulled)} model(s) pulled{RESET}" if pulled
                   else f"{DIM}not detected{RESET}"),
        "local-server": f"{DIM}vLLM / LM Studio / llama-server{RESET}",
        "hosted-api": f"{DIM}OpenRouter, OpenAI, Groq, Together{RESET}",
    }
    for k in kinds:
        print(f"  {k:<14} {hint[k]}")
    print()

    try:
        kind = choose("connect via", kinds, "ollama" if pulled else "hosted-api")
        if kind == "ollama":
            if not pulled:
                print(f"{DIM}  no ollama models found at {cfg_mod.OLLAMA_HOST}; "
                      f"run `ollama pull qwen2.5:0.5b-instruct` first{RESET}")
            cfg.backend = "ollama"
            cfg.ollama_model = ask("model", default=(pulled[0] if pulled
                                                     else cfg.ollama_model),
                                   options=pulled)
        elif kind == "local-server":
            flavour = choose("server", sorted(LOCAL_SERVER), "vllm")
            base, model = LOCAL_SERVER[flavour]
            cfg.backend = "api"
            cfg.api_base = ask("api_base", default=base)
            served = local_server_models(cfg.api_base)
            if served:
                print(f"{GREY}  serving: {', '.join(served[:6])}{RESET}")
            cfg.api_model = ask("model", default=(served[0] if served else model),
                                options=served)
            cfg.api_key_env = "OBIOBI_API_KEY"      # localhost needs no key
        else:
            provider = choose("provider", sorted(HOSTED), "openrouter")
            base, model, key_env, needs_key = HOSTED[provider]
            cfg.backend = "api"
            cfg.api_base = ask("api_base", default=base)
            cfg.api_model = ask("model", default=model)
            cfg.api_key_env = ask("key comes from env var", default=key_env)
            if needs_key and not cfg.resolve_api_key():
                key = ask(f"paste your {provider} key (not echoed, or Enter to skip)",
                          secret=True)
                if key:
                    path = cfg_mod.store_api_key(key)
                    print(f"{GREY}  saved to {path} (mode 600){RESET}")
    except (EOFError, KeyboardInterrupt):
        print(f"\n{DIM}cancelled, nothing changed{RESET}")
        return 130

    path = cfg.save()
    print(f"\n{GREEN}✓{RESET} saved {path}")

    from . import index
    if not index.load()["commands"]:
        tools = index.build()
        print(f"{GREEN}✓{RESET} indexed {index.summary(tools)}")
        index.save(tools)

    from .backends import BackendError, build_backend
    try:
        print(f"{GREEN}✓{RESET} backend {build_backend(cfg).label} is reachable")
    except BackendError as exc:
        print(f"{DIM}! {exc}{RESET}")
        return 1
    print(f"\nstart it with: {BOLD}obiobi{RESET}")
    return 0
