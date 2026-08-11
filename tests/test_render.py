import unittest

from obiobi.ui import render_ghost


def fake_state(status, suggestion="", query="q", error="", armed=False):
    s = type("S", (), {})()
    s.status, s.suggestion, s.query, s.error = status, suggestion, query, error
    s.armed = armed
    s.ready_for = lambda q: status == "ready" and q == query and bool(suggestion)
    return s


def text_of(frags):
    return "".join(t for _, t in frags)


def styles_of(frags):
    return " ".join(s for s, _ in frags)


class TestRenderGhost(unittest.TestCase):
    def test_ready_shows_command_in_ghost_style(self):
        frags = render_ghost(fake_state("ready", "python3 -m pip list"), "q")
        self.assertIn("python3 -m pip list", text_of(frags))
        self.assertIn("[Tab]", text_of(frags))
        self.assertIn("class:ghost", styles_of(frags))

    def test_risky_command_is_flagged_and_asks_for_two_tabs(self):
        frags = render_ghost(fake_state("ready", "sudo rm -rf ./build"), "q")
        self.assertIn("class:ghost.warn", styles_of(frags))
        self.assertIn("[Tab][Tab]", text_of(frags))

    def test_armed_risky_command_says_press_tab_again(self):
        frags = render_ghost(fake_state("ready", "sudo rm -rf ./build", armed=True), "q")
        self.assertIn("again to accept", text_of(frags))
        self.assertIn("class:ghost.warn", styles_of(frags))

    def test_safe_command_asks_for_one_tab_only(self):
        frags = render_ghost(fake_state("ready", "df -h"), "q")
        self.assertIn("[Tab]", text_of(frags))
        self.assertNotIn("[Tab][Tab]", text_of(frags))

    def test_blocked_command_is_refused(self):
        self.assertIn("refused", text_of(render_ghost(fake_state("ready", "rm -rf /"), "q")))

    def test_thinking_and_error(self):
        self.assertIn("thinking", text_of(render_ghost(fake_state("thinking"), "q")))
        self.assertIn("boom", text_of(render_ghost(fake_state("error", error="boom"), "q")))

    def test_stale_suggestion_is_not_shown(self):
        # suggestion belongs to another question
        self.assertEqual(text_of(render_ghost(fake_state("ready", "ls", query="old"), "new")), "")

    def test_cannot_is_explained(self):
        self.assertIn("no shell command",
                      text_of(render_ghost(fake_state("ready", "# cannot"), "q")))


if __name__ == "__main__":
    unittest.main()
