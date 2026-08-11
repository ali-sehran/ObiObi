"""Tab completion: command names on the first word, paths everywhere else."""
import os
import tempfile
import unittest
from pathlib import Path

from prompt_toolkit.document import Document

from obiobi.ui import ShellCompleter

COMMANDS = {"ls", "lsof", "docker", "docker-compose", "grep", "git"}


class CompleterTest(unittest.TestCase):
    def setUp(self):
        self.c = ShellCompleter(COMMANDS)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name in ("README.md", "requirements.txt", "notes.txt"):
            (Path(self.tmp.name) / name).write_text("x")
        (Path(self.tmp.name) / "subdir").mkdir()
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)

    def complete(self, text):
        return [c.text for c in
                self.c.get_completions(Document(text, len(text)), None)]

    def test_first_word_completes_commands(self):
        self.assertEqual(sorted(self.complete("doc")), ["docker", "docker-compose"])

    def test_later_words_complete_paths_not_commands(self):
        """`cat g<Tab>` must not offer `grep`."""
        self.assertNotIn("grep", self.complete("cat g"))
        self.assertIn("EADME.md", self.complete("cat R"))

    def test_a_bare_argument_lists_the_directory(self):
        self.assertIn("README.md", self.complete("git "))

    def test_command_position_after_a_pipe(self):
        self.assertIn("grep", self.complete("ls | gre"))
        self.assertIn("grep", self.complete("ls && gre"))
        self.assertIn("grep", self.complete("ls; gre"))

    def test_a_relative_path_in_command_position_is_a_path(self):
        self.assertNotIn("docker", self.complete("./doc"))
        self.assertIn("otes.txt", self.complete("./n"))

    def test_no_match_yields_nothing(self):
        self.assertEqual(self.complete("zzzznope"), [])

    def test_prefix_is_replaced_not_appended(self):
        """start_position must cover the typed word, or Tab gives `docdocker`."""
        got = list(self.c.get_completions(Document("doc", 3), None))
        self.assertTrue(all(c.start_position == -3 for c in got), got)


if __name__ == "__main__":
    unittest.main()
