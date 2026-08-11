"""The assisted setup: `obiobi config --reset`."""
import unittest
from unittest.mock import patch

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from obiobi import config as cfg_mod
from obiobi import wizard
from obiobi.config import Config

TAB, ENTER = "\t", "\r"


def answer(keys, **kw):
    with create_pipe_input() as pipe:
        with create_app_session(input=pipe, output=DummyOutput()):
            pipe.send_text(keys)
            return wizard.ask(**kw)


class AskTest(unittest.TestCase):
    def test_enter_alone_takes_the_recommendation(self):
        self.assertEqual(answer(ENTER, label="provider", default="openrouter"), "openrouter")

    def test_tab_fills_in_the_recommendation(self):
        """`just tab should auto fill those recommended values`."""
        self.assertEqual(
            answer(TAB + ENTER, label="provider", default="openrouter",
                   options=["openai", "openrouter", "groq"]),
            "openrouter")

    def test_typing_replaces_rather_than_appends(self):
        """A pre-filled line welds the typed answer onto the default."""
        self.assertEqual(
            answer("groq" + ENTER, label="provider", default="openrouter",
                   options=["openrouter", "groq"]),
            "groq")

    def test_the_recommendation_is_offered_before_the_alternatives(self):
        """Tab must land on the recommended value, not on alphabetical first."""
        from prompt_toolkit.completion import WordCompleter
        seen = {}
        real = WordCompleter.__init__

        def spy(self, words, **kw):
            seen["words"] = list(words)
            real(self, words, **kw)

        with patch.object(WordCompleter, "__init__", spy):
            answer(ENTER, label="p", default="openrouter",
                   options=["groq", "openai", "openrouter"])
        self.assertEqual(seen["words"][0], "openrouter")
        self.assertNotIn("openrouter", seen["words"][1:], "recommendation duplicated")


class PresetTest(unittest.TestCase):
    def test_every_hosted_preset_is_complete_and_https(self):
        for name, (base, model, env, needs_key) in wizard.HOSTED.items():
            self.assertTrue(base.startswith("https://"), name)
            self.assertTrue(model and env.isupper(), name)
            self.assertTrue(needs_key, name)

    def test_every_local_server_preset_is_loopback(self):
        for name, (base, _model) in wizard.LOCAL_SERVER.items():
            self.assertTrue("127.0.0.1" in base or "localhost" in base, name)

    def test_gguf_is_not_offered(self):
        """Compiling llama-cpp and fetching gigabytes is not a setup step."""
        blob = " ".join(wizard.HOSTED) + " " + " ".join(wizard.LOCAL_SERVER)
        self.assertNotIn("gguf", blob.lower())
        self.assertNotIn("llama-cpp", blob.lower())


class RelevantFieldsTest(unittest.TestCase):
    def test_gguf_is_hidden_on_an_api_backend(self):
        shown = cfg_mod.relevant_fields(Config(backend="api"))
        self.assertNotIn("gguf_url", shown)
        self.assertNotIn("gguf_path", shown)
        self.assertNotIn("ollama_model", shown)
        self.assertIn("api_base", shown)

    def test_api_settings_are_hidden_on_ollama(self):
        shown = cfg_mod.relevant_fields(Config(backend="ollama"))
        self.assertIn("ollama_model", shown)
        self.assertNotIn("api_base", shown)
        self.assertNotIn("gguf_url", shown)

    def test_shared_settings_always_show(self):
        for backend in ("api", "ollama", "llama-cpp", "heuristic"):
            shown = cfg_mod.relevant_fields(Config(backend=backend))
            for always in ("debounce_ms", "confirm_risky", "use_index", "prefixes"):
                self.assertIn(always, shown, backend)

    def test_auto_shows_everything(self):
        shown = cfg_mod.relevant_fields(Config(backend="auto"))
        self.assertIn("gguf_url", shown)
        self.assertIn("api_base", shown)
        self.assertIn("ollama_model", shown)


if __name__ == "__main__":
    unittest.main()
