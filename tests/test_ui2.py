"""Drives the real prompt with piped keystrokes: ghost text -> Tab -> Enter.

The prompt reads and writes the user's real shell history, so every test here
redirects HISTFILE to a throwaway file first. Without that, running the suite
appends `echo hello` and `sudo rm -rf ...` to whoever's ~/.bash_history.
"""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from obiobi.backends import HeuristicBackend
from obiobi.config import Config
from obiobi.safety import screen
from obiobi.ui import build_session

ASK = "??ask: check all installed modules and packages"
TAB, ENTER, CTRL_G, CTRL_U = "\t", "\r", "\x07", "\x15"


class FixedBackend(HeuristicBackend):
    """Always answers the same thing, so a test can pick the safety verdict."""

    def __init__(self, command):
        super().__init__()
        self._command = command

    def generate(self, system, user):
        return self._command


def drive(script, backend=None, timeout=20):
    """`script(send, state)` runs on a worker thread while the prompt is live."""
    cfg = Config(debounce_ms=150)
    box = {}
    with create_pipe_input() as pipe:
        with create_app_session(input=pipe, output=DummyOutput()):
            session, state = build_session(cfg, backend or HeuristicBackend())

            def send(text, wait=0.25):
                pipe.send_text(text)
                time.sleep(wait)

            def guarded():
                # a bare thread swallows the traceback and the test then fails
                # with a confusing KeyError instead of the real error
                try:
                    script(send, state)
                except BaseException as exc:      # noqa: BLE001
                    box["script_error"] = exc
                    pipe.send_text("\x03\x04")   # let the prompt finish

            thread = threading.Thread(target=guarded, daemon=True)
            thread.start()
            box["accepted"] = session.prompt()
            box["state"] = state
            # a script still sending after the prompt returned leaks into the
            # next test and shows up as a confusing KeyError there
            thread.join(timeout=5)
    if "script_error" in box:
        raise box["script_error"]
    return box


