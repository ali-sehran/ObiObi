# obiobi 帯

[![PyPI](https://img.shields.io/pypi/v/obiobi?color=5f8787&label=pypi)](https://pypi.org/project/obiobi/)
[![Python](https://img.shields.io/pypi/pyversions/obiobi?color=5f8787)](https://pypi.org/project/obiobi/)
[![Downloads](https://img.shields.io/pypi/dm/obiobi?color=5f8787)](https://pypi.org/project/obiobi/)
[![Tests](https://github.com/ali-sehran/ObiObi/actions/workflows/tests.yml/badge.svg)](https://github.com/ali-sehran/ObiObi/actions/workflows/tests.yml)
[![License](https://img.shields.io/github/license/ali-sehran/ObiObi?color=5f8787)](LICENSE)
[![Stars](https://img.shields.io/github/stars/ali-sehran/ObiObi?style=flat&color=5f8787)](https://github.com/ali-sehran/ObiObi/stargazers)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-5f8787.svg)](https://makeapullrequest.com)

> **帯** *obi* — the sash tied around a kimono, and the paper band wrapped
> around a bundle of notes or a book. One quiet strip that holds the whole
> thing together without being the thing you look at.

That is the whole design brief. obiobi is a band around your shell: it binds
your terminal, your history, the tools you have installed and a language model
into one line of dim grey text, and then gets out of the way.

A terminal prompt that turns plain-English questions into shell commands using a
small language model — local, or any endpoint you point it at.

```
obi ~/Desktop/obiobi ❯ ??ask: what containers are running
  docker ps   [Tab]
```

The second line is the suggestion, drawn in dim grey. **`Tab`** turns it into the
real input line, **`Enter`** runs it. Nothing executes until you accept it.

Type an ordinary command and the grey text is your **last matching command**
instead — `doc` → `doc`**`ker ps`**. Same `Tab` to take it.

Tab completes like a shell when there's no grey text to take: the first word of
a line against every executable on `$PATH`, everything after it against the
filesystem. It knows a command position from an argument, including after a
`|`, `;` or `&&`:

```
lso<Tab>            → lsof
cat READ<Tab>       → cat README.md
cd tes<Tab>         → cd tests/
ls | gre<Tab>       → ls | grep
```

Tab inserts the candidate straight away and cycles through the rest on further
presses, the way zsh's menu-complete does. There is no floating menu on purpose:
prompt_toolkit reserves eight blank rows under the prompt to hold one, whether
or not anything is completing. While a completion is open **Enter picks, it does
not run** — you get to read what you picked and press Enter again to execute:

```
cat READ  →  [Tab]  cat README.md   (menu open)
          →  [Enter] takes it, line sits there
          →  [Enter] runs it
```

The grey history replay takes priority over the completion menu, so `doc<Tab>`
gives you `docker ps` (your last matching command) rather than a list. Use `→`
if you want the replay without disturbing an open menu.

Anything that deletes, sudos, kills or installs is offered with a reason and
takes **two** deliberate Tabs, so it can't be accepted by reflex:

```
obi ~/projects ❯ ??ask: recursively delete the node_modules folder
  rm -rf node_modules   ⚠ deletes files   [Tab][Tab]
```

The first Tab leaves the line alone and changes the note to
`⚠ deletes files - [Tab] again to accept`. Typing anything cancels it.

| key | what it does |
| --- | --- |
| `Tab` | accept the grey text; if there is none, **complete** a command or path |
| `Tab` `Tab` | a **risky** command needs two presses — the first only arms it |
| `→` | accept the grey text without touching completion (fish/zsh habit) |
| `Enter` | with a completion menu open: take the highlighted item, don't run |
| `Enter` | otherwise run the line. It never accepts a suggestion; that is Tab's job |
| `Ctrl-G` / `Esc` | dismiss the suggestion |
| `Ctrl-D` | exit |
| `??docs` | write this session's questions and answers to a file |
| `history [n]` | your real shell history |
| `:help` `:backend` `:dry` | in-shell meta commands |

## Install

One command, any OS with Python 3.9+ — see [INSTALL.md](INSTALL.md) for the
step-by-step version.

```bash
pipx install obiobi        # or: uv tool install obiobi   /   pip install obiobi
obiobi config --set backend=api \
              --set api_base=https://openrouter.ai/api/v1 \
              --set api_model=nvidia/nemotron-3-nano-30b-a3b:free \
              --set api_key_env=OPENROUTER_API_KEY
obiobi config --set-key     # prompts, saves to ~/.config/obiobi/credentials (600)
obiobi
```

That is the whole setup. `obiobi config` on its own prints what is set, what is
missing and how to fix it; the first `--set` also indexes what is installed on
the machine. One pure-python dependency (`prompt_toolkit`), a 33 KB wheel, no
model bundled.

The key goes in its own 0600 file, never in `config.json` — so `config.json`
stays safe to commit or copy between machines. An environment variable still
wins if you set one. `obiobi config --forget-key` removes it.

```bash
obiobi                     # interactive shell
obiobi ask "how much disk space is left"     # one-shot, prints the command
obiobi ask "..." --run                       # print and execute
obiobi index --show        # re-scan, and print what the model is told
obiobi doctor              # what's installed, which backend is live
obiobi config              # show / change settings
obiobi --dry-run           # never execute, just show
```

`./install.sh` is still there for a self-contained venv install from a checkout
(`./install.sh ollama|llama-cpp|heuristic`), but it is no longer the main path.

## Your history is the shell's history

obiobi keeps no history of its own. It reads `~/.bash_history` or
`~/.zsh_history` directly and appends to it, so anything you run here shows up
in `history` in every other terminal, and Up-Arrow walks the commands you ran
outside obiobi. `??ask:` lines and meta commands are filtered out — only real
commands are stored.

`history` inside obiobi lists the same commands your terminal does, in the same
order. The **numbers are close but cannot be made identical**, for three
independent reasons, all verified against a live bash:

1. A shell's history number is a per-session counter whose origin depends on
   how long the file was when *that* terminal opened. Two terminals number the
   same command differently.
2. bash keeps only the last `HISTSIZE` entries (default **500**) and renumbers
   from 1, so once your file passes that the numbers shift. Raising `HISTSIZE`
   and `HISTFILESIZE` in your rc removes this one.
3. A file line is not a history entry: bash skips blank lines and folds
   backslash-continued commands into one entry.

obiobi shows the one number two processes can agree on — the entry's position
in the file — and says so under the listing. Don't feed them to `!123`; that
resolves against your shell's counter, not the file.

zsh's two on-disk formats are both handled; the existing file decides which one
is appended. **bash users:** add `shopt -s histappend` to your rc. Without it
bash *overwrites* the history file when a terminal exits and would drop the
entries obiobi added while that terminal was open.

fish is not supported — its history format is different enough that obiobi
stays out of it and falls back to its own file.

## What it knows about your machine

`obiobi index` writes a plain list of names to `~/.local/share/obiobi/tools.json`
and every request hands that list to the model. A name is enough — the model
already knows what `docker` is; it only needs to know that you have it.

| source | what it gives |
| --- | --- |
| `$PATH` directory scan | executable names, **excluding** `/usr/bin` and friends |
| `importlib.metadata` | installed python distributions |
| `npm ls -g --depth=0` | global node packages |
| `brew list --formula` | homebrew formulae |

```
✓ indexed 269 commands, 48 packages
```

The base OS is filtered out on purpose: every machine has `awk`, so listing it
teaches the model nothing. What matters is that *this* machine has `docker`,
`kubectl` and `psql`. ~270 names is roughly 800 tokens, small enough to send in
full rather than guess which ones are relevant.

**Nothing unknown is ever executed.** obiobi does not run `--help` on the
binaries it finds, and does not read man pages. The only commands it runs are
the three package managers named above. Running strangers to read their banner
is how you get a keychain prompt out of `docker-credential-osxkeychain`; a test
asserts that only `python3`, `npm` and `brew` are ever invoked.

```bash
obiobi index --show                  # rebuild, and print exactly what the model gets
obiobi config --set use_index=false  # or turn the whole thing off
obiobi config --set index_limit=800  # most names sent per list
```

Re-run `obiobi index` after installing new tools; nothing watches for them.
Only the first `python3` on `$PATH` is asked, so pyenv and per-project venvs
contribute whichever one is active when you run it.

## ??docs

`??docs` writes the session's questions and the commands they produced to a
timestamped markdown file in the current directory:

```markdown
# obiobi session - 2026-08-10 20:30:10
_1 question_

## 1. how much free memory

```sh
free -h | awk '/^Mem:/ {print $4}'
```
```

## Quiet by default

The band is meant to be barely visible. Everything obiobi does is designed to
stay out of your way and off your machine:

- **Nothing runs on its own.** Every suggestion is grey text until you press
  `Tab`. Anything that deletes, sudos, kills or installs takes `Tab` twice.
- **Nothing unknown is executed.** obiobi never runs the binaries it finds to
  learn about them — it reads their names. The only commands it invokes are
  `python3`, `npm` and `brew`, and a test enforces that.
- **No telemetry, no account, no daemon.** One process, started by you, gone
  when you press `Ctrl-D`.
- **Your key stays yours.** It lives in a `0600` file that `config.json` never
  touches, so the config is safe to commit or copy between machines.
- **Your shell stays yours.** obiobi keeps no history of its own; it reads and
  appends to the one your terminal already uses.
- **It tells you when it leaves the machine.** A remote endpoint is announced
  on startup, because your question and your cwd travel with it.

## Backends — bring your own model

Nothing here is hardcoded to one provider. Four backends, resolved in this order
when `backend = "auto"`:

1. **api** — any OpenAI-compatible `/chat/completions` endpoint. Only tried in
   `auto` if you've configured one, since it's a deliberate choice.
2. **llama.cpp** — a local `.gguf` in `~/.local/share/obiobi/models/`, loaded
   through `llama-cpp-python`. Fully offline.
3. **ollama** — a daemon at `$OLLAMA_HOST` (default `http://127.0.0.1:11434`).
4. **heuristic** — ~25 regex rules (package inventories, disk, memory, ports,
   processes, git, docker). No model, no latency, platform-aware (`free -h` on
   Linux, `vm_stat` on macOS). The always-available fallback.

Force one with `--backend api|llama-cpp|ollama|heuristic`.

### Your own GGUF

```bash
obiobi install --gguf-url https://your.host/some-model-Q4_K_M.gguf
# or just drop any .gguf into ~/.local/share/obiobi/models/
obiobi config --set gguf_path=/path/to/model.gguf
export OBIOBI_MODEL_URL=https://...        # env override
```

With no `gguf_path` set, the smallest `.gguf` in the models directory is used —
smallest means fastest to answer.

### OpenAI (or any compatible endpoint)

```bash
export OPENAI_API_KEY=sk-...
obiobi config --set api_base=https://api.openai.com/v1 --set api_model=gpt-4o-mini
obiobi --backend api
```

The same backend covers everything that speaks the OpenAI dialect — swap
`api_base`:

| endpoint | `api_base` | key needed |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | yes |
| OpenRouter | `https://openrouter.ai/api/v1` | yes |
| Groq | `https://api.groq.com/openai/v1` | yes |
| Together | `https://api.together.xyz/v1` | yes |
| `llama-server` (llama.cpp) | `http://127.0.0.1:8080/v1` | no |
| LM Studio | `http://127.0.0.1:1234/v1` | no |
| vLLM | `http://127.0.0.1:8000/v1` | no |
| Ollama's OpenAI shim | `http://127.0.0.1:11434/v1` | no |

You do **not** need the key set when you run `obiobi config` — that only writes
JSON. The key is read at the moment a request is made, so order doesn't matter.
Put the export in your `~/.zshrc` or `~/.bashrc` to make it stick, or prefix a
single run: `OPENAI_API_KEY=sk-... obiobi`. Run `obiobi config` or `obiobi doctor`
to see whether it currently resolves.

`--backend api` is only needed to *force* the endpoint. With `backend = auto` a
configured endpoint is already tried first; forcing it means you get a hard error
instead of a quiet fall back to a weaker backend. Make it permanent with
`obiobi config --set backend=api`. (`--backend openai` is accepted as an alias;
the backend is called `api` because it isn't OpenAI-specific.) Whenever a backend
is skipped, the reason is printed — you'll never get regex answers while thinking
you're talking to GPT.

Keys are read from the environment — `$OPENAI_API_KEY` by default, renameable via
`api_key_env`, or `$OBIOBI_API_KEY` — and are **never written to the config
file**. Localhost endpoints don't require one. When a remote host is in use, the
banner says so on startup, because your questions (and the cwd in the system
prompt) leave the machine. Env overrides: `OBIOBI_API_BASE`,
`OBIOBI_API_MODEL`, `OBIOBI_BACKEND`.

### OpenRouter, on the free tier

```bash
obiobi config --set backend=api \
              --set api_base=https://openrouter.ai/api/v1 \
              --set api_model=nvidia/nemotron-3-nano-30b-a3b:free \
              --set api_key_env=OPENROUTER_API_KEY
export OPENROUTER_API_KEY=sk-or-v1-...        # your own key; put it in ~/.zshrc
obiobi
```

The config file holds the *name* of the variable, never the key — so it is safe
to commit or share, and everyone who clones this brings their own.

Small free models refuse at random — the same question that answers `ls` once
comes back `# cannot` the next time. obiobi asks once more when it sees a
refusal, which measured 1-in-6 wrong refusals down to 0-in-6 while still
refusing things that genuinely have no shell command. Turn it off with
`obiobi config --set retry_refusals=false`. If refusals still bother you,
`nvidia/nemotron-3-super-120b-a12b:free` is steadier at ~1.2 s versus ~0.6 s.

Every `:free` model on OpenRouter is a hybrid reasoning model, so obiobi sends
`reasoning: {enabled: false}` to that host — otherwise the whole `max_tokens`
budget goes to thinking and the reply comes back empty. Free models are also
rate-limited by a shared pool. When it is exhausted OpenRouter answers **HTTP
200 with an error body**, so obiobi reads the body rather than the status code,
retries once after a second, and then says `the model is busy right now (free
tier is shared)` instead of printing a truncated JSON dict. Raise `debounce_ms`
further if you still hit it. `nemotron-3-nano-30b-a3b:free` answers in ~1.5 s;
`poolside/laguna-xs-2.1:free` is a touch faster, `gemma-4-*-it:free` is ~6 s.

### Assisted setup

```bash
obiobi config --reset
```

```
obiobi setup - Enter takes the suggested value, Tab shows the alternatives

  ollama         found, 2 model(s) pulled
  local-server   vLLM / LM Studio / llama-server
  hosted-api     OpenRouter, OpenAI, Groq, Together

connect via [ollama]:
model [llama3.2:3b]:
✓ backend ollama:llama3.2:3b is reachable
```

It checks what is already running and recommends accordingly: if an ollama
daemon answers, that is the default and the models it lists become the choices;
if you pick a local server it queries `/v1/models` and offers what that server
is actually serving. **Enter** takes the recommendation, **Tab** fills it in so
you can edit it and shows the alternatives after it, typing replaces it.

A local GGUF through llama-cpp-python is deliberately not offered — it compiles
a C extension and downloads gigabytes, and `ollama pull` does the same job.
`obiobi install --backend llama-cpp` is still there if you want it.

### Settings

```bash
obiobi config                      # what is set, and where the key comes from
obiobi config --set debounce_ms=500 --set confirm_risky=false
obiobi config --all                # plus the settings other backends use
```

Stored in `~/.config/obiobi/config.json`. The listing only shows settings the
active backend actually uses — `gguf_url` and `ollama_model` are noise on an API
endpoint, and nobody set them. `--all` adds them back, marked `(unused with
backend=api)`.

## How the suggestion works

Typing schedules a translation after an 800 ms pause (`debounce_ms`). Every
keystroke cancels the pending timer, so only a real pause spends a request —
and the window has to be longer than a mid-sentence pause or each pause fires
one. Measured on a 43-character question typed with 0.55 s pauses: **450 ms
cost 8 requests, 7 of them for half-typed fragments that were thrown away;
800 ms costs 1.** `Tab` still means "ask now" if you don't want to wait it out.
It runs on a worker thread, so the prompt never blocks; a spinner shows while
the model thinks. Only the newest question's answer is kept — if you keep editing, stale
answers are dropped. Buffer mutations always happen on the UI thread, during
render, never from the worker.

The model is asked for exactly one command, and the reply is sanitised: code
fences, `$ ` prompt markers, backticks and prose lines are stripped. If nothing
usable comes back, the ghost line says so instead of guessing.

## Your shell's functions and aliases

Commands run through **`$SHELL -lc`**, a login shell, so `~/.bash_profile` and
`~/.zshrc` are sourced and the functions and aliases you defined there exist:

```
obi ~/Desktop ❯ skey
live: git_internal
have: git_internal sa_key
```

A plain `bash -c` is neither login nor interactive and reads no profile at all,
which is why a personal function used to die with `command not found`. bash also
ignores aliases when it is not interactive, so obiobi turns on `expand_aliases`.

The profile is re-sourced for each command. Measured on a profile that loads
nvm: **~130 ms** versus ~2 ms without. If your profile is heavy and you would
rather have the milliseconds back, `obiobi config --set login_shell=false`.

## Safety

Every suggestion is screened before it is offered:

- **Blocked** — never offered or run: `rm -rf /`, `mkfs`, raw writes to block
  devices, fork bombs, `curl … | sh`, `chmod 777 /`. The ghost line shows
  `refused: <reason>`.
- **Risky** — offered with a `⚠` and a reason, and requires a typed `y` before it
  runs: sudo, deletes, `kill`, package installs, `git reset --hard`, force pushes,
  writes into system directories, docker removals.

`confirm_risky` and `dry_run` are configurable. Commands run in `$SHELL -c`;
`cd` is handled in-process so directory changes persist.

## Tests

```bash
python3 -m unittest discover -s tests      # 118 tests
python3 tests/pty_demo.py                  # drives a real pty, shows the output
```

`tests/test_api_backend.py` runs a real HTTP server on localhost and asserts the
request shape, bearer auth, key-less localhost access, and that a 401 produces a
readable message, plus that a refusal or a blocked command never reaches stdout.
`tests/test_index.py` covers the installed-command index.
`tests/test_ui2.py` drives the actual prompt through a pipe input and asserts the
full flow: ghost appears → `Tab` solidifies → `Enter` submits; `Tab` before the
debounce forces generation; editing the question replaces a stale suggestion.

## Notes / known limits

- The default GGUF download URL is unverified — if it 404s, the installer falls
  back to the heuristic backend and tells you. `ollama pull` is the safer path.
- A 0.5B model is fast but modest. It handles everyday inventory/inspection
  questions well and gets creative with rare flags; read the grey line before
  pressing Tab. A 1.5B–3B model is noticeably better if you have the RAM.
- The index is a snapshot: install a new tool and it stays invisible until you
  re-run `obiobi index`.
- `Esc` to dismiss depends on the terminal flushing a lone escape byte; `Ctrl-G`
  always works.
- prompt_toolkit hides its own `bottom_toolbar` when the renderer height is
  unknown (terminals that don't answer cursor-position requests), which would
  make the suggestion silently vanish — so the ghost row is part of the layout
  instead of being a toolbar.

## Publishing a release

```bash
python -m build                       # -> dist/*.whl and dist/*.tar.gz
python -m twine check dist/*          # must say PASSED for both
python -m twine upload dist/*         # username: __token__, password: pypi-...
```

Bump `version` in `pyproject.toml` first — PyPI refuses to overwrite a version
that already exists. Try it against TestPyPI if you want a dry run:

```bash
python -m twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ obiobi
```

Get the token from <https://pypi.org/manage/account/token/>. Scope it to this
project once the project exists; the first upload needs an account-wide token.

## Files

```
obiobi/config.py     paths, defaults, persisted config
obiobi/backends.py   api (OpenAI-compatible) / llama.cpp / ollama / heuristic
obiobi/nl2cmd.py     prompt template, output sanitising, ??ask: parsing
obiobi/ui.py         the prompt, the debounced Suggester thread, the ghost row
obiobi/safety.py     blocked and risky command patterns
obiobi/executor.py   confirmation and execution
obiobi/installer.py  model download, pip, ollama pull
obiobi/index.py      $PATH + package-manager scan, names only
obiobi/history.py    the real shell history, read and appended; ??docs
obiobi/wizard.py     the assisted setup behind `config --reset`
obiobi/cli.py        install / ask / index / doctor / config / run
```
