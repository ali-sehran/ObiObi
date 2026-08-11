"""Paths, defaults and on-disk config for obiobi."""
from __future__ import annotations

import json
import os
import platform
import shutil
import ssl
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP = "obiobi"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP
MODELS_DIR = DATA_DIR / "models"
CONFIG_FILE = CONFIG_DIR / "config.json"
CREDENTIALS_FILE = CONFIG_DIR / "credentials"   # the api key, mode 0600
HISTORY_FILE = DATA_DIR / "history"

# Small, CPU-friendly instruct models. Anything GGUF works; these are just defaults.
DEFAULT_GGUF_REPO = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
DEFAULT_GGUF_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
DEFAULT_GGUF_URL = (
    f"https://huggingface.co/{DEFAULT_GGUF_REPO}/resolve/main/{DEFAULT_GGUF_FILE}"
)
DEFAULT_OLLAMA_MODEL = "qwen2.5:0.5b-instruct"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# Any OpenAI-compatible /chat/completions endpoint: OpenAI itself, a llama.cpp
# server, vLLM, LM Studio, Ollama's /v1 shim, OpenRouter, Groq, Together...
DEFAULT_API_BASE = ""            # empty = not configured
DEFAULT_API_MODEL = "gpt-4o-mini"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"

# Lines starting with any of these are treated as natural-language asks.
DEFAULT_PREFIXES = ("??ask:", "??ask", "??")


@dataclass
class Config:
    backend: str = "auto"  # auto | llama-cpp | ollama | openai | heuristic
    gguf_path: str = ""
    gguf_url: str = DEFAULT_GGUF_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    api_base: str = DEFAULT_API_BASE
    api_model: str = DEFAULT_API_MODEL
    api_key_env: str = DEFAULT_API_KEY_ENV
    api_timeout: int = 30
    prefixes: list[str] = field(default_factory=lambda: list(DEFAULT_PREFIXES))
    # Must be longer than a mid-sentence typing pause or every pause fires a
    # request: at 450 ms one typed question cost 8 requests, 7 of them for
    # half-typed fragments that were thrown away. At 800 ms it costs 1.
    debounce_ms: int = 800
    max_tokens: int = 96
    temperature: float = 0.1
    confirm_risky: bool = True
    dry_run: bool = False
    use_index: bool = True    # tell the model which tools this machine actually has
    index_limit: int = 500    # most names sent to the model per list
    history_limit: int = 5000  # newest shell-history lines kept for suggestions
    retry_refusals: bool = True  # small models refuse at random; ask once more
    login_shell: bool = True   # source your profile, so your functions exist

    # ---------- persistence ----------
    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_FILE.exists():
            try:
                raw = json.loads(CONFIG_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                raw = {}
            known = {f for f in cfg.__dataclass_fields__}
            for k, v in raw.items():
                if k in known:
                    setattr(cfg, k, v)
        for env, field_name in (
            ("OBIOBI_MODEL_URL", "gguf_url"),
            ("OBIOBI_GGUF_PATH", "gguf_path"),
            ("OBIOBI_BACKEND", "backend"),
            ("OBIOBI_API_BASE", "api_base"),
            ("OBIOBI_API_MODEL", "api_model"),
            ("OBIOBI_OLLAMA_MODEL", "ollama_model"),
        ):
            value = os.environ.get(env)
            if value:
                setattr(cfg, field_name, value)
        return cfg

    def resolve_api_key(self) -> str:
        """Environment first, then the credentials file. Never config.json."""
        return (os.environ.get("OBIOBI_API_KEY")
                or os.environ.get(self.api_key_env or "")
                or stored_api_key())

    def key_source(self) -> str:
        """Where the key in use came from, for `config` and `doctor` to show."""
        if os.environ.get("OBIOBI_API_KEY"):
            return "$OBIOBI_API_KEY"
        if self.api_key_env and os.environ.get(self.api_key_env):
            return f"${self.api_key_env}"
        if stored_api_key():
            return str(CREDENTIALS_FILE)
        return ""

    def save(self) -> Path:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2) + "\n")
        return CONFIG_FILE


# Settings that only matter for one backend. Showing `gguf_url` to somebody on
# an API endpoint is noise they never set and will never use.
BACKEND_ONLY = {
    "api": ("api_base", "api_model", "api_key_env", "api_timeout"),
    "ollama": ("ollama_model",),
    "llama-cpp": ("gguf_path", "gguf_url"),
    "heuristic": (),
}


def relevant_fields(cfg: "Config") -> list:
    """Field names worth showing for the backend actually in use."""
    import dataclasses

    every = [f.name for f in dataclasses.fields(cfg)]
    other = {name for backend, names in BACKEND_ONLY.items() for name in names}
    mine = set(BACKEND_ONLY.get(cfg.backend, ()))
    if cfg.backend == "auto":                 # auto can reach any of them
        mine = other
    return [n for n in every if n not in other or n in mine]


def stored_api_key() -> str:
    """The key saved by `obiobi config --set-key`, if there is one."""
    try:
        return CREDENTIALS_FILE.read_text().strip()
    except OSError:
        return ""


def store_api_key(key: str) -> Path:
    """Save the key for every future session, readable only by this user.

    It lives beside config.json rather than inside it, so config.json stays
    something you can commit, paste in a ticket or copy to another machine.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.touch(mode=0o600, exist_ok=True)
    CREDENTIALS_FILE.chmod(0o600)                 # tighten a pre-existing file
    CREDENTIALS_FILE.write_text(key.strip() + "\n")
    return CREDENTIALS_FILE


def forget_api_key() -> bool:
    try:
        CREDENTIALS_FILE.unlink()
        return True
    except OSError:
        return False


def mask(key: str) -> str:
    return f"{key[:7]}…{key[-4:]}" if len(key) > 14 else "set"


def user_shell() -> str:
    return os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"


def os_label() -> str:
    sysname = platform.system()
    if sysname == "Darwin":
        return f"macOS {platform.mac_ver()[0]}".strip()
    if sysname == "Linux":
        pretty = ""
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if line.startswith("PRETTY_NAME="):
                    pretty = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return pretty or "Linux"
    return sysname or "unknown"


def is_mac() -> bool:
    return platform.system() == "Darwin"


def ssl_context() -> ssl.SSLContext:
    """Verified TLS, even where the interpreter ships no CA bundle.

    python.org's macOS framework build has an empty cert store until someone
    runs `Install Certificates.command`, so every https call fails with
    CERTIFICATE_VERIFY_FAILED. Fall back to the system bundle curl uses.
    Verification stays on either way.
    """
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        for ca in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem",
                   "/etc/pki/tls/certs/ca-bundle.crt"):
            if ca and Path(ca).exists():
                ctx.load_verify_locations(ca)
                break
    return ctx