class TestGhostFlow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = patch.dict(os.environ,
                         {"HISTFILE": str(Path(self._tmp.name) / "history")})
        env.start()
        self.addCleanup(env.stop)
    def test_ghost_appears_then_tab_solidifies_then_enter_runs(self):
        seen = {}

        def script(send, state):
            send(ASK, wait=0.6)             # debounce fires, suggestion arrives
            seen["status"] = state.status
            seen["ghost"] = state.suggestion
            send(TAB)                       # grey -> solid
            seen["after_tab"] = state.status
            send(ENTER)                     # run it

        out = drive(script)
        self.assertEqual(seen["status"], "ready")
        self.assertIn("pip list", seen["ghost"])
        self.assertEqual(seen["after_tab"], "idle")      # ghost consumed
        self.assertIn("pip list", out["accepted"])       # the line that got submitted
        self.assertNotIn("??ask", out["accepted"])

    def test_tab_before_debounce_forces_generation(self):
        def script(send, state):
            send(ASK, wait=0.02)            # no time for the debounce
            send(TAB, wait=0.6)             # Tab = ask now
            send(TAB)                       # accept
            send(ENTER)

        self.assertIn("pip list", drive(script)["accepted"])

    def test_enter_asks_but_never_accepts(self):
        """Enter must not behave like Tab - only Tab takes a suggestion."""
        seen = {}

        def script(send, state):
            send(ASK, wait=0.02)
            send(ENTER, wait=0.7)           # asks now, but leaves the line alone
            seen["status"] = state.status
            seen["buffer"] = state.suggestion
            send(TAB, wait=0.3)             # this is what accepts
            send(ENTER)

        out = drive(script)
        self.assertEqual(seen["status"], "ready")
        self.assertIn("pip list", seen["buffer"])
        self.assertIn("pip list", out["accepted"])

    def test_risky_suggestion_needs_two_tabs(self):
        risky = "sudo rm -rf /tmp/build-cache"
        self.assertTrue(screen(risky).risky)
        seen = {}

        def script(send, state):
            send(ASK, wait=0.7)
            send(TAB, wait=0.3)             # first Tab only arms it
            seen["armed"] = state.armed
            seen["buffer_untouched"] = state.status
            send(TAB, wait=0.3)             # second Tab accepts
            seen["after_two"] = state.status
            send(ENTER)

        out = drive(script, backend=FixedBackend(risky))
        self.assertTrue(seen["armed"], "first Tab should arm, not accept")
        self.assertEqual(seen["buffer_untouched"], "ready")   # not consumed yet
        self.assertEqual(seen["after_two"], "idle")
        self.assertEqual(out["accepted"], risky)

    def test_editing_disarms_a_risky_suggestion(self):
        seen = {}

        def script(send, state):
            send(ASK, wait=0.7)
            send(TAB, wait=0.3)
            seen["armed"] = state.armed
            send("x", wait=0.3)             # any edit cancels the arming
            seen["after_edit"] = state.armed
            send(CTRL_U)
            send("echo ok")
            send(ENTER)

        out = drive(script, backend=FixedBackend("sudo rm -rf /tmp/build-cache"))
        self.assertTrue(seen["armed"])
        self.assertFalse(seen["after_edit"], "typing must cancel the first Tab")
        self.assertEqual(out["accepted"], "echo ok")

    def test_safe_suggestion_still_takes_one_tab(self):
        def script(send, state):
            send(ASK, wait=0.6)
            send(TAB, wait=0.25)
            send(ENTER)

        self.assertIn("pip list", drive(script)["accepted"])

    def _in_a_dir_with(self, filename):
        """cwd with one known file, so completion has a deterministic answer."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        (Path(d.name) / filename).write_text("x")
        cwd = os.getcwd()
        os.chdir(d.name)
        self.addCleanup(os.chdir, cwd)

    def test_tab_actually_inserts_the_completion(self):
        """Tab must complete the word, not just draw a menu beside it."""
        self._in_a_dir_with("zzz-unique-name.txt")

        def script(send, state):
            send("cat zzz-uni", wait=0.3)
            send(TAB, wait=0.5)
            send(ENTER, wait=0.4)       # takes the highlighted item, must NOT run
            send(ENTER, wait=0.3)       # now it runs

        self.assertEqual(drive(script)["accepted"], "cat zzz-unique-name.txt")

    def test_first_enter_only_closes_the_menu(self):
        """Picking from the menu and running must be two separate keypresses."""
        self._in_a_dir_with("zzz-unique-name.txt")
        seen = {}

        def script(send, state):
            send("cat zzz-uni", wait=0.3)
            send(TAB, wait=0.5)
            send(ENTER, wait=0.5)
            seen["not_submitted_yet"] = True
            send(ENTER, wait=0.3)

        out = drive(script)
        self.assertTrue(seen["not_submitted_yet"])
        self.assertEqual(out["accepted"], "cat zzz-unique-name.txt")

    def test_escape_drops_the_history_replay_so_tab_can_complete(self):
        """`cd D` replays `cd Documents`; Esc must free Tab to offer Desktop."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for name in ("Documents", "Desktop"):
            (Path(d.name) / name).mkdir()
        cwd = os.getcwd()
        os.chdir(d.name)
        self.addCleanup(os.chdir, cwd)
        Path(os.environ["HISTFILE"]).write_text("cd Documents\n")

        seen = {}

        def script(send, state):
            send("cd D", wait=0.4)
            send(CTRL_G, wait=0.3)      # same handler as Esc, survives a pipe
            send(TAB, wait=0.4)         # must complete, not replay
            send(ENTER, wait=0.4)       # take the completion
            send(ENTER, wait=0.3)

        out = drive(script)
        seen["accepted"] = out["accepted"]
        self.assertTrue(out["accepted"].startswith("cd D"), out["accepted"])
        self.assertNotEqual(out["accepted"], "cd Documents",
                            "Esc did not stop the replay")

    def test_plain_command_is_never_touched(self):
        def script(send, state):
            send("echo hello")
            send(ENTER)

        out = drive(script)
        self.assertEqual(out["accepted"], "echo hello")
        self.assertEqual(out["state"].status, "idle")

    def test_ctrl_g_dismisses_the_ghost(self):
        seen = {}

        def script(send, state):
            send(ASK, wait=0.6)
            seen["before"] = state.status
            send(CTRL_G)
            seen["after"] = state.status
            send(CTRL_U)                    # clear the line
            send("echo ok")
            send(ENTER)

        out = drive(script)
        self.assertEqual(seen["before"], "ready")
        self.assertEqual(seen["after"], "idle")
        self.assertEqual(out["accepted"], "echo ok")

    def test_editing_the_question_replaces_the_suggestion(self):
        seen = {}

        def script(send, state):
            send(ASK, wait=0.6)
            seen["first"] = state.suggestion
            send(CTRL_U)
            send("??ask: how much disk space is left", wait=0.6)
            seen["second"] = state.suggestion
            send(TAB)
            send(ENTER)

        out = drive(script)
        self.assertIn("pip list", seen["first"])
        self.assertIn("df -h", seen["second"])
        self.assertEqual(out["accepted"], "df -h")



class CompletionCyclingTest(unittest.TestCase):
    """Tab cycles; Enter keeps whatever is on the line.

    Each case runs in its own app session because prompt_toolkit's completer
    runs as a background task - reusing a session across cases lets one case's
    task settle into the next one's buffer.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        for name in ("aaa.txt", "bbb.txt", "ccc.txt"):
            (Path(self.dir.name) / name).write_text("x")
        hist = Path(self.dir.name) / "hist"
        hist.write_text("")
        env = patch.dict(os.environ, {"HISTFILE": str(hist)})
        env.start()
        self.addCleanup(env.stop)
        cwd = os.getcwd()
        os.chdir(self.dir.name)
        self.addCleanup(os.chdir, cwd)

    def test_each_tab_moves_to_the_next_candidate(self):
        seen = []

        def script(send, state):
            buf = state.app.current_buffer
            send("cat ", wait=0.5)
            for _ in range(3):
                send(TAB, wait=0.5)
                seen.append(buf.text)
            send(ENTER, wait=0.4)       # keeps the line, closes completion
            send(ENTER, wait=0.3)       # runs it

        out = drive(script)
        self.assertEqual(seen, ["cat aaa.txt", "cat bbb.txt", "cat ccc.txt"])
        self.assertEqual(out["accepted"], "cat ccc.txt",
                         "Enter must keep the candidate Tab landed on")

if __name__ == "__main__":
    unittest.main()
