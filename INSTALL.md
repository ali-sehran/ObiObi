# Installing obiobi 帯 on a new machine

Three steps. macOS, Linux, and WSL, on Python 3.9+.
(Windows: run it inside WSL — obiobi runs commands through a POSIX shell, so
native PowerShell isn't supported yet.)

## 1. Install the package

```bash
pip install obiobi
```

On macOS you may see `externally-managed-environment`. If so, scope it to your
user:

```bash
pip install --user obiobi
```

## 2. Make `obiobi` a command

`python3 -m obiobi` already works in every terminal, with no PATH setup — try
it now. For the short `obiobi` word, add a one-line alias to **your shell's
startup file**. It matters which one:

```bash
echo "alias obiobi='python3 -m obiobi'" >> ~/.zshrc          # zsh (macOS default)
echo "alias obiobi='python3 -m obiobi'" >> ~/.bash_profile   # bash on macOS
echo "alias obiobi='python3 -m obiobi'" >> ~/.bashrc         # bash on Linux
```

Then `source` that same file (or open a new terminal) and `obiobi` works
everywhere:

```bash
source ~/.bash_profile     # or ~/.zshrc — whichever you edited
```

> **`obiobi: command not found`?** The alias went in a file your shell doesn't
> read. macOS bash login shells read `~/.bash_profile`, **not** `~/.bashrc` —
> that's the #1 cause. When in doubt, just use `python3 -m obiobi`; it always
> works.

## 3. Pick a model

```bash
obiobi config --reset
```

Assisted setup: it detects a running ollama daemon, offers `local-server`
(vLLM / LM Studio / llama-server) or a hosted API, and fills in sensible
defaults. **Enter** takes the recommendation, **Tab** shows the alternatives.
It also builds the index of your installed tools, so the model suggests
`docker ps` on a box that has docker.

Then just run it:

```bash
obiobi
```

```
obi ~/projects ❯ ??ask: what containers are running
  docker ps   [Tab]
```

---

## Configuring by hand

`obiobi config` on its own shows what's set and what's missing. To wire up a
provider without the wizard — any OpenAI-compatible endpoint works; this is
OpenRouter's free tier, which needs no credit:

```bash
obiobi config --set backend=api \
              --set api_base=https://openrouter.ai/api/v1 \
              --set api_model=nvidia/nemotron-3-nano-30b-a3b:free \
              --set api_key_env=OPENROUTER_API_KEY
obiobi config --set-key        # prompts, saves to ~/.config/obiobi/credentials (mode 600)
```

The key lives in that `credentials` file and **nowhere else** — `config.json`
only stores the *name* of the env var, so it's safe to commit or copy between
machines. An environment variable wins if you set one (handy for CI):

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
```

`obiobi config --forget-key` deletes the saved key.

## No API at all

Two offline options, neither needs a key:

```bash
obiobi config --set backend=ollama      # a local ollama daemon
obiobi config --set backend=heuristic   # ~25 regex rules, instant, no model
```

For a local GGUF through llama.cpp: `pip install "obiobi[local]"`, then
`obiobi install --backend llama-cpp`.

## Check it's working

```bash
obiobi doctor    # os, python, endpoint, key source, index, live backend
```

The bottom `backend` line is the real test — it actually builds the backend, so
if something's off (no key, wrong URL, ollama down) it says so there.

## Keep your history in sync (bash only)

Commands you run in obiobi already go to `~/.bash_history`. For an **already-open**
terminal to see them (and vice versa), add to your rc — `~/.bashrc`, or
`~/.bash_profile` on macOS:

```bash
shopt -s histappend
PROMPT_COMMAND='history -a; history -c; history -r'
```

Use exactly `-a; -c; -r` — the shorter `history -a; history -n` silently drops
entries. zsh shares history without any of this. `obiobi doctor` tells you
whether the sync is active.

## Where things live

| path | what |
| --- | --- |
| `~/.config/obiobi/config.json` | settings — safe to share |
| `~/.config/obiobi/credentials` | the API key, mode 600 |
| `~/.local/share/obiobi/tools.json` | the index of installed commands |
| `~/.bash_history` / `~/.zsh_history` | your history — obiobi reads and appends |

## Uninstall

```bash
python3 -m pip uninstall obiobi          # add --break-system-packages on macOS if it complains
rm -rf ~/.config/obiobi ~/.local/share/obiobi   # settings, key, and index
```

`pip uninstall` removes the program; the second line removes your settings and
the saved key. Also drop the alias line from your shell rc if you added one.
