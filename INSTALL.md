# Installing obiobi 帯 on a new machine

Works the same on macOS, Linux, WSL and Windows. You need Python 3.9 or newer.

## 1. Install

```bash
pipx install obiobi
```

`pipx` gives obiobi its own environment and puts the command on your PATH. If
you don't have it, any of these work just as well:

```bash
uv tool install obiobi        # if you use uv
pip install --user obiobi     # plain pip
```

If the shell says `obiobi: command not found` afterwards, the install directory
isn't on your PATH. `pipx ensurepath` fixes it, or add this to your shell rc:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## 2. Configure

```bash
obiobi config --reset
```

That is an assisted setup: it detects a running ollama daemon, offers
`local-server` (vLLM / LM Studio / llama-server) or a hosted API, and fills in
sensible defaults. Enter takes the recommendation, Tab shows the alternatives.

Run `obiobi config` on its own to see what is set and what is missing:

```
obiobi    ~/.config/obiobi/config.json
  backend        auto
  api_base       not set
  api_model      gpt-4o-mini
  api_key_env    OPENAI_API_KEY
  (13 more settings: obiobi config --all)

api key   not set
  save one for every session:  obiobi config --set-key
  or export $OPENAI_API_KEY in your shell rc
```

Point it at a provider. Any OpenAI-compatible endpoint works — this is
OpenRouter's free tier, which needs no credit:

```bash
obiobi config --set backend=api \
              --set api_base=https://openrouter.ai/api/v1 \
              --set api_model=nvidia/nemotron-3-nano-30b-a3b:free \
              --set api_key_env=OPENROUTER_API_KEY
```

Then give it the key once:

```bash
obiobi config --set-key
API key (not echoed): ••••••••
saved to ~/.config/obiobi/credentials (mode 600)
```

That file is readable only by you and is the **only** place a key is written.
`config.json` never contains it, so you can copy that file to another machine,
commit it, or paste it in a ticket. `obiobi config --forget-key` removes it.

An environment variable still wins if you set one, which is what you want on a
shared or CI machine:

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
```

The first `config --set ...` also scans the machine for installed commands and
packages, so the model suggests `docker ps` on a box that has docker. Re-run
`obiobi index` after installing new tools.

## 3. Check and run

```bash
obiobi doctor      # os, python, endpoint, key source, index, live backend
obiobi             # the prompt
```

```
obi ~/projects ❯ ??ask: what containers are running
  docker ps   [Tab]
```

## No API at all?

Two offline options, neither needs a key:

```bash
obiobi config --set backend=ollama    # a local ollama daemon
obiobi config --set backend=heuristic # ~25 regex rules, instant, no model
```

For a local GGUF through llama.cpp: `pip install "obiobi[local]"` then
`obiobi install --backend llama-cpp`.

## Where things live

| path | what |
| --- | --- |
| `~/.config/obiobi/config.json` | settings — safe to share |
| `~/.config/obiobi/credentials` | the API key, mode 600 |
| `~/.local/share/obiobi/tools.json` | the list of installed commands |
| `~/.bash_history` / `~/.zsh_history` | your history — obiobi reads and appends to it |

**bash users — keeping history in sync.** For commands you run in obiobi to show
up in your terminal's `history` (and vice versa) while both are open, add two
lines to your rc (`~/.bashrc`, or `~/.bash_profile` on macOS):

```bash
shopt -s histappend                                   # don't overwrite on exit
PROMPT_COMMAND='history -a; history -c; history -r'   # flush + reload each prompt
```

`histappend` stops bash truncating the file when a terminal closes.
`PROMPT_COMMAND` flushes this terminal's commands and re-reads the file after
every prompt, so both sides stay current. Use exactly `-a; -c; -r` — the shorter
`history -a; history -n` silently drops entries another process appended.
`obiobi doctor` tells you whether the sync is active. zsh shares history without
any of this.

## Uninstall

```bash
pipx uninstall obiobi
rm -rf ~/.config/obiobi ~/.local/share/obiobi
```
