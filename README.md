# obiobi 帯

[![PyPI](https://img.shields.io/pypi/v/obiobi?color=5f8787&label=pypi)](https://pypi.org/project/obiobi/)
[![Python](https://img.shields.io/pypi/pyversions/obiobi?color=5f8787)](https://pypi.org/project/obiobi/)
[![Downloads](https://img.shields.io/pypi/dm/obiobi?color=5f8787)](https://pypi.org/project/obiobi/)
[![Tests](https://github.com/ali-sehran/ObiObi/actions/workflows/tests.yml/badge.svg)](https://github.com/ali-sehran/ObiObi/actions/workflows/tests.yml)
[![License](https://img.shields.io/github/license/ali-sehran/ObiObi?color=5f8787)](LICENSE)
[![Stars](https://img.shields.io/github/stars/ali-sehran/ObiObi?style=flat&color=5f8787)](https://github.com/ali-sehran/ObiObi/stargazers)

> **帯** *obi* — the paper band around a bundle of notes. It holds the thing
> together without being the thing you look at.

**Plain-English → shell command, in your own terminal.** The answer appears in
dim grey on the next line. `Tab` takes it. `Enter` runs it. Nothing happens on
its own.

```
obi ~/project ❯ ??ask: what containers are running
  docker ps   [Tab]
```

<br>

## why this exists

I don't love AI. But a few times a day I know exactly what I want and can't
remember the flags — the `tar` incantation, which `find` does the thing, the
docker command I ran last week and lost. So I reach for it anyway.

Everything that does this wants to be an *agent*: run its own commands, take
over the screen, do things I didn't watch. I don't want that near my shell. I
want the command written on the line in grey, so I can read it, and **I** decide
if it runs.

So I built the small thing I actually wanted. It sits in my prompt, I type
`??ask:`, the command shows up dim under the cursor, Tab takes it, Enter runs
it. That's it. It uses my real history and my aliases. And `??docs` dumps the
session to a file, because I'm the kind of person who solves something, closes
the tab, and needs it again on Thursday.

Fair warning: this is mostly vibe-coded. But it has a test suite, and it will
not run anything destructive without two deliberate keystrokes — I wasn't going
to point an LLM at my own shell without that. It was built for me. Maybe you'll
find it as useful as I did.

<br>

## install

Three steps. macOS, Linux, and WSL, on Python 3.9+.

**1 — install the package**

```bash
pip install obiobi
```

> On macOS you may see `externally-managed-environment`. If so:
> `pip install --user obiobi`

**2 — make `obiobi` a command**

`python3 -m obiobi` already works in any terminal, no setup. For the short
`obiobi` word, add a one-line alias to **your shell's startup file** — and it
matters which one:

```bash
echo "alias obiobi='python3 -m obiobi'" >> ~/.zshrc          # zsh (macOS default)
echo "alias obiobi='python3 -m obiobi'" >> ~/.bash_profile   # bash on macOS
echo "alias obiobi='python3 -m obiobi'" >> ~/.bashrc         # bash on Linux
```

Then `source` that same file (or open a new terminal) and `obiobi` works
everywhere. macOS bash reads `~/.bash_profile`, **not** `~/.bashrc` — the most
common reason the alias "doesn't take."

**3 — pick a model**

```bash
obiobi config --reset
```

It sees what's already running and walks you through it — then just run `obiobi`:

```
obiobi setup — Enter takes the suggested value, Tab shows the alternatives

  ollama         found, 2 model(s) pulled
  local-server   vLLM / LM Studio / llama-server
  hosted-api     OpenRouter, OpenAI, Groq, Together

connect via [ollama]:
model [llama3.2:3b]:
✓ backend ollama:llama3.2:3b is reachable
```

One dependency (`prompt_toolkit`), no model bundled.

> **Windows:** run it inside WSL and follow the steps above. Native PowerShell
> isn't supported yet — obiobi runs commands through a POSIX shell.

<br>

## what it looks like

**Ask for a command.** Type `??ask:` and the suggestion fades in below the line.

```
obi ~/project ❯ ??ask: how much disk space is left
  df -h .   [Tab]
```

**It knows your machine.** At setup obiobi scans what you have installed —
`$PATH`, plus your `pip` / `npm` / `brew` packages — and hands the model that
list, so it reaches for your tools instead of guessing:

```
obi ~/project ❯ ??ask: follow the logs for my kafka container and grep warnings
  docker logs -f kafka 2>&1 | grep -i warn   [Tab]
```

The scan runs once during setup. Installed something new? Re-scan with `obiobi
index` (`obiobi index --show` prints exactly what the model is told). It only
reads names — it never runs a binary to find out what it does.

**Destructive commands take two Tabs.** The first press only arms it; typing
anything cancels it.

```
obi ~/project ❯ ??ask: delete the node_modules folder
  rm -rf node_modules   ⚠ deletes files   [Tab][Tab]
```

**Tab completes like a shell** when there's no suggestion to take — commands
first, then paths:

```
lso<Tab>          → lsof
cat READ<Tab>     → cat README.md
cd tes<Tab>       → cd tests/
```

**It remembers, so you don't have to.** `??docs` writes the session's questions
and the commands they produced to a file — for the thing you solve today and
need again next Thursday:

```markdown
# obiobi session — 2026-08-11
## how much free memory
free -h | awk '/^Mem:/ {print $4}'
```

<br>

## it's not an agent

That's the whole point. obiobi is one dim line in your prompt, not a thing that
runs off and does stuff.

- **Nothing runs on its own.** Grey text until *you* press Tab. Destructive
  commands take two.
- **No takeover.** No dashboard, no "agent is thinking…", no background daemon,
  no account, no telemetry. One process, started by you, gone on `Ctrl-D`.
- **Your shell stays yours.** Real `bash`/`zsh` history, your aliases and
  functions, your prompt. It reads and appends to the history file your terminal
  already uses.
- **Local-first.** Point it at `ollama` and nothing leaves the machine. Use a
  hosted API if you want — and the banner tells you, on startup, when a request
  will leave.
- **Your key is yours.** Stored in a `0600` file, never in the config that's
  safe to commit or copy.

<br>

## bring your own model

`obiobi config --reset` is the easy path. To wire one up by hand — any
OpenAI-compatible endpoint works:

```bash
obiobi config --set backend=api \
              --set api_base=https://openrouter.ai/api/v1 \
              --set api_model=nvidia/nemotron-3-nano-30b-a3b:free \
              --set api_key_env=OPENROUTER_API_KEY
obiobi config --set-key    # prompts, saves the key to a 0600 file
```

| endpoint | `api_base` | key |
| --- | --- | --- |
| ollama | `http://127.0.0.1:11434/v1` | — |
| vLLM / LM Studio / llama-server | `http://127.0.0.1:{port}/v1` | — |
| OpenAI | `https://api.openai.com/v1` | yes |
| OpenRouter | `https://openrouter.ai/api/v1` | yes |
| Groq | `https://api.groq.com/openai/v1` | yes |
| Together | `https://api.together.xyz/v1` | yes |

Localhost needs no key. There's also a **heuristic** backend — ~25 regex rules,
no model at all — so it does something useful the second it's installed.

<br>

## keys

| key | what it does |
| --- | --- |
| `Tab` | take the grey text; or, if there's none, complete a command / path |
| `Tab` `Tab` | accept a **risky** command — the first press only arms it |
| `Enter` | run the line. It never accepts a suggestion; that's Tab's job |
| `Esc` / `Ctrl-G` | dismiss the suggestion |
| `Ctrl-D` | exit |

<br>

## commands

Inside the prompt, just type:

| type this | when you want to… |
| --- | --- |
| `??ask: <question>` | ask for a command in plain English (`??` and `??ask` work too) |
| `??docs` | save this session's questions + answers to a timestamped file |
| `history [n]` | see your real shell history (last `n`) |
| `:backend` | check which model is answering right now |
| `:dry` | toggle dry-run — print commands instead of running them |
| `:help` | show the key reminder |
| `exit` / `Ctrl-D` | leave |

From your shell, without entering the prompt:

| command | when you want to… |
| --- | --- |
| `obiobi` | start the interactive prompt (the usual way to use it) |
| `obiobi config --reset` | **set up / switch model** — assisted, detects what's running |
| `obiobi config` | see current settings and where the key comes from |
| `obiobi config --set KEY=VALUE` | change one setting, e.g. `--set debounce_ms=500` |
| `obiobi config --set-key` | paste an API key (saved to a `0600` file) |
| `obiobi config --forget-key` | delete the saved key |
| `obiobi doctor` | **is it working?** — config, key, backend reachability, history sync |
| `obiobi index` | re-scan installed tools after you install something new |
| `obiobi index --show` | print exactly what the model is told you have |
| `obiobi ask "…"` | one-shot: just print the command for a question |
| `obiobi ask "…" --run` | print it and run it |
| `obiobi --dry-run` | run the prompt but never execute — only show |
| `obiobi --backend NAME` | force `api` / `ollama` / `llama-cpp` / `heuristic` for one run |

<br>

## a few honest notes

- **It's a small model by default.** It nails everyday inventory/inspection
  questions and gets creative with rare flags — so read the grey line before you
  press Tab. A bigger model or endpoint is one `config --reset` away.
- **The safety screen is a net, not a sandbox.** It blocks the worst shapes
  (`rm -rf /`, `mkfs`, `dd` to a disk, `curl … | sh`) and flags the risky ones,
  but it's a denylist — a creative command can slip past. The real guarantee is
  that nothing runs without your keystroke. `obiobi --dry-run` never executes,
  just prints.
- **bash users, for history to sync live** between obiobi and your terminal, add
  to your rc — details in [INSTALL.md](INSTALL.md):
  ```bash
  shopt -s histappend
  PROMPT_COMMAND='history -a; history -c; history -r'
  ```

<br>

## more

- [INSTALL.md](INSTALL.md) — step-by-step setup, where files live, uninstall
- [RELEASING.md](RELEASING.md) — maintainer notes
- `python3 -m unittest discover -s tests` — 119 tests, green on 3.9 & 3.13

Built for me. If it saves you a trip to a search engine now and then, that's
plenty. PRs and issues welcome.
