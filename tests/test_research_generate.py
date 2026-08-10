"""
test_research_generate.py - Tests for scripts/research_generate.py

Tests cover:
  - Manual script override (EPISODE_SCRIPT set) — no API key or network needed
  - Output file creation and content
  - sources.json structure and mode field
  - CLI validation: missing API key exits 1, no args exits non-zero
  - Feed utility functions: _clean_html, _item_matches_keywords, _parse_entry_date
  - write_outputs produces correct files

No API calls or network requests are made in this test suite.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "research_generate.py")
PYTHON = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from research_generate import (
    _clean_html,
    _item_matches_keywords,
    _parse_entry_date,
    write_outputs,
    MIN_SCRIPT_WORDS,
)


# ---------------------------------------------------------------------------
# _clean_html
# ---------------------------------------------------------------------------


class TestCleanHtml:
    def test_strips_tags(self):
        assert _clean_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_collapses_whitespace(self):
        assert _clean_html("  foo   bar  ") == "foo bar"

    def test_empty_string(self):
        assert _clean_html("") == ""

    def test_no_tags(self):
        assert _clean_html("plain text") == "plain text"


# ---------------------------------------------------------------------------
# _item_matches_keywords
# ---------------------------------------------------------------------------


class TestItemMatchesKeywords:
    def test_no_keywords_always_matches(self):
        entry = {"title": "Anything", "summary": "stuff"}
        assert _item_matches_keywords(entry, []) is True

    def test_keyword_in_title(self):
        entry = {"title": "Aurora PostgreSQL 16.3 released", "summary": ""}
        assert _item_matches_keywords(entry, ["aurora"]) is True

    def test_keyword_in_summary(self):
        entry = {"title": "New release", "summary": "Aurora MySQL 3.07 is now available"}
        assert _item_matches_keywords(entry, ["aurora"]) is True

    def test_no_match(self):
        entry = {"title": "Python 3.14 beta", "summary": "New language features"}
        assert _item_matches_keywords(entry, ["aurora", "rds", "sql server"]) is False

    def test_case_insensitive(self):
        entry = {"title": "AURORA release", "summary": ""}
        assert _item_matches_keywords(entry, ["aurora"]) is True


# ---------------------------------------------------------------------------
# _parse_entry_date
# ---------------------------------------------------------------------------


class TestParseEntryDate:
    def test_returns_none_for_empty_entry(self):
        entry = SimpleNamespace()
        assert _parse_entry_date(entry) is None

    def test_parses_published_parsed(self):
        entry = SimpleNamespace(published_parsed=(2026, 8, 10, 12, 0, 0, 0, 0, 0))
        result = _parse_entry_date(entry)
        assert result is not None
        assert result.year == 2026
        assert result.month == 8
        assert result.day == 10

    def test_falls_back_to_updated_parsed(self):
        entry = SimpleNamespace(updated_parsed=(2026, 7, 1, 0, 0, 0, 0, 0, 0))
        result = _parse_entry_date(entry)
        assert result is not None
        assert result.year == 2026
        assert result.month == 7

    def test_published_parsed_takes_priority(self):
        entry = SimpleNamespace(
            published_parsed=(2026, 8, 10, 0, 0, 0, 0, 0, 0),
            updated_parsed=(2026, 1, 1, 0, 0, 0, 0, 0, 0),
        )
        result = _parse_entry_date(entry)
        assert result.month == 8


# ---------------------------------------------------------------------------
# write_outputs
# ---------------------------------------------------------------------------


class TestWriteOutputs:
    def test_creates_script_txt(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "Hello world script.", {"mode": "test", "sources_consulted": [], "stories_selected": [], "model": None})
        assert (tmp_path / "script.txt").exists()

    def test_script_content_correct(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "Test script content.", {"mode": "test", "sources_consulted": [], "stories_selected": [], "model": None})
        content = (tmp_path / "script.txt").read_text(encoding="utf-8")
        assert content == "Test script content."

    def test_creates_sources_json(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "Script.", {"mode": "test", "sources_consulted": [], "stories_selected": [], "model": None})
        assert (tmp_path / "sources.json").exists()

    def test_sources_json_valid(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "Script text here.", {"mode": "test", "sources_consulted": [], "stories_selected": [], "model": None})
        data = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
        assert data["episode_date"] == "2026-08-11"
        assert "generated_at" in data
        assert "script_word_count" in data

    def test_word_count_in_sources(self, tmp_path):
        script = "one two three four five"
        write_outputs(tmp_path, "2026-08-11", script, {"mode": "test", "sources_consulted": [], "stories_selected": [], "model": None})
        data = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
        assert data["script_word_count"] == 5

    def test_creates_output_dir_if_missing(self, tmp_path):
        out = tmp_path / "nested" / "dir"
        write_outputs(out, "2026-08-11", "Script.", {"mode": "test", "sources_consulted": [], "stories_selected": [], "model": None})
        assert (out / "script.txt").exists()


# ---------------------------------------------------------------------------
# Manual override path (subprocess — no API key needed)
# ---------------------------------------------------------------------------


class TestManualOverride:
    def _run(self, tmp_path, script_text):
        env = {
            **os.environ,
            "EPISODE_SCRIPT": script_text,
        }
        env.pop("ANTHROPIC_API_KEY", None)
        return subprocess.run(
            [PYTHON, SCRIPT, "--date", "2026-08-11", "--output-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_exits_zero(self, tmp_path):
        result = self._run(tmp_path, "A" * 600)
        assert result.returncode == 0

    def test_creates_script_txt(self, tmp_path):
        self._run(tmp_path, "Hello world script text.")
        assert (tmp_path / "script.txt").exists()

    def test_script_content_matches(self, tmp_path):
        self._run(tmp_path, "My custom script content.")
        content = (tmp_path / "script.txt").read_text(encoding="utf-8")
        assert content == "My custom script content."

    def test_creates_sources_json(self, tmp_path):
        self._run(tmp_path, "Hello world.")
        assert (tmp_path / "sources.json").exists()

    def test_sources_mode_is_manual(self, tmp_path):
        self._run(tmp_path, "Hello world.")
        data = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
        assert data["mode"] == "manual_override"

    def test_sources_model_is_none(self, tmp_path):
        self._run(tmp_path, "Hello world.")
        data = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
        assert data["model"] is None


# ---------------------------------------------------------------------------
# CLI validation (subprocess)
# ---------------------------------------------------------------------------


class TestCliValidation:
    def test_no_args_exits_nonzero(self):
        result = subprocess.run(
            [PYTHON, SCRIPT],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_missing_api_key_exits_1(self, tmp_path):
        """No EPISODE_SCRIPT and no ANTHROPIC_API_KEY must exit 1."""
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        env.pop("EPISODE_SCRIPT", None)
        result = subprocess.run(
            [PYTHON, SCRIPT, "--date", "2026-08-11", "--output-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 1
        assert "ANTHROPIC_API_KEY" in result.stderr
