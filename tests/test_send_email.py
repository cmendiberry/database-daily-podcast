"""
test_send_email.py - Tests for scripts/send_email.py

No network access — urllib.request.urlopen is replaced with a fake
in-process stand-in for the send() tests. build_payload() is tested
directly with no I/O at all. time.sleep is monkeypatched so retry tests
run instantly.

Covers:
  - build_payload: from/to/subject/html/text fields
  - send: POSTs once and succeeds on a 2xx response
  - send: retries on transient failure and succeeds within MAX_ATTEMPTS
  - send: raises the last error once MAX_ATTEMPTS is exhausted
  - send: a 4xx/5xx response raises with the response body included
  - CLI: missing RESEND_API_KEY / EMAIL_TO exits 1
  - CLI: RESEND_FROM defaults when unset
"""

import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "send_email.py")
PYTHON = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from send_email import DEFAULT_FROM, build_payload, send


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_fields(self):
        payload = build_payload("Subject line", "from@example.com", "to@example.com", "<p>hi</p>", "hi")
        assert payload["subject"] == "Subject line"
        assert payload["from"] == "from@example.com"
        assert payload["to"] == ["to@example.com"]
        assert payload["html"] == "<p>hi</p>"
        assert payload["text"] == "hi"


# ---------------------------------------------------------------------------
# send (fake urlopen, no network)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, body: bytes = b'{"id":"abc"}'):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class FakeUrlopenSuccessAfter:
    """Stand-in for urllib.request.urlopen: fails fail_count times, then succeeds."""

    def __init__(self, fail_count: int):
        self.fail_count = fail_count
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        if self.fail_count > 0:
            self.fail_count -= 1
            raise OSError("Connection reset")
        return FakeResponse()


def _always_fail_urlopen(request, timeout=None):
    raise OSError("Connection reset")


def _http_error_urlopen(request, timeout=None):
    raise urllib.error.HTTPError(
        url="https://api.resend.com/emails",
        code=422,
        msg="Unprocessable Entity",
        hdrs=None,
        fp=__import__("io").BytesIO(b'{"message":"invalid from address"}'),
    )


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr("send_email.time.sleep", lambda seconds: None)


class TestSend:
    def test_sends_successfully(self, monkeypatch):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(request)
            return FakeResponse()

        monkeypatch.setattr("send_email.urllib.request.urlopen", fake_urlopen)
        payload = build_payload("S", "a@example.com", "b@example.com", "<p>hi</p>", "hi")

        send(payload, "test-api-key")

        assert len(calls) == 1
        req = calls[0]
        assert req.full_url == "https://api.resend.com/emails"
        assert req.get_header("Authorization") == "Bearer test-api-key"
        assert json.loads(req.data.decode("utf-8")) == payload

    def test_retries_and_succeeds_after_transient_failure(self, monkeypatch):
        fake = FakeUrlopenSuccessAfter(fail_count=1)
        monkeypatch.setattr("send_email.urllib.request.urlopen", fake)
        payload = build_payload("S", "a@example.com", "b@example.com", "<p>hi</p>", "hi")

        send(payload, "test-api-key")

        assert len(fake.calls) == 2

    def test_raises_after_exhausting_retries(self, monkeypatch):
        monkeypatch.setattr("send_email.urllib.request.urlopen", _always_fail_urlopen)
        payload = build_payload("S", "a@example.com", "b@example.com", "<p>hi</p>", "hi")

        with pytest.raises(OSError, match="Connection reset"):
            send(payload, "test-api-key")

    def test_http_error_includes_response_body(self, monkeypatch):
        monkeypatch.setattr("send_email.urllib.request.urlopen", _http_error_urlopen)
        payload = build_payload("S", "a@example.com", "b@example.com", "<p>hi</p>", "hi")

        with pytest.raises(RuntimeError, match="invalid from address"):
            send(payload, "test-api-key")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_cli(env_overrides: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    html_file = tmp_path / "episode.html"
    script_file = tmp_path / "script.txt"
    html_file.write_text("<p>hi</p>", encoding="utf-8")
    script_file.write_text("hi", encoding="utf-8")

    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [
            PYTHON,
            SCRIPT,
            "--html-file",
            str(html_file),
            "--script-file",
            str(script_file),
            "--subject",
            "Test subject",
        ],
        env=env,
        capture_output=True,
        text=True,
    )


class TestCLI:
    def test_missing_credentials_exits_1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("EMAIL_TO", raising=False)
        result = run_cli({"RESEND_API_KEY": "", "EMAIL_TO": ""}, tmp_path)
        assert result.returncode == 1
        assert "RESEND_API_KEY" in result.stderr

    def test_default_from_constant(self):
        assert "@" in DEFAULT_FROM
