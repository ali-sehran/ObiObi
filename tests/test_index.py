"""The list of what is installed, and the shell-history integration."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obiobi import history as hist
from obiobi import index


class IndexTest(unittest.TestCase):
    def test_nothing_unknown_is_ever_executed(self):
        """The only binaries obiobi runs are the package managers it names.

        Running strangers to read their banner is what made
        `docker-credential-osxkeychain` raise a keychain prompt.
        """
        called = []

        def spy(cmd, **kw):
            called.append(cmd[0])
            return type("R", (), {"stdout": "", "returncode": 1})()

        with patch("subprocess.run", spy), patch("shutil.which", return_value="/x"):
            index.build()
        self.assertTrue(set(called) <= {"python3", "python", "npm", "brew"},
                        f"executed something unexpected: {called}")

    def test_system_directories_are_left_out(self):
        """Every machine has awk; only what the user installed is interesting."""
        self.assertTrue(index._is_system("/usr/bin"))
        self.assertTrue(index._is_system("/System/Cryptexes/App/usr/bin"))
        self.assertFalse(index._is_system("/opt/homebrew/bin"))
        self.assertFalse(index._is_system(str(Path.home() / ".local/bin")))

    def test_path_scan_finds_a_user_installed_binary(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "mytool"
            exe.write_text("#!/bin/sh\n")
            exe.chmod(0o755)
            with patch.dict(os.environ, {"PATH": d}):
                self.assertIn("mytool", index.path_executables())

    def test_packages_never_shadow_a_command(self):
        with patch.object(index, "path_executables", return_value={"pip"}), \
             patch.object(index, "python_packages", return_value={"pip", "numpy"}), \
             patch.object(index, "npm_packages", return_value=set()), \
             patch.object(index, "brew_packages", return_value=set()):
            built = index.build()
        self.assertIn("pip", built["commands"])
        self.assertNotIn("pip", built["packages"])
        self.assertIn("numpy", built["packages"])

    def test_prompt_lines_say_when_they_truncate(self):
        big = {"commands": [f"c{i}" for i in range(600)], "packages": []}
        line = index.prompt_lines(big, limit=500)[0]
        self.assertIn("and 100 more", line)

    def test_missing_index_is_not_an_error(self):
        with patch.object(index, "INDEX_FILE", Path("/nonexistent/tools.json")):
            self.assertEqual(index.load(), {"commands": [], "packages": []})
            self.assertEqual(index.prompt_lines(index.load()), [])

    def test_old_flat_index_still_loads(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "tools.json"
            f.write_text('{"df": "display free disk space"}')
            with patch.object(index, "INDEX_FILE", f):
                self.assertEqual(index.load()["commands"], ["df"])


class ShellHistoryTest(unittest.TestCase):
    def _with_history(self, name, contents):
        d = tempfile.mkdtemp()
        f = Path(d) / name
        f.write_text(contents)
        return patch.dict(os.environ, {"HISTFILE": str(f)}), f

    def test_reads_plain_bash_history(self):
        env, f = self._with_history(".bash_history", "ls -l\ngit status\n")
        with env:
            self.assertEqual(hist.read(), ["ls -l", "git status"])

    def test_reads_zsh_extended_history(self):
        env, f = self._with_history(
            ".zsh_history", ": 1699999999:0;git status\n: 1700000000:0;docker ps\n")
        with env:
            self.assertEqual(hist.read(), ["git status", "docker ps"])

    def test_appends_in_the_format_the_file_already_uses(self):
        env, f = self._with_history(".zsh_history", ": 1699999999:0;git status\n")
        with env:
            hist.append("docker ps")
        last = f.read_text().splitlines()[-1]
        self.assertTrue(last.startswith(": "), last)
        self.assertTrue(last.endswith(";docker ps"), last)

        env, f = self._with_history(".bash_history", "ls -l\n")
        with env:
            hist.append("docker ps")
        self.assertEqual(f.read_text().splitlines()[-1], "docker ps")

    def test_meta_commands_stay_out_of_the_shell_history(self):
        env, f = self._with_history(".bash_history", "ls\n")
        with env:
            store = hist.ShellHistory()
            store.store_string("??ask: how much disk")
            store.store_string(":help")
            store.store_string("df -h")
        self.assertEqual(f.read_text().splitlines(), ["ls", "df -h"])

    def test_newest_first_for_the_inline_suggester(self):
        env, f = self._with_history(".bash_history", "old\nnewer\nnewest\n")
        with env:
            self.assertEqual(list(hist.ShellHistory().load_history_strings())[0],
                             "newest")

    def test_limit_keeps_the_newest(self):
        env, f = self._with_history(".bash_history", "".join(f"cmd{i}\n" for i in range(100)))
        with env:
            self.assertEqual(hist.read(3), ["cmd97", "cmd98", "cmd99"])

    def test_unreadable_history_is_not_an_error(self):
        with patch.dict(os.environ, {"HISTFILE": "/nonexistent/dir/hist"}):
            self.assertEqual(hist.read(), [])
            hist.append("df -h")          # must not raise

    def test_docs_file_records_every_question(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "session.md"
            hist.write_docs([("how much disk", "df -h"),
                             ("running containers", "docker ps")], out)
            text = out.read_text()
        self.assertIn("how much disk", text)
        self.assertIn("df -h", text)
        self.assertIn("docker ps", text)



class ApiKeyStorageTest(unittest.TestCase):
    """The key gets a file of its own so config.json stays shareable."""

    def setUp(self):
        from obiobi import config as cfg_mod
        self.cfg_mod = cfg_mod
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = Path(self._tmp.name)
        for name, value in (("CONFIG_DIR", d), ("CONFIG_FILE", d / "config.json"),
                            ("CREDENTIALS_FILE", d / "credentials")):
            p = patch.object(cfg_mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for var in ("OBIOBI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
            os.environ.pop(var, None)

    def test_saved_key_is_found_without_any_env_var(self):
        cfg = self.cfg_mod.Config(api_key_env="OPENROUTER_API_KEY")
        self.assertEqual(cfg.resolve_api_key(), "")
        self.cfg_mod.store_api_key("sk-or-v1-abc123")
        self.assertEqual(cfg.resolve_api_key(), "sk-or-v1-abc123")
        self.assertIn("credentials", cfg.key_source())

    def test_key_file_is_private(self):
        path = self.cfg_mod.store_api_key("sk-secret")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_environment_wins_over_the_saved_key(self):
        self.cfg_mod.store_api_key("sk-from-file")
        os.environ["OPENROUTER_API_KEY"] = "sk-from-env"
        cfg = self.cfg_mod.Config(api_key_env="OPENROUTER_API_KEY")
        self.assertEqual(cfg.resolve_api_key(), "sk-from-env")
        self.assertEqual(cfg.key_source(), "$OPENROUTER_API_KEY")

    def test_config_json_never_contains_the_key(self):
        self.cfg_mod.store_api_key("sk-or-v1-supersecret")
        cfg = self.cfg_mod.Config(api_key_env="OPENROUTER_API_KEY")
        written = cfg.save().read_text()
        self.assertNotIn("supersecret", written)

    def test_forgetting_a_key_that_is_not_there_is_not_an_error(self):
        self.assertFalse(self.cfg_mod.forget_api_key())
        self.cfg_mod.store_api_key("sk-x")
        self.assertTrue(self.cfg_mod.forget_api_key())

    def test_mask_never_shows_the_middle(self):
        masked = self.cfg_mod.mask("sk-or-v1-0123456789abcdef0123456789abcdef")
        self.assertNotIn("89abcdef0123", masked)
        self.assertTrue(masked.startswith("sk-or-v"))


class HistoryNoiseTest(unittest.TestCase):
    """What the inline grey suggestion is allowed to replay."""

    def _hist(self, contents):
        d = tempfile.mkdtemp()
        f = Path(d) / ".bash_history"
        f.write_text(contents)
        return patch.dict(os.environ, {"HISTFILE": str(f)})

    def test_questions_never_come_back_as_suggestions(self):
        """`??ask: ...` in a shell history is a question, not a command."""
        with self._hist("ls -l\n??ask: delete everything on the root filesystem\n"
                        "??ask\ndocker ps\n"):
            self.assertEqual(hist.read(), ["ls -l", "docker ps"])

    def test_blocked_commands_never_come_back_as_suggestions(self):
        with self._hist("ls -l\nrm -rf /\nmkfs.ext4 /dev/sda1\ngit status\n"):
            self.assertEqual(hist.read(), ["ls -l", "git status"])

    def test_risky_but_legitimate_commands_are_kept(self):
        """sudo apt install is real history; only blocked lines are dropped."""
        with self._hist("sudo apt install jq\ngit push --force\n"):
            self.assertEqual(len(hist.read()), 2)

    def test_raw_read_keeps_everything(self):
        with self._hist("ls\n??ask: x\nrm -rf /\n"):
            self.assertEqual(len(hist.read(raw=True)), 3)

    def test_meta_commands_are_filtered_on_read_too(self):
        with self._hist("ls\nhistory 3\n??docs\ndf -h\n"):
            self.assertEqual(hist.read(), ["ls", "df -h"])


class PromptToolListTest(unittest.TestCase):
    def test_the_list_is_not_presented_as_exhaustive(self):
        """Excluding /usr/bin and saying "nothing else exists" makes the model
        answer "# cannot" to anything needing ls or df."""
        from obiobi.config import Config
        from obiobi.nl2cmd import build_prompt
        with patch("obiobi.index.load",
                   return_value={"commands": ["docker"], "packages": []}):
            prompt = build_prompt(Config(use_index=True))
        self.assertIn("docker", prompt)
        self.assertNotIn("Do not use anything else", prompt)
        self.assertIn("ls", prompt)          # the POSIX baseline is stated


class HistoryNumberingTest(unittest.TestCase):
    """`history` mirrors the file, and says which numbers these are."""

    def _hist(self, contents):
        d = tempfile.mkdtemp()
        f = Path(d) / ".bash_history"
        f.write_text(contents)
        return patch.dict(os.environ, {"HISTFILE": str(f)})

    def test_numbers_are_file_positions_with_no_gaps(self):
        """Skipping filtered lines but keeping their numbers left holes."""
        with self._hist("ls\n??ask: something\nrm -rf /\ndf -h\n"):
            rows = hist.numbered()
        self.assertEqual([n for n, _ in rows], [1, 2, 3, 4])

    def test_history_shows_everything_the_shell_would(self):
        """The noise filter is for the suggester, not for `history`."""
        with self._hist("ls\n??ask: something\nrm -rf /\ndf -h\n"):
            shown = [c for _, c in hist.numbered()]
            replayable = hist.read()
        self.assertEqual(len(shown), 4)
        self.assertEqual(replayable, ["ls", "df -h"])   # suggester still filters

    def test_limit_takes_the_newest_and_keeps_their_numbers(self):
        with self._hist("".join(f"cmd{i}\n" for i in range(1, 21))):
            rows = hist.numbered(3)
        self.assertEqual(rows, [(18, "cmd18"), (19, "cmd19"), (20, "cmd20")])

    def test_empty_history_is_not_an_error(self):
        with self._hist(""):
            self.assertEqual(hist.numbered(5), [])


class LiveSyncRecipeTest(unittest.TestCase):
    """The rc line obiobi tells people to add has to be the correct one."""

    def test_bash_recipe_reloads_rather_than_reading_incrementally(self):
        """`history -a; history -n` silently drops entries.

        -a advances bash's read offset past anything another process appended
        since its last read, so a command obiobi wrote while bash sat at its
        prompt is skipped for good. Verified against a live bash: the line was
        in the file and missing from `history`, with bash's own line duplicated
        in its place.
        """
        recipe = hist.LIVE_SYNC["bash"]
        self.assertIn("history -a", recipe)
        self.assertIn("history -c", recipe)
        self.assertIn("history -r", recipe)
        self.assertNotIn("history -n", recipe)
        self.assertLess(recipe.index("history -c"), recipe.index("history -r"),
                        "must clear before re-reading, or entries double up")

    def test_zsh_recipe_shares_history(self):
        self.assertIn("SHARE_HISTORY", hist.LIVE_SYNC["zsh"])

    def test_detection_matches_the_recipe_it_recommends(self):
        """doctor must not report 'live-shared' for the broken ordering."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rc = Path(d) / ".bashrc"
            with patch.dict(os.environ, {"SHELL": "/bin/bash"}), \
                 patch.object(hist, "RC_FILES", {"bash": (str(rc),)}):
                rc.write_text("PROMPT_COMMAND='history -a; history -n'\n")
                self.assertFalse(hist.live_sync_enabled(), "stale recipe passed")
                rc.write_text(hist.LIVE_SYNC["bash"] + "\n")
                self.assertTrue(hist.live_sync_enabled())


