"""The interactive prompt.

Behaviour
---------
    obi ❯ ??ask: check all installed modules and packages
          python3 -m pip list; npm ls -g --depth=0 ...      <- dim grey, on the line below

    [Tab]   the grey text becomes the real, solid input line. With no grey
            text it completes a command name or a path, like a shell does.
            A risky command needs Tab twice - the first press only arms it.
    [Enter] runs the line. It never accepts a suggestion; that is Tab's job.
    [Esc]   dismisses the suggestion

Generation happens on a worker thread, debounced, so typing never blocks.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.auto_suggest import AutoSuggest, AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, is_done
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from . import config as cfg_mod
from .backends import Backend
from .config import Config
from .history import ShellHistory
from .nl2cmd import is_ask, strip_prefix, translate
from .safety import screen

STYLE = Style.from_dict({
    "prompt": "#5fafd7 bold",
    "prompt.path": "#87afaf",
    "prompt.mark": "#5f8787",
    "auto-suggestion": "#767676",   # the grey inline replay of a past command
    "rprompt": "#585858",
    "ghost-row": "noreverse bg:default",
    "ghost": "#767676",            # the light grey suggestion
    "ghost.pending": "#585858 italic",
    "ghost.warn": "#af8700",
    "ghost.error": "#af5f5f",
    "hint": "#585858",
})

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Below this many characters a line is still a fragment, not a question, and
# asking about it only spends a request that its own next keystroke discards.
MIN_QUESTION = 8


class Suggester:
    """Debounced, coalescing background translator.

    Only the newest request matters; older ones are dropped. Results are applied
    to the input buffer on the UI thread (via `tick`, called during render) so we
    never mutate prompt_toolkit state from a worker thread.
    """

    def __init__(self, translate_fn: Callable[[str], str], debounce_ms: int = 450):
        self._translate = translate_fn
        self._debounce = debounce_ms / 1000.0
        self._cv = threading.Condition()
        self._queued: Optional[str] = None
        self._timer: Optional[threading.Timer] = None

        self.query: str = ""        # question the current suggestion answers
        self.suggestion: str = ""
        self.status: str = "idle"   # idle | thinking | ready | error
        self.error: str = ""
        self.armed = False          # a risky suggestion, one Tab away from accepted
        self.log: list[tuple[str, str]] = []   # (question, command) for ??docs
        # Set once the prompt exists: worker threads have no app context of their
        # own (it is thread-local), so they need a direct handle to redraw.
        self.app = None

        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._ticker, daemon=True).start()

    # ---------- scheduling ----------
    def schedule(self, question: str) -> None:
        """Ask after the debounce window, unless the user keeps typing.

        Every keystroke cancels the pending timer, so only a real pause spends
        a request. Tab still means "ask now" for anyone who does not want to
        wait out the window.
        """
        if self._timer:
            self._timer.cancel()
        if not question or len(question) < MIN_QUESTION:
            return
        if question == self.query and self.status in ("ready", "thinking"):
            return
        self._timer = threading.Timer(self._debounce, self.submit, args=(question,))
        self._timer.daemon = True
        self._timer.start()

    def submit(self, question: str) -> None:
        """Ask right now."""
        if self._timer:
            self._timer.cancel()
        if not question:
            return
        if question == self.query and self.status == "ready":
            return
        with self._cv:
            self._queued = question
            self.status = "thinking"
            self.error = ""
            self._cv.notify()
        self._redraw()

    def clear(self) -> None:
        if self._timer:
            self._timer.cancel()
        with self._cv:
            self._queued = None
        self.query = self.suggestion = self.error = ""
        self.status = "idle"
        self.armed = False

    def ready_for(self, question: str) -> bool:
        return self.status == "ready" and self.query == question and bool(self.suggestion)

    # ---------- threads ----------
    def _worker(self) -> None:
        while True:
            with self._cv:
                while self._queued is None:
                    self._cv.wait()
                question, self._queued = self._queued, None
            try:
                command = self._translate(question)
                fresh = False
                with self._cv:
                    fresh = self._queued is None
                if not fresh:
                    continue  # a newer question arrived; drop this answer
                self.query = question
                self.suggestion = command
                self.status = "ready" if command else "error"
                self.error = "" if command else "model returned nothing"
                if command:
                    self.log.append((question, command))
            except Exception as exc:  # noqa: BLE001 - surface any backend failure
                self.query = question
                self.suggestion = ""
                self.status = "error"
                self.error = str(exc).splitlines()[0][:120]
            self._redraw()

    def _ticker(self) -> None:
        while True:
            time.sleep(0.12)
            if self.status == "thinking":
                self._redraw()

    def _redraw(self) -> None:
        app = self.app or get_app_or_none()
        if app is None:
            return
        try:
            app.invalidate()      # thread-safe in prompt_toolkit 3.x
        except Exception:         # pragma: no cover - prompt already closed
            pass


class DismissableSuggest(AutoSuggest):
    """The grey replay of a past command, which Esc can switch off.

    `cd D` offers `cd Documents` because that is what you ran last time. When
    you actually wanted `Desktop`, the replay is in the way: Tab takes it
    instead of opening the completion menu. Esc drops it for this line so Tab
    goes back to completing, and the next line starts fresh.
    """

    def __init__(self):
        self._inner = AutoSuggestFromHistory()
        self.enabled = True

    def get_suggestion(self, buffer, document):
        return self._inner.get_suggestion(buffer, document) if self.enabled else None


class ShellCompleter(Completer):
    """Tab completion the way a shell does it.

    The first word of a line is a command, everything after it is a path. That
    one rule covers almost every real completion: `doc<Tab>` should offer
    `docker`, `cat READ<Tab>` should offer `README.md`, and neither should ever
    offer the other.

    ponytail: no per-command argument completion (`git che<Tab>` -> `checkout`).
    That needs a spec per tool, which is what bash-completion is for; add it if
    the plain version turns out not to be enough.
    """

    def __init__(self, commands):
        self._commands = sorted(commands)
        self._paths = PathCompleter(expanduser=True)

    @staticmethod
    def _on_first_word(text: str) -> bool:
        before = text.lstrip()
        # after a pipe or separator the next word is a command again
        for sep in ("|", ";", "&&", "||"):
            before = before.rsplit(sep, 1)[-1]
        return " " not in before.strip() and not before.endswith(" ")

    def _path_completions(self, word, complete_event):
        """PathCompleter treats the whole line as one path, so give it the word.

        Without this, `cat READ<Tab>` asks it to complete a file literally named
        "cat READ" and it returns nothing.
        """
        return self._paths.get_completions(Document(word, len(word)), complete_event)

    def get_completions(self, document, complete_event):
        word = document.get_word_before_cursor(WORD=True)
        # a path typed where a command goes is still a path: ./run.sh, ~/bin/x
        if (not self._on_first_word(document.text_before_cursor)
                or word.startswith((".", "/", "~"))):
            yield from self._path_completions(word, complete_event)
            return
        for name in self._commands:
            if name.startswith(word):
                yield Completion(name, start_position=-len(word))


def short_cwd(width: int = 32) -> str:
    """`~/Desktop/obiobi`, trimmed from the left when it gets long."""
    cwd = os.getcwd()
    home = os.path.expanduser("~")
    if cwd == home:
        cwd = "~"
    elif cwd.startswith(home + os.sep):
        cwd = "~" + cwd[len(home):]
    return cwd if len(cwd) <= width else "…" + cwd[-(width - 1):]


def apply_to_buffer(buffer, text: str) -> None:
    """Replace the input line with `text` - the grey suggestion becomes solid."""
    buffer.text = text
    buffer.cursor_position = len(text)


def render_ghost(state: Suggester, question: str, width: int = 100) -> FormattedText:
    if state.status == "thinking":
        frame = SPINNER[int(time.time() * 8) % len(SPINNER)]
        return FormattedText([("class:ghost.pending", f"  {frame} thinking…")])
    if state.status == "error":
        return FormattedText([("class:ghost.error", f"  ! {state.error}")])
    if state.ready_for(question):
        cmd = state.suggestion
        if cmd.startswith("# cannot"):
            return FormattedText([("class:ghost.pending", "  no shell command for that")])
        verdict = screen(cmd)
        if verdict.blocked:
            return FormattedText([("class:ghost.error", f"  refused: {verdict.reason}")])

        if verdict.risky and state.armed:
            return FormattedText([
                ("class:ghost", f"  {cmd}"),
                ("class:ghost.warn", f"   ⚠ {verdict.reason} - [Tab] again to accept"),
            ])
        warn = f"   ⚠ {verdict.reason}" if verdict.risky else ""
        hint = "   [Tab][Tab]" if verdict.risky else "   [Tab]"
        room = max(20, width - len(warn) - len(hint) - 3)
        shown = cmd if len(cmd) <= room else cmd[: room - 1] + "…"
        parts = [("class:ghost", f"  {shown}")]
        if warn:
            parts.append(("class:ghost.warn", warn))
        if len(shown) + len(warn) + len(hint) + 2 <= width:
            parts.append(("class:hint", hint))
        return FormattedText(parts)
    return FormattedText([("", "")])


def all_commands() -> set:
    """Every executable on $PATH, including /usr/bin - `ls` must complete too.

    The index deliberately drops the base OS because the model gains nothing
    from it, but a person pressing Tab expects `ls` and `grep`. Re-scanning
    costs ~40 ms for ~1500 names, so it happens once per session.
    """
    from .index import path_executables
    return path_executables(user_only=False)


def build_session(cfg: Config, backend: Backend) -> tuple[PromptSession, Suggester]:
    state = Suggester(lambda q: translate(backend, cfg, q), cfg.debounce_ms)

    def question_of(text: str) -> str:
        return strip_prefix(text, cfg.prefixes) if is_ask(text, cfg.prefixes) else ""

    def ghost_line() -> FormattedText:
        """Runs on the UI thread during every render."""
        app = get_app_or_none()
        if app is None:
            return FormattedText([("", "")])
        buf = app.current_buffer
        try:
            width = app.output.get_size().columns
        except Exception:
            width = 100
        return render_ghost(state, question_of(buf.text), width)

    def has_ghost() -> bool:
        return state.status != "idle"

    kb = KeyBindings()

    @kb.add("tab")
    def _tab(event):
        buf = event.current_buffer
        q = question_of(buf.text)
        if not q:
            # 1. walking an open completion menu
            if buf.complete_state:
                buf.complete_next()
            # 2. the grey replay of a past command that starts the same way
            elif buf.suggestion and buf.suggestion.text:
                buf.insert_text(buf.suggestion.text)
            # 3. otherwise complete a command name or a path, like a shell.
            #    select_first inserts the candidate straight away - without it
            #    Tab only draws a menu and the line never actually completes.
            else:
                buf.start_completion(select_first=True)
            return
        if not state.ready_for(q):
            state.submit(q)                 # Tab also means "ask now"
            return
        cmd = state.suggestion
        if cmd.startswith("#") or screen(cmd).blocked:
            return
        # A risky command takes two deliberate presses. The first one only
        # arms it, so `rm`, `sudo` and friends cannot be taken by reflex.
        if screen(cmd).risky and not state.armed:
            state.armed = True
            state._redraw()
            return
        apply_to_buffer(buf, cmd)           # grey -> solid
        state.clear()

    @kb.add("enter")
    def _enter(event):
        buf = event.current_buffer
        # An open completion menu swallows Enter: it takes the highlighted item
        # and leaves the line sitting there. Running on the same keypress that
        # picked the completion means never getting to read what you picked.
        if buf.complete_state:
            # Whatever is highlighted is already in the buffer - cycling with
            # Tab writes it there. So Enter only has to drop the completion
            # state and leave the line alone. apply_completion() would revert
            # to the original text first and re-insert, which races the
            # completer that is still running in the background.
            buf.complete_state = None
            return
        q = question_of(buf.text)
        if not q:
            suggest.enabled = True          # next line starts fresh
            buf.validate_and_handle()       # a real command: run it
            return
        # Enter never accepts a suggestion - Tab is the only way to take one.
        # Before an answer exists it just means "ask now". Once one exists a
        # second Enter submits the question itself, so a suggestion you cannot
        # use (refused, or "# cannot") never traps you on the line.
        if state.ready_for(q) or state.status == "error":
            buf.validate_and_handle()
        else:
            state.submit(q)

    @kb.add("right")
    def _accept_suggestion(event):
        """End-of-line Right takes the grey replay, as fish and zsh do."""
        buf = event.current_buffer
        if buf.cursor_position == len(buf.text) and buf.suggestion and buf.suggestion.text:
            buf.insert_text(buf.suggestion.text)
        else:
            buf.cursor_right()

    @kb.add("c-g")            # unambiguous dismiss
    @kb.add("escape", eager=True)   # Esc also works on terminals that flush it
    def _dismiss(event):
        state.clear()
        # Disabling the provider only stops the *next* lookup; prompt_toolkit
        # keeps the last answer on the buffer, so clear that too or the grey
        # text stays on screen and Tab still takes it.
        suggest.enabled = False
        event.current_buffer.suggestion = None
        event.current_buffer.cancel_completion()

    @kb.add("c-l")
    def _clear(event):
        event.app.renderer.clear()

    def on_text_changed(buf) -> None:
        state.armed = False      # the two Tabs have to be consecutive
        q = question_of(buf.text)
        if q:
            state.schedule(q)
        elif state.status != "idle":
            state.clear()

    suggest = DismissableSuggest()

    def prompt_message() -> FormattedText:
        """Re-evaluated every render, so `cd` is visible immediately."""
        return FormattedText([
            ("class:prompt", "obi"),
            ("class:prompt.path", f" {short_cwd()}"),
            ("class:prompt.mark", " ❯ "),
        ])

    cfg_mod.DATA_DIR.mkdir(parents=True, exist_ok=True)
    session = PromptSession(
        message=prompt_message,
        rprompt=FormattedText([("class:rprompt", backend.label)]),
        key_bindings=kb,
        style=STYLE,
        history=ShellHistory(cfg.history_limit),
        auto_suggest=suggest,
        completer=ShellCompleter(all_commands()),
        # A floating menu costs 8 permanently reserved blank rows under the
        # prompt, whether or not anything is completing. Readline style prints
        # the candidates below the line instead - the way bash does it - so the
        # reservation drops to nothing.
        complete_style=CompleteStyle.READLINE_LIKE,
        reserve_space_for_menu=0,
        include_default_pygments_style=False,
        complete_while_typing=False,
    )

    # A dedicated row directly under the input. prompt_toolkit's own
    # `bottom_toolbar` is hidden whenever the renderer height is unknown (i.e.
    # terminals that don't answer cursor-position requests), which would make the
    # suggestion silently disappear - so the row is part of the layout instead.
    ghost_row = ConditionalContainer(
        Window(
            FormattedTextControl(ghost_line),
            height=1,
            dont_extend_height=True,
            style="class:ghost-row",
        ),
        filter=~is_done & Condition(has_ghost),
    )
    session.layout.container = HSplit([session.layout.container, ghost_row])

    session.default_buffer.on_text_changed += on_text_changed
    state.app = session.app
    return session, state
