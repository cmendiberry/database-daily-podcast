"""
test_tts_generate.py - Tests for scripts/tts_generate.py

These tests do NOT require Kokoro model files or actual TTS execution.
They validate:
  - format_duration() helper
  - CLI argument validation (missing files, empty script)

The generate() function itself is integration-tested by the manual
generate_episode workflow in CI (which downloads the real model).

Run:
    pytest tests/test_tts_generate.py -v
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from tts_generate import format_duration


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------


class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == "0:00"

    def test_thirty_seconds(self):
        assert format_duration(30) == "0:30"

    def test_exactly_one_minute(self):
        assert format_duration(60) == "1:00"

    def test_five_minutes(self):
        assert format_duration(300) == "5:00"

    def test_five_minutes_twelve_seconds(self):
        assert format_duration(312) == "5:12"

    def test_nine_minutes_59_seconds(self):
        assert format_duration(599) == "9:59"

    def test_exactly_one_hour(self):
        assert format_duration(3600) == "1:00:00"

    def test_over_one_hour(self):
        assert format_duration(3661) == "1:01:01"

    def test_float_truncates(self):
        # 299.9 should truncate to 4:59, not round up to 5:00
        assert format_duration(299.9) == "4:59"

    def test_seconds_padded(self):
        # Single-digit seconds must be zero-padded
        result = format_duration(65)
        assert result == "1:05"


# ---------------------------------------------------------------------------
# CLI validation (no Kokoro required)
# ---------------------------------------------------------------------------


class TestCliValidation:
    """
    Confirm the script exits 1 with a clear error before ever touching Kokoro
    when given invalid inputs.
    """

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "tts_generate.py")] + list(args),
            capture_output=True,
            text=True,
        )

    def test_no_args_exits_nonzero(self):
        result = self._run()
        assert result.returncode != 0

    def test_missing_script_file_exits_1(self, tmp_path):
        result = self._run(
            "--script-file", str(tmp_path / "does_not_exist.txt"),
            "--output", str(tmp_path / "out.mp3"),
        )
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()

    def test_missing_model_exits_1(self, tmp_path):
        script = tmp_path / "script.txt"
        script.write_text("Hello, this is a test script.", encoding="utf-8")
        result = self._run(
            "--script-file", str(script),
            "--output", str(tmp_path / "out.mp3"),
            "--model", str(tmp_path / "no_model.onnx"),
            "--voices-bin", str(tmp_path / "no_voices.bin"),
        )
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()

    def test_missing_voices_exits_1(self, tmp_path):
        script = tmp_path / "script.txt"
        script.write_text("Hello, this is a test script.", encoding="utf-8")
        # Provide a fake model file (exists) but no voices file
        fake_model = tmp_path / "kokoro.onnx"
        fake_model.write_bytes(b"\x00" * 16)
        result = self._run(
            "--script-file", str(script),
            "--output", str(tmp_path / "out.mp3"),
            "--model", str(fake_model),
            "--voices-bin", str(tmp_path / "no_voices.bin"),
        )
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()

    def test_empty_script_exits_1(self, tmp_path):
        script = tmp_path / "empty.txt"
        script.write_text("   \n\n   \t  \n", encoding="utf-8")
        result = self._run(
            "--script-file", str(script),
            "--output", str(tmp_path / "out.mp3"),
        )
        assert result.returncode == 1
        assert "empty" in result.stderr.lower()
