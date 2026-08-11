"""Pluggable text-generation backends.

Every backend implements `generate(system, user) -> str`.
Resolution order for `backend = "auto"`: llama-cpp (local gguf) -> ollama -> heuristic.
The heuristic backend needs no model at all, so the tool is usable the second
it is installed and degrades gracefully on a machine with no model present.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from . import config as cfg_mod
from .config import Config


class BackendError(RuntimeError):
    pass


class Backend:
    name = "base"
    detail = ""
    fallback_from: list = []   # backends that were tried and skipped before this one

    def generate(self, system: str, user: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def label(self) -> str:
        return f"{self.name}{':' + self.detail if self.detail else ''}"


# --------------------------------------------------------------------------- #
# local gguf via llama-cpp-python
# --------------------------------------------------------------------------- #
class LlamaCppBackend(Backend):
    name = "llama.cpp"

    def __init__(self, cfg: Config):
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise BackendError("llama-cpp-python is not installed") from exc

        path = Path(cfg.gguf_path) if cfg.gguf_path else _find_gguf()
        if not path or not path.exists():
            raise BackendError("no .gguf model found (run: obiobi install)")

        self.detail = path.stem
        self._cfg = cfg
        self._llm = Llama(
            model_path=str(path),
            n_ctx=2048,
            n_threads=None,     # llama.cpp picks a sensible default
            verbose=False,
        )

    def generate(self, system: str, user: str) -> str:
        out = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=self._cfg.max_tokens,
            temperature=self._cfg.temperature,
            stop=["\n\n", "```"],
        )
        return out["choices"][0]["message"]["content"] or ""


def _find_gguf() -> Optional[Path]:
    if not cfg_mod.MODELS_DIR.exists():
        return None
    files = sorted(cfg_mod.MODELS_DIR.glob("*.gguf"), key=lambda p: p.stat().st_size)
    return files[0] if files else None  # smallest = fastest to answer


# --------------------------------------------------------------------------- #
# ollama daemon
# --------------------------------------------------------------------------- #
class OllamaBackend(Backend):
    name = "ollama"

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._host = cfg_mod.OLLAMA_HOST.rstrip("/")
        tags = self._get("/api/tags")
        names = {m.get("name", "") for m in tags.get("models", [])}
        want = cfg.ollama_model
        if want not in names:
            base = want.split(":")[0]
            match = next((n for n in sorted(names) if n.split(":")[0] == base), None)
            if match:
                want = match
            elif names:
                raise BackendError(f"ollama is running but '{cfg.ollama_model}' is not pulled")
            else:
                raise BackendError("ollama is running but has no models pulled")
        self.model = want
        self.detail = want

    def _get(self, path: str) -> dict:
        try:
            with urllib.request.urlopen(self._host + path, timeout=1.5,
                                        context=cfg_mod.ssl_context()) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise BackendError(f"ollama not reachable at {self._host}") from exc

    def generate(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "temperature": self._cfg.temperature,
                "num_predict": self._cfg.max_tokens,
            },
        }).encode()
        req = urllib.request.Request(
            self._host + "/api/chat", data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60,
                                        context=cfg_mod.ssl_context()) as r:
                data = json.loads(r.read().decode())
        except (urllib.error.URLError, OSError) as exc:
            raise BackendError(f"ollama request failed: {exc}") from exc
        return (data.get("message") or {}).get("content", "")


# --------------------------------------------------------------------------- #
# any OpenAI-compatible /chat/completions endpoint
# --------------------------------------------------------------------------- #
# Shared free pools run out constantly and recover in seconds. Anything that
# reads like "come back later" is worth one more try before bothering the user.
TRANSIENT = re.compile(
    r"rate.?limit|resource.?exhausted|exhausted|temporarily|overloaded|"
    r"too many requests|try again|capacity|unavailable|HTTP 429|HTTP 50[023]", re.I)

RETRY_PAUSE = 1.0     # ponytail: flat pause, not a backoff ladder - one retry


def _error_message(data) -> str:
    """The error text out of a body that came back with HTTP 200."""
    err = data.get("error") if isinstance(data, dict) else None
    if not err:
        return ""
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err)


def short_error(message: str) -> str:
    """One readable line, not a truncated python dict.

    The raw thing looks like `Upstream error from Nvidia: ResourceExhausted:
    Worker local total request limit reached...`, which tells a user nothing
    they can act on. What they need to know is: it is busy, not broken.
    """
    if TRANSIENT.search(message):
        return "the model is busy right now (free tier is shared) - press Tab to retry"
    message = " ".join(message.split())
    return message if len(message) <= 110 else message[:107] + "…"


class OpenAIBackend(Backend):
    """OpenAI, or anything speaking its chat-completions dialect.

    Works with api.openai.com, a `llama-server` you run yourself, vLLM,
    LM Studio, Ollama's /v1 shim, OpenRouter, Groq, Together, and so on.
    The key is read from the environment - it is never written to disk.
    """

    name = "api"

    def __init__(self, cfg: Config):
        base = (cfg.api_base or "").strip().rstrip("/")
        if not base:
            raise BackendError("no api_base set (obiobi config --set api_base=...)")
        if not base.startswith(("http://", "https://")):
            raise BackendError(f"api_base must start with http:// or https:// ({base})")

        self._url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        self._key = cfg.resolve_api_key()
        self._local = any(h in base for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"))
        if not self._key and not self._local:
            raise BackendError(
                f"no API key: export {cfg.api_key_env} (or OBIOBI_API_KEY)")

        self._cfg = cfg
        self.detail = cfg.api_model
        host = base.split("//", 1)[-1].split("/", 1)[0]
        self.remote_host = "" if self._local else host

    def generate(self, system: str, user: str) -> str:
        body = {
            "model": self._cfg.api_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._cfg.temperature,
            "max_tokens": self._cfg.max_tokens,
        }
        if "openrouter.ai" in self._url:
            # ponytail: OpenRouter dialect only - hybrid models otherwise spend the
            # whole max_tokens budget thinking and return content: null.
            body["reasoning"] = {"enabled": False}
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"

        # A busy shared pool answers HTTP 200 with an error *body*, so the
        # HTTPError branch never sees it. Retry once, then say it plainly.
        for attempt in range(2):
            try:
                data = self._post(payload, headers)
            except BackendError as exc:
                if attempt == 0 and TRANSIENT.search(str(exc)):
                    time.sleep(RETRY_PAUSE)
                    continue
                raise
            problem = _error_message(data)
            if problem:
                if attempt == 0 and TRANSIENT.search(problem):
                    time.sleep(RETRY_PAUSE)
                    continue
                raise BackendError(short_error(problem))
            choices = data.get("choices") or []
            if not choices:
                raise BackendError(f"unexpected response: {str(data)[:120]}")
            return (choices[0].get("message") or {}).get("content", "")
        raise BackendError(short_error("rate limited"))

    def _post(self, payload: bytes, headers: dict) -> dict:
        req = urllib.request.Request(self._url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self._cfg.api_timeout,
                                        context=cfg_mod.ssl_context()) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = json.loads(exc.read().decode()).get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001 - error bodies vary wildly
                pass
            hint = {401: " (bad or missing API key)", 404: " (wrong api_base or model)",
                    429: " (rate limited)"}.get(exc.code, "")
            raise BackendError(f"HTTP {exc.code}{hint}: {body or exc.reason}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise BackendError(f"{self._url} unreachable: {exc}") from exc


# --------------------------------------------------------------------------- #
# rule-based fallback - no model, instant, offline
# --------------------------------------------------------------------------- #
_MAC = cfg_mod.is_mac()

RULES: list[tuple[str, str]] = [
    # inventory
    (r"(installed|list).*(modules?|packages?|deps|dependencies)|packages?.*installed",
     "python3 -m pip list" + ("; brew list --versions" if _MAC else
      "; npm ls -g --depth=0 2>/dev/null; dpkg -l 2>/dev/null | awk 'NR>5{print $2, $3}'")),
    (r"(python|pip).*(packages?|modules?)", "python3 -m pip list"),
    (r"(npm|node).*(packages?|modules?)", "npm ls -g --depth=0"),
    (r"outdated", "python3 -m pip list --outdated"),
    # system
    (r"disk (space|usage)|free space|how full", "df -h"),
    (r"(biggest|largest).*(file|folder|dir)", "du -ah . 2>/dev/null | sort -rh | head -20"),
    (r"\b(ram|memory)\b", "vm_stat" if _MAC else "free -h"),
    (r"\bcpu\b|load", "uptime; top -l1 -n0 2>/dev/null | head -8" if _MAC else "uptime; top -bn1 | head -12"),
    (r"(listening|open).*ports?|ports?.*(listening|open)",
     "lsof -iTCP -sTCP:LISTEN -nP" if _MAC else "ss -tulpn"),
    (r"using port (\d+)",
     ("lsof -iTCP:{0} -sTCP:LISTEN -nP" if _MAC else "ss -tulpn | grep -w ':{0}'")),
    (r"process|running (apps?|programs?)",
     "ps aux | sort -k3 -r | head -15" if _MAC else "ps aux --sort=-%cpu | head -15"),
    (r"\bip address|my ip\b", "ifconfig | grep 'inet '" if _MAC else "ip -brief address"),
    (r"(os|kernel|system) (version|info)",
     "sw_vers; uname -a" if _MAC else "uname -a; cat /etc/os-release"),
    (r"uptime|how long.*(up|running)", "uptime"),
    (r"env(ironment)? (vars?|variables?)", "printenv | sort"),
    (r"who.*logged in|logged in users?", "who")
    ,
    # tooling
    (r"docker.*(container|running)", "docker ps -a"),
    (r"docker.*images?", "docker images"),
    (r"git.*(status|changed|modified)", "git status -sb"),
    (r"git.*branch", "git branch -vv"),
    (r"git.*(log|commits?|history)", "git log --oneline --graph -20"),
    (r"(find|search|locate).*(file|folder).*(named|called)\s+([\w.\-*]+)", "find . -iname '*{3}*'"),
    (r"(find|search).*text\s+[\"']?([\w.\-]+)[\"']?", "grep -rn '{1}' ."),
    (r"tail|follow.*log", "tail -f"),
]


class HeuristicBackend(Backend):
    """Pattern matcher used when no model is available (or as `--backend heuristic`)."""

    name = "heuristic"
    detail = "no model"

    def __init__(self, cfg: Optional[Config] = None):
        self._cfg = cfg

    def generate(self, system: str, user: str) -> str:
        q = user.strip().lower()
        for pattern, template in RULES:
            m = re.search(pattern, q)
            if m:
                if "{" in template:
                    groups = [g if g is not None else "" for g in m.groups()]
                    try:
                        return template.format(*groups)
                    except (IndexError, KeyError):
                        return template
                return template
        return "# no rule matched - install a model with: obiobi install"


# --------------------------------------------------------------------------- #
def build_backend(cfg: Config, verbose: bool = False) -> Backend:
    # In "auto", an explicitly configured endpoint wins - you asked for it -
    # then local models, then the offline rules.
    auto = [LlamaCppBackend, OllamaBackend, HeuristicBackend]
    if (cfg.api_base or "").strip():
        auto.insert(0, OpenAIBackend)
    order = {
        "auto": auto,
        "llama-cpp": [LlamaCppBackend],
        "ollama": [OllamaBackend],
        "api": [OpenAIBackend],
        "openai": [OpenAIBackend],
        "heuristic": [HeuristicBackend],
    }.get(cfg.backend, [HeuristicBackend])

    errors: list[str] = []
    for klass in order:
        try:
            backend = klass(cfg)
            # Remember what we had to skip, so callers can say so out loud instead
            # of silently answering with a weaker backend than the user expects.
            backend.fallback_from = errors
            return backend
        except BackendError as exc:
            errors.append(f"{klass.name}: {exc}")
        except Exception as exc:  # a broken model file shouldn't kill the shell
            errors.append(f"{klass.name}: {exc}")
    raise BackendError("no usable backend:\n  " + "\n  ".join(errors))
