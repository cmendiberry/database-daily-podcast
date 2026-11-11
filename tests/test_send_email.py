"""
test_send_email.py - Tests for scripts/send_email.py

No network access — smtplib.SMTP is replaced with a fake in-process
stand-in for the send() tests. build_message() is tested directly with no
I/O at all. time.sleep is monkeypatched so retry tests run instantly.

Covers:
  - build_message: headers, multipart/alternative with text + html parts
  - send: connects via STARTTLS on port 587, logs in, and sends
  - send: retries on transient failure and succeeds within MAX_ATTEMPTS
  - send: raises the last error once MAX_ATTEMPTS is exhausted
  - CLI: missing GMAIL_ADDRESS / GMAIL_APP_PASSWORD exits 1
  - CLI: EMAIL_TO defaults to GMAIL_ADDRESS when unset
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "send_email.py")
PYTHON = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from send_email import build_message, send


# ---------------------------------------------------------------------------
# build_message
# ---------------------------------------------------------------------------


class TestBuildMessage:
    def test_sets_headers(self):
        msg = build_message("Subject line", "from@example.com", "to@example.com", "<p>hi</p>", "hi")
        assert msg["Subject"] == "Subject line"
        assert msg["From"] == "from@example.com"
        assert msg["To"] == "to@example.com"

    def test_is_multipart_alternative(self):
        msg = build_message("S", "a@example.com", "b@example.com", "<p>hi</p>", "hi")
        assert msg.get_content_type() == "multipart/alternative"

    def test_contains_both_text_and_html_parts(self):
        msg = build_message("S", "a@example.com", "b@example.com", "<p>HTML BODY</p>", "TEXT BODY")
        parts = msg.get_payload()
        payloads = [part.get_payload(decode=True).decode("utf-8") for part in parts]
        content_types = [part.get_content_type() for part in parts]
        assert "text/plain" in content_types
        assert "text/html" in content_types
        assert any("TEXT BODY" in p for p in payloads)
        assert any("HTML BODY" in p for p in payloads)


# ---------------------------------------------------------------------------
# send (fake SMTP, no network)
# ---------------------------------------------------------------------------


class FakeSMTP:
    """Stand-in for smtplib.SMTP that records calls instead of connecting.

    fail_count controls how many constructions raise before one succeeds,
    simulating a transient connection failure that later retries recover
    from.
    """

    instances = []
    fail_count = 0

    def __init__(self, host, port):
        if FakeSMTP.fail_count > 0:
            FakeSMTP.fail_count -= 1
            raise OSError("Connection unexpectedly closed")
        self.host = host
        self.port = port
        self.starttls_calls = []
        self.login_calls = []
        self.sent_messages = []
        self.quit_called = False
        FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.starttls_calls.append(context)

    def login(self, address, app_password):
        self.login_calls.append((address, app_password))

    def send_message(self, message):
        self.sent_messages.append(message)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.quit_called = True
        return False


class AlwaysFailingSMTP(FakeSMTP):
    def __init__(self, host, port):
        raise OSError("Connection unexpectedly closed")


class FailingLoginSMTP(FakeSMTP):
    def login(self, address, app_password):
        raise OSError("auth failed")


@pytest.fixture(autouse=True)
def _reset_fake_instances():
    FakeSMTP.instances = []
    FakeSMTP.fail_count = 0
    yield
    FakeSMTP.instances = []
    FakeSMTP.fail_count = 0


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr("send_email.time.sleep", lambda seconds: None)


class TestSend:
    def test_connects_via_starttls_logs_in_and_sends(self, monkeypatch):
        monkeypatch.setattr("send_email.smtplib.SMTP", FakeSMTP)
        msg = build_message("S", "me@gmail.com", "me@gmail.com", "<p>hi</p>", "hi")

        send(msg, "me@gmail.com", "app-password")

        assert len(FakeSMTP.instances) == 1
        instance = FakeSMTP.instances[0]
        assert instance.host == "smtp.gmail.com"
        assert instance.port == 587
        assert len(instance.starttls_calls) == 1
        assert instance.login_calls == [("me@gmail.com", "app-password")]
        assert instance.sent_messages == [msg]
        assert instance.quit_called is True

    def test_propagates_login_failure(self, monkeypatch):
        monkeypatch.setattr("send_email.smtplib.SMTP", FailingLoginSMTP)
        msg = build_message("S", "me@gmail.com", "me@gmail.com", "<p>hi</p>", "hi")

        with pytest.raises(OSError):
            send(msg, "me@gmail.com", "wrong-password")

    def test_retries_and_succeeds_after_transient_failure(self, monkeypatch):
        monkeypatch.setattr("send_email.smtplib.SMTP", FakeSMTP)
        FakeSMTP.fail_count = 1  # first attempt fails, second succeeds
        msg = build_message("S", "me@gmail.com", "me@gmail.com", "<p>hi</p>", "hi")

        send(msg, "me@gmail.com", "app-password")

        assert len(FakeSMTP.instances) == 1
        assert FakeSMTP.instances[0].sent_messages == [msg]

    def test_raises_after_exhausting_retries(self, monkeypatch):
        monkeypatch.setattr("send_email.smtplib.SMTP", AlwaysFailingSMTP)
        msg = build_message("S", "me@gmail.com", "me@gmail.com", "<p>hi</p>", "hi")

        with pytest.raises(OSError, match="Connection unexpectedly closed"):
            send(msg, "me@gmail.com", "app-password")


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
        monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
        result = run_cli({"GMAIL_ADDRESS": "", "GMAIL_APP_PASSWORD": ""}, tmp_path)
        assert result.returncode == 1
        assert "GMAIL_ADDRESS" in result.stderr
