"""Exercises the OpenAI-compatible backend against a real local HTTP server."""
import json
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

from obiobi.backends import BackendError, OpenAIBackend, build_backend
from obiobi.config import Config
from obiobi.nl2cmd import translate

RECEIVED = []
REPLY = {"content": "python3 -m pip list"}
STATUS = {"code": 200}
BODY_ERROR = {"message": ""}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RECEIVED.append({"path": self.path, "body": body,
                         "auth": self.headers.get("Authorization")})
        if BODY_ERROR["message"]:
            # OpenRouter answers HTTP 200 with an error body when the shared
            # free pool is exhausted - the HTTPError path never sees it
            payload = json.dumps({"error": {"message": BODY_ERROR["message"],
                                            "code": 429}}).encode()
            self.send_response(200)
        elif STATUS["code"] != 200:
            payload = json.dumps({"error": {"message": "nope"}}).encode()
            self.send_response(STATUS["code"])
        else:
            payload = json.dumps({
                "choices": [{"message": {"role": "assistant",
                                         "content": REPLY["content"]}}]
            }).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


class TestOpenAICompatible(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        RECEIVED.clear()
        STATUS["code"] = 200
        BODY_ERROR["message"] = ""
        REPLY["content"] = "python3 -m pip list"
        self.cfg = Config(
            backend="api",
            api_base=f"http://127.0.0.1:{self.port}/v1",
            api_model="my-local-model",
            api_key_env="OBIOBI_TEST_KEY_UNSET",
        )

    def test_round_trip(self):
        backend = OpenAIBackend(self.cfg)
        out = translate(backend, self.cfg, "check all installed modules and packages")
        self.assertEqual(out, "python3 -m pip list")

        sent = RECEIVED[0]
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertEqual(sent["body"]["model"], "my-local-model")
        self.assertEqual([m["role"] for m in sent["body"]["messages"]],
                         ["system", "user"])
        self.assertIn("ONE shell command", sent["body"]["messages"][0]["content"])
        self.assertEqual(sent["body"]["messages"][1]["content"],
                         "check all installed modules and packages")

    def test_localhost_needs_no_key(self):
        self.assertEqual(OpenAIBackend(self.cfg).label, "api:my-local-model")
        self.assertEqual(OpenAIBackend(self.cfg).remote_host, "")

    def test_remote_without_key_is_rejected(self):
        from unittest.mock import patch

        from obiobi import config as cfg_mod
        cfg = Config(backend="api", api_base="https://api.openai.com/v1",
                     api_key_env="OBIOBI_TEST_KEY_UNSET")
        # a key saved by `config --set-key` would satisfy this, so hide it
        with patch.object(cfg_mod, "CREDENTIALS_FILE", Path("/nonexistent/creds")):
            with self.assertRaises(BackendError) as ctx:
                OpenAIBackend(cfg)
        self.assertIn("no API key", str(ctx.exception))

    def _ask_stdout(self, reply):
        """What the shell hook would capture on stdout, plus the exit code."""
        import contextlib, io
        from obiobi.cli import cmd_ask
        REPLY["content"] = reply
        args = type("A", (), {"question": ["do", "the", "thing"], "run": False})()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cmd_ask(self.cfg, args)
        return out.getvalue().strip(), rc

    def test_refusal_never_reaches_stdout(self):
        """'# cannot' on stdout would land in the user's history as a command."""
        for reply in ("# cannot", "  # cannot do that", ""):
            stdout, rc = self._ask_stdout(reply)
            self.assertEqual(stdout, "", f"{reply!r} leaked to stdout")
            self.assertEqual(rc, 1, reply)

    def test_blocked_command_never_reaches_stdout(self):
        stdout, rc = self._ask_stdout("rm -rf /")
        self.assertEqual(stdout, "")
        self.assertEqual(rc, 1)

    def test_risky_command_is_offered_with_the_warning_on_stderr(self):
        stdout, rc = self._ask_stdout("sudo systemsetup -getremotelogin")
        self.assertEqual(stdout, "sudo systemsetup -getremotelogin")
        self.assertEqual(rc, 0)

    def test_error_in_a_200_body_is_reported_readably(self):
        """The upstream pool answers 200 with an error; don't dump the dict."""
        from obiobi.backends import short_error
        BODY_ERROR["message"] = ("Upstream error from Nvidia: ResourceExhausted: "
                                 "Worker local total request limit reached")
        with self.assertRaises(BackendError) as ctx:
            OpenAIBackend(self.cfg).generate("sys", "hi")
        message = str(ctx.exception)
        self.assertNotIn("{", message, f"raw dict leaked: {message}")
        self.assertNotIn("unexpected response", message)
        self.assertIn("busy", message)
        self.assertEqual(message, short_error(BODY_ERROR["message"]))

    def test_a_busy_pool_is_retried_once(self):
        BODY_ERROR["message"] = "ResourceExhausted: please retry shortly"
        with self.assertRaises(BackendError):
            OpenAIBackend(self.cfg).generate("sys", "hi")
        self.assertEqual(len(RECEIVED), 2, "a transient failure should be retried")

    def test_a_real_error_is_not_retried(self):
        BODY_ERROR["message"] = 'model "nope" does not exist'
        with self.assertRaises(BackendError) as ctx:
            OpenAIBackend(self.cfg).generate("sys", "hi")
        self.assertEqual(len(RECEIVED), 1, "a permanent error must not be retried")
        self.assertIn("does not exist", str(ctx.exception))

    def test_a_transient_failure_that_clears_returns_the_answer(self):
        BODY_ERROR["message"] = "temporarily rate-limited upstream"
        original = Handler.do_POST

        def clear_after_first(handler):
            if RECEIVED:
                BODY_ERROR["message"] = ""
            original(handler)

        Handler.do_POST = clear_after_first
        try:
            out = OpenAIBackend(self.cfg).generate("sys", "hi")
        finally:
            Handler.do_POST = original
        self.assertEqual(out, "python3 -m pip list")

    def test_ssl_context_has_certs(self):
        """An empty CA store means every https backend dies with a verify error."""
        from obiobi.config import ssl_context
        ctx = ssl_context()
        self.assertTrue(ctx.get_ca_certs(), "no CA bundle found for https requests")
        self.assertTrue(ctx.check_hostname)

    def test_key_is_sent_as_bearer(self):
        import os
        os.environ["OBIOBI_API_KEY"] = "sk-test-123"
        try:
            OpenAIBackend(self.cfg).generate("sys", "hi")
        finally:
            del os.environ["OBIOBI_API_KEY"]
        self.assertEqual(RECEIVED[0]["auth"], "Bearer sk-test-123")

    def test_http_error_is_explained(self):
        STATUS["code"] = 401
        with self.assertRaises(BackendError) as ctx:
            OpenAIBackend(self.cfg).generate("sys", "hi")
        self.assertIn("bad or missing API key", str(ctx.exception))

    def test_markdown_reply_is_sanitised(self):
        REPLY["content"] = "Sure!\n```bash\ndf -h\n```"
        self.assertEqual(translate(OpenAIBackend(self.cfg), self.cfg, "disk space"),
                         "df -h")

    def test_bad_base_url(self):
        cfg = Config(backend="api", api_base="api.openai.com/v1")
        with self.assertRaises(BackendError):
            OpenAIBackend(cfg)

    def test_missing_base_url(self):
        with self.assertRaises(BackendError):
            OpenAIBackend(Config(backend="api"))

    def test_auto_prefers_configured_endpoint(self):
        cfg = Config(backend="auto", api_base=f"http://127.0.0.1:{self.port}/v1")
        self.assertEqual(build_backend(cfg).name, "api")

    def test_auto_falls_back_when_unconfigured(self):
        self.assertEqual(build_backend(Config(backend="auto")).name, "heuristic")



class RefusalRetryTest(unittest.TestCase):
    """A random '# cannot' from a small model should not reach the user."""

    class Flaky:
        """Refuses the first time, answers the second."""
        name = label = "flaky"
        fallback_from = []

        def __init__(self, replies):
            self.replies = list(replies)
            self.calls = 0

        def generate(self, system, user):
            self.calls += 1
            return self.replies.pop(0) if self.replies else "# cannot"

    def test_a_random_refusal_is_retried_once(self):
        backend = self.Flaky(["# cannot", "ls -l"])
        self.assertEqual(translate(backend, Config(), "list the files"), "ls -l")
        self.assertEqual(backend.calls, 2)

    def test_a_real_refusal_survives_the_retry(self):
        backend = self.Flaky(["# cannot", "# cannot"])
        self.assertEqual(translate(backend, Config(), "tell me a joke"), "# cannot")
        self.assertEqual(backend.calls, 2)

    def test_a_good_answer_is_never_asked_twice(self):
        backend = self.Flaky(["df -h"])
        self.assertEqual(translate(backend, Config(), "disk space"), "df -h")
        self.assertEqual(backend.calls, 1)

    def test_retry_can_be_turned_off(self):
        backend = self.Flaky(["# cannot", "ls -l"])
        out = translate(backend, Config(retry_refusals=False), "list the files")
        self.assertEqual(out, "# cannot")
        self.assertEqual(backend.calls, 1)

if __name__ == "__main__":
    unittest.main()
