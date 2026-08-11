"""Install the pieces needed to run a small model locally."""
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import config as cfg_mod
from .config import Config

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def _say(msg: str) -> None:
    print(f"{BOLD}::{RESET} {msg}")


def pip_install(*packages: str) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *packages]
    _say(" ".join(cmd))
    if subprocess.run(cmd).returncode == 0:
        return True
    _say("retrying with --break-system-packages")
    return subprocess.run(cmd + ["--break-system-packages"]).returncode == 0


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    _say(f"downloading {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "obiobi/1.0"})
        with urllib.request.urlopen(req, timeout=30,
                                    context=cfg_mod.ssl_context()) as r, tmp.open("wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    bar = "#" * (pct // 3)
                    print(f"\r  {pct:3d}% [{bar:<33}] {done>>20}/{total>>20} MiB",
                          end="", flush=True)
                else:
                    print(f"\r  {done>>20} MiB", end="", flush=True)
        print()
        tmp.replace(dest)
        return True
    except (urllib.error.URLError, OSError) as exc:
        print()
        print(f"{RED}download failed: {exc}{RESET}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return False


def install_ollama_model(cfg: Config) -> bool:
    if not shutil.which("ollama"):
        print(f"{RED}ollama is not installed.{RESET}")
        print("  macOS/Linux: curl -fsSL https://ollama.com/install.sh | sh")
        return False
    _say(f"ollama pull {cfg.ollama_model}")
    return subprocess.run(["ollama", "pull", cfg.ollama_model]).returncode == 0


def install_llama_cpp(cfg: Config) -> bool:
    _say("installing llama-cpp-python (this compiles; it can take a few minutes)")
    if not pip_install("llama-cpp-python"):
        print(f"{RED}could not install llama-cpp-python.{RESET} "
              "A C compiler and cmake are required.")
        return False
    target = cfg_mod.MODELS_DIR / cfg.gguf_url.rsplit("/", 1)[-1]
    if target.exists():
        _say(f"model already present: {target}")
    elif not download(cfg.gguf_url, target):
        print(f"{DIM}Tip: download any .gguf into {cfg_mod.MODELS_DIR} manually, "
              f"or set OBIOBI_MODEL_URL.{RESET}")
        return False
    cfg.gguf_path = str(target)
    return True


def build_index() -> None:
    """Learn what this machine has, so suggestions stay inside that set."""
    from . import index
    _say("indexing installed commands and packages")
    tools = index.build()
    index.save(tools)
    print(f"{GREEN}✓{RESET} indexed {index.summary(tools)}")


def install(cfg: Config, backend: str) -> int:
    cfg_mod.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if not pip_install("prompt_toolkit"):
        return 1
    build_index()

    ok = True
    if backend == "api":
        cfg.backend = "api"
        if not cfg.api_base:
            print(f"{RED}set an endpoint first:{RESET}\n"
                  "  obiobi config --set api_base=https://api.openai.com/v1 "
                  "--set api_model=gpt-4o-mini")
            print(f"  export {cfg.api_key_env}=sk-...")
            return 1
        print(f"{GREEN}✓{RESET} using {cfg.api_base} ({cfg.api_model})")
        cfg.save()
        return 0
    if backend in ("auto", "ollama") and shutil.which("ollama"):
        ok = install_ollama_model(cfg)
        if ok:
            cfg.backend = "ollama"
    elif backend in ("auto", "llama-cpp"):
        ok = install_llama_cpp(cfg)
        if ok:
            cfg.backend = "llama-cpp"
    elif backend == "heuristic":
        cfg.backend = "heuristic"

    if not ok:
        cfg.backend = "heuristic"
        print(f"{DIM}falling back to the rule-based backend; "
              f"re-run `obiobi install` any time.{RESET}")

    path = cfg.save()
    print(f"{GREEN}✓{RESET} backend = {cfg.backend}   config = {path}")
    print(f"  start it with: {BOLD}obiobi{RESET}")
    return 0
