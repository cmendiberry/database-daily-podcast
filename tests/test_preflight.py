"""
test_preflight.py - Tests for scripts/preflight.py

Tests:
  - Date resolution: supplied input vs Buenos Aires fallback
  - Schedule event + existing episode  -> skip=true, exit 0
  - Schedule event + no episode        -> skip=false, exit 0
  - Dispatch event + existing episode  -> exit 1
  - Dispatch event + no episode        -> skip=false, exit 0
  - GITHUB_OUTPUT is written correctly
  - EPISODES_DIR override is respected
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PREFLIGHT = str(REPO_ROOT / "scripts" / "preflight.py")
PYTHON = sys.executable


def run_preflight(env_overrides: dict, episodes_dir: Path = None) -> subprocess.CompletedProcess:
    """Run preflight.py in a subprocess with the given env overrides."""
    env = {**os.environ, **env_overrides}
    if episodes_dir is not None:
        env["EPISODES_DIR"] = str(episodes_dir)
    # Remove GITHUB_OUTPUT so we don't corrupt the real one
    env.pop("GITHUB_OUTPUT", None)
    return subprocess.run(
        [PYTHON, PREFLIGHT],
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Date resolution (unit tests — import preflight directly)
# ---------------------------------------------------------------------------


class TestResolveDate:
    def setup_method(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))

    def test_returns_supplied_date(self):
        from preflight import resolve_date
        assert resolve_date("2026-08-11") == "2026-08-11"

    def test_strips_whitespace(self):
        from preflight import resolve_date
        assert resolve_date("  2026-08-11  ") == "2026-08-11"

    def test_empty_returns_today_format(self):
        from preflight import resolve_date
        result = resolve_date("")
        assert len(result) == 10
        assert result[4] == "-" and result[7] == "-"


# ---------------------------------------------------------------------------
# Schedule event: episode already exists -> skip, exit 0
# ---------------------------------------------------------------------------


class TestScheduleEpisodeExists:
    def test_exits_zero(self, tmp_path):
        (tmp_path / "2026-08-11").mkdir()
        result = run_preflight(
            {"EVENT_NAME": "schedule", "EPISODE_DATE": "2026-08-11"},
            episodes_dir=tmp_path,
        )
        assert result.returncode == 0

    def test_stdout_mentions_skipped(self, tmp_path):
        (tmp_path / "2026-08-11").mkdir()
        result = run_preflight(
            {"EVENT_NAME": "schedule", "EPISODE_DATE": "2026-08-11"},
            episodes_dir=tmp_path,
        )
        assert "skipped" in result.stdout.lower() or "already exists" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Schedule event: episode does not exist -> proceed, exit 0
# ---------------------------------------------------------------------------


class TestScheduleEpisodeMissing:
    def test_exits_zero(self, tmp_path):
        result = run_preflight(
            {"EVENT_NAME": "schedule", "EPISODE_DATE": "2026-08-11"},
            episodes_dir=tmp_path,
        )
        assert result.returncode == 0

    def test_stdout_mentions_proceeding(self, tmp_path):
        result = run_preflight(
            {"EVENT_NAME": "schedule", "EPISODE_DATE": "2026-08-11"},
            episodes_dir=tmp_path,
        )
        assert "proceeding" in result.stdout.lower() or "ok" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Dispatch event: episode already exists -> exit 1
# ---------------------------------------------------------------------------


class TestDispatchEpisodeExists:
    def test_exits_one(self, tmp_path):
        (tmp_path / "2026-08-11").mkdir()
        result = run_preflight(
            {"EVENT_NAME": "workflow_dispatch", "EPISODE_DATE": "2026-08-11"},
            episodes_dir=tmp_path,
        )
        assert result.returncode == 1

    def test_stderr_mentions_error(self, tmp_path):
        (tmp_path / "2026-08-11").mkdir()
        result = run_preflight(
            {"EVENT_NAME": "workflow_dispatch", "EPISODE_DATE": "2026-08-11"},
            episodes_dir=tmp_path,
        )
        assert "error" in result.stderr.lower() or "already exists" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Dispatch event: episode does not exist -> exit 0
# ---------------------------------------------------------------------------


class TestDispatchEpisodeMissing:
    def test_exits_zero(self, tmp_path):
        result = run_preflight(
            {"EVENT_NAME": "workflow_dispatch", "EPISODE_DATE": "2026-08-11"},
            episodes_dir=tmp_path,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# GITHUB_OUTPUT is written correctly
# ---------------------------------------------------------------------------


class TestGithubOutput:
    def test_skip_false_written_when_episode_missing(self, tmp_path):
        output_file = tmp_path / "github_output.txt"
        env = {
            "EVENT_NAME": "workflow_dispatch",
            "EPISODE_DATE": "2026-08-12",
            "EPISODES_DIR": str(tmp_path),
            "GITHUB_OUTPUT": str(output_file),
            "GITHUB_STEP_SUMMARY": "",
        }
        env.pop("GITHUB_STEP_SUMMARY", None)
        result = subprocess.run(
            [PYTHON, PREFLIGHT],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )
        assert result.returncode == 0
        content = output_file.read_text(encoding="utf-8")
        assert "skip=false" in content
        assert "episode_date=2026-08-12" in content

    def test_skip_true_written_for_schedule_with_existing_episode(self, tmp_path):
        (tmp_path / "2026-08-12").mkdir()
        output_file = tmp_path / "github_output.txt"
        env = {
            "EVENT_NAME": "schedule",
            "EPISODE_DATE": "2026-08-12",
            "EPISODES_DIR": str(tmp_path),
            "GITHUB_OUTPUT": str(output_file),
        }
        result = subprocess.run(
            [PYTHON, PREFLIGHT],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )
        assert result.returncode == 0
        content = output_file.read_text(encoding="utf-8")
        assert "skip=true" in content
        assert "episode_date=2026-08-12" in content