class ShellArgvTest(unittest.TestCase):
    """Commands must run in a shell that knows your profile."""

    def setUp(self):
        from obiobi import executor
        self.executor = executor
        from obiobi.config import Config
        self.Config = Config

    def test_a_login_shell_is_used_so_profile_functions_exist(self):
        """`bash -c` reads no profile at all - a function defined in
        ~/.bash_profile simply does not exist and the command dies."""
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            argv = self.executor.shell_argv("skey", self.Config())
        self.assertEqual(argv[0], "/bin/bash")
        self.assertEqual(argv[1], "-lc")
        self.assertIn("skey", argv[2])

    def test_bash_gets_alias_expansion(self):
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            argv = self.executor.shell_argv("ll", self.Config())
        self.assertIn("expand_aliases", argv[2])

    def test_non_bash_shells_get_no_bash_builtins(self):
        with patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            argv = self.executor.shell_argv("skey", self.Config())
        self.assertEqual(argv, ["/bin/zsh", "-lc", "skey"])

    def test_login_shell_can_be_turned_off(self):
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            argv = self.executor.shell_argv("ls", self.Config(login_shell=False))
        self.assertEqual(argv, ["/bin/bash", "-c", "ls"])


class MultiLineHistoryTest(unittest.TestCase):
    def _hist(self, contents):
        d = tempfile.mkdtemp()
        f = Path(d) / ".bash_history"
        f.write_text(contents)
        return patch.dict(os.environ, {"HISTFILE": str(f)})

    def test_a_continued_command_is_one_entry(self):
        """`docker run \\` alone is not a command worth replaying."""
        with self._hist("ls\ndocker run \\\n  --rm alpine\ndf -h\n"):
            self.assertEqual(hist.read(),
                             ["ls", "docker run   --rm alpine", "df -h"])

    def test_blank_lines_are_not_commands(self):
        with self._hist("ls\n\n\ndf -h\n"):
            self.assertEqual(hist.read(), ["ls", "df -h"])

if __name__ == "__main__":
    unittest.main()
