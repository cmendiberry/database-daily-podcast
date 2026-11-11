"""
test_research_generate.py - Tests for scripts/research_generate.py

No API calls, no network requests, no TTS dependencies.

Covers:
  - HTML utilities: _clean_html, _extract_text
  - Title normalisation for dedup: _normalize_title
  - Feed keyword filter: _item_matches_keywords
  - Entry date parsing: _parse_entry_date
  - Script length validation: _validate_script_length (600–750 words)
  - Cross-episode deduplication: load_used_stories, is_duplicate
  - Source content sufficiency: is_sufficient_content
  - Primary source fetching failure / insufficient content: fetch_candidate_content
  - Output writing: write_outputs
  - Manual override (subprocess — no API key needed)
  - CLI validation
  - Aurora restriction: generic PostgreSQL/MySQL feeds excluded from SOURCES
  - DBA/DBRE audience boundary: editorial system prompt content
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
    EDITORIAL_SYSTEM_PROMPT,
    SCRIPT_MAX_WORDS,
    SCRIPT_MIN_WORDS,
    SOURCES,
    _clean_html,
    _extract_text,
    _item_matches_keywords,
    _normalize_title,
    _parse_entry_date,
    _validate_script_length,
    fetch_candidate_content,
    is_duplicate,
    is_sufficient_content,
    load_used_stories,
    write_outputs,
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
# _extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_removes_script_blocks(self):
        html = "<html><script>var x = 1;</script><p>Content here</p></html>"
        result = _extract_text(html)
        assert "var x" not in result
        assert "Content here" in result

    def test_removes_style_blocks(self):
        html = "<style>.foo { color: red }</style><p>Hello</p>"
        result = _extract_text(html)
        assert ".foo" not in result
        assert "Hello" in result

    def test_truncates_at_max_chars(self):
        html = "<p>" + "x" * 10000 + "</p>"
        result = _extract_text(html, max_chars=100)
        assert len(result) <= 100

    def test_strips_remaining_tags(self):
        html = "<div><h1>Title</h1><p>Body</p></div>"
        result = _extract_text(html)
        assert "<" not in result
        assert "Title" in result
        assert "Body" in result


# ---------------------------------------------------------------------------
# _normalize_title
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_lowercases(self):
        assert "aurora" in _normalize_title("AURORA PostgreSQL")

    def test_removes_punctuation(self):
        result = _normalize_title("Aurora PostgreSQL: New Version!")
        assert ":" not in result
        assert "!" not in result

    def test_removes_stop_words(self):
        result = _normalize_title("the new aurora feature is now available")
        tokens = result.split()
        assert "the" not in tokens
        assert "is" not in tokens
        assert "aurora" in tokens

    def test_collapses_whitespace(self):
        result = _normalize_title("  aurora   postgresql  ")
        assert "  " not in result
        assert result == result.strip()


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
# _validate_script_length
# ---------------------------------------------------------------------------


class TestValidateScriptLength:
    def test_exactly_min_valid(self):
        script = " ".join(["word"] * SCRIPT_MIN_WORDS)
        valid, count = _validate_script_length(script)
        assert valid is True
        assert count == SCRIPT_MIN_WORDS

    def test_exactly_max_valid(self):
        script = " ".join(["word"] * SCRIPT_MAX_WORDS)
        valid, count = _validate_script_length(script)
        assert valid is True
        assert count == SCRIPT_MAX_WORDS

    def test_one_below_min_invalid(self):
        script = " ".join(["word"] * (SCRIPT_MIN_WORDS - 1))
        valid, count = _validate_script_length(script)
        assert valid is False
        assert count == SCRIPT_MIN_WORDS - 1

    def test_one_above_max_invalid(self):
        script = " ".join(["word"] * (SCRIPT_MAX_WORDS + 1))
        valid, count = _validate_script_length(script)
        assert valid is False
        assert count == SCRIPT_MAX_WORDS + 1

    def test_mid_range_valid(self):
        mid = (SCRIPT_MIN_WORDS + SCRIPT_MAX_WORDS) // 2
        script = " ".join(["word"] * mid)
        valid, count = _validate_script_length(script)
        assert valid is True
        assert count == mid

    def test_empty_script_invalid(self):
        valid, count = _validate_script_length("")
        assert valid is False
        assert count == 0


# ---------------------------------------------------------------------------
# load_used_stories
# ---------------------------------------------------------------------------


class TestLoadUsedStories:
    def _make_sources(self, ep_dir: Path, stories: list) -> None:
        ep_dir.mkdir(parents=True, exist_ok=True)
        data = {"stories_selected": stories}
        (ep_dir / "sources.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_loads_urls_from_sources_json(self, tmp_path):
        self._make_sources(
            tmp_path / "2026-08-10",
            [{"url": "https://example.com/story", "title": "Test Story"}],
        )
        used = load_used_stories(tmp_path)
        assert "https://example.com/story" in used["urls"]

    def test_loads_normalized_titles(self, tmp_path):
        self._make_sources(
            tmp_path / "2026-08-10",
            [{"url": "https://example.com", "title": "Aurora PostgreSQL Released"}],
        )
        used = load_used_stories(tmp_path)
        assert len(used["normalized_titles"]) > 0

    def test_multiple_episodes_combined(self, tmp_path):
        self._make_sources(
            tmp_path / "2026-08-09",
            [{"url": "https://a.com", "title": "Story A"}],
        )
        self._make_sources(
            tmp_path / "2026-08-10",
            [{"url": "https://b.com", "title": "Story B"}],
        )
        used = load_used_stories(tmp_path)
        assert "https://a.com" in used["urls"]
        assert "https://b.com" in used["urls"]

    def test_missing_sources_json_skipped(self, tmp_path):
        (tmp_path / "2026-08-10").mkdir()  # No sources.json
        used = load_used_stories(tmp_path)
        assert len(used["urls"]) == 0

    def test_nonexistent_episodes_dir(self, tmp_path):
        used = load_used_stories(tmp_path / "nonexistent")
        assert used == {"urls": set(), "normalized_titles": set()}


# ---------------------------------------------------------------------------
# is_duplicate
# ---------------------------------------------------------------------------


class TestIsDuplicate:
    def test_exact_url_match(self):
        used = {"urls": {"https://example.com/story"}, "normalized_titles": set()}
        item = {"url": "https://example.com/story", "title": "New Story"}
        assert is_duplicate(item, used) is True

    def test_normalized_title_match(self):
        # Build the normalized title that _normalize_title would produce
        norm = _normalize_title("Aurora PostgreSQL Version Released")
        used = {"urls": set(), "normalized_titles": {norm}}
        item = {"url": "https://other.com/page", "title": "Aurora PostgreSQL Version Released"}
        assert is_duplicate(item, used) is True

    def test_no_match(self):
        used = {"urls": {"https://other.com"}, "normalized_titles": {"something else"}}
        item = {"url": "https://example.com/new", "title": "Aurora PostgreSQL New Feature"}
        assert is_duplicate(item, used) is False

    def test_empty_used_set(self):
        used = {"urls": set(), "normalized_titles": set()}
        item = {"url": "https://example.com", "title": "Any Story"}
        assert is_duplicate(item, used) is False

    def test_different_url_same_title_flagged(self):
        norm = _normalize_title("Aurora MySQL End of Life")
        used = {"urls": set(), "normalized_titles": {norm}}
        item = {"url": "https://completely-different.com", "title": "Aurora MySQL End of Life"}
        assert is_duplicate(item, used) is True


# ---------------------------------------------------------------------------
# is_sufficient_content
# ---------------------------------------------------------------------------


class TestIsSufficientContent:
    def test_none_is_insufficient(self):
        assert is_sufficient_content(None) is False

    def test_empty_string_is_insufficient(self):
        assert is_sufficient_content("") is False

    def test_short_content_is_insufficient(self):
        assert is_sufficient_content("too short") is False

    def test_sufficient_length_passes(self):
        assert is_sufficient_content("x" * 400) is True


# ---------------------------------------------------------------------------
# fetch_candidate_content (using pytest-mock)
# ---------------------------------------------------------------------------


class TestFetchCandidateContent:
    def _make_candidate(self, title="Test Story", url="https://example.com"):
        return {
            "title": title,
            "url": url,
            "summary": "summary",
            "published": "2026-08-10",
            "source": "AWS What's New",
        }

    def test_none_fetch_excludes_candidate(self, mocker):
        mocker.patch("research_generate.fetch_source_content", return_value=None)
        candidates = [self._make_candidate()]
        result = fetch_candidate_content(candidates)
        assert len(result) == 0

    def test_thin_content_excludes_candidate(self, mocker):
        mocker.patch("research_generate.fetch_source_content", return_value="short")
        candidates = [self._make_candidate()]
        result = fetch_candidate_content(candidates)
        assert len(result) == 0

    def test_sufficient_content_kept_with_full_content_key(self, mocker):
        mocker.patch(
            "research_generate.fetch_source_content", return_value="x" * 400
        )
        candidates = [self._make_candidate()]
        result = fetch_candidate_content(candidates)
        assert len(result) == 1
        assert "full_content" in result[0]
        assert result[0]["full_content"] == "x" * 400

    def test_mixed_keeps_only_sufficient(self, mocker):
        def side_effect(url, **kwargs):
            if "good" in url:
                return "x" * 400
            return None

        mocker.patch("research_generate.fetch_source_content", side_effect=side_effect)
        candidates = [
            self._make_candidate(url="https://good.com/a"),
            self._make_candidate(url="https://bad.com/b"),
        ]
        result = fetch_candidate_content(candidates)
        assert len(result) == 1
        assert result[0]["url"] == "https://good.com/a"


# ---------------------------------------------------------------------------
# write_outputs
# ---------------------------------------------------------------------------


class TestWriteOutputs:
    def _rd(self):
        return {"mode": "test", "sources_consulted": [], "stories_selected": [], "model": None}

    def test_creates_script_txt(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "Hello world script.", self._rd())
        assert (tmp_path / "script.txt").exists()

    def test_script_content_correct(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "Test script content.", self._rd())
        assert (tmp_path / "script.txt").read_text(encoding="utf-8") == "Test script content."

    def test_creates_sources_json(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "Script.", self._rd())
        assert (tmp_path / "sources.json").exists()

    def test_sources_json_valid(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "Script text here.", self._rd())
        data = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
        assert data["episode_date"] == "2026-08-11"
        assert "generated_at" in data
        assert "script_word_count" in data

    def test_word_count_correct(self, tmp_path):
        write_outputs(tmp_path, "2026-08-11", "one two three four five", self._rd())
        data = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
        assert data["script_word_count"] == 5

    def test_creates_output_dir_if_missing(self, tmp_path):
        out = tmp_path / "nested" / "dir"
        write_outputs(out, "2026-08-11", "Script.", self._rd())
        assert (out / "script.txt").exists()


# ---------------------------------------------------------------------------
# Manual override (subprocess — no API key or network needed)
# ---------------------------------------------------------------------------


class TestManualOverride:
    def _run(self, tmp_path, script_text):
        env = {**os.environ, "EPISODE_SCRIPT": script_text}
        env.pop("ANTHROPIC_API_KEY", None)
        return subprocess.run(
            [PYTHON, SCRIPT, "--date", "2026-08-11", "--output-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_exits_zero(self, tmp_path):
        assert self._run(tmp_path, "A" * 600).returncode == 0

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

    def test_short_script_accepted_in_manual_mode(self, tmp_path):
        """Manual override bypasses script-length validation."""
        result = self._run(tmp_path, "Short script.")
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# CLI validation (subprocess)
# ---------------------------------------------------------------------------


class TestCliValidation:
    def test_no_args_exits_nonzero(self):
        result = subprocess.run([PYTHON, SCRIPT], capture_output=True, text=True)
        assert result.returncode != 0

    def test_missing_api_key_exits_1(self, tmp_path):
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


# ---------------------------------------------------------------------------
# Aurora restriction — generic PostgreSQL/MySQL upstream feeds excluded
# ---------------------------------------------------------------------------


class TestAuroraRestriction:
    def test_no_generic_postgresql_org_feed(self):
        """postgresql.org news feed must not be in SOURCES."""
        for source in SOURCES:
            url = source.get("url", "")
            assert "postgresql.org" not in url, (
                f"Generic PostgreSQL.org feed '{url}' found in SOURCES. "
                "Aurora-relevant PostgreSQL news comes through AWS sources only."
            )

    def test_no_generic_mysql_news_feed(self):
        """Generic MySQL.com news feeds must not be in SOURCES."""
        for source in SOURCES:
            url = source.get("url", "")
            assert "dev.mysql.com/feeds" not in url, (
                f"Generic MySQL news feed '{url}' found in SOURCES."
            )

    def test_aws_sources_present(self):
        """AWS What's New and AWS Database Blog must be in SOURCES."""
        source_urls = [s["url"] for s in SOURCES]
        assert any("aws.amazon.com/about-aws/whats-new" in u for u in source_urls)
        assert any("aws.amazon.com/blogs/database" in u for u in source_urls)

    def test_editorial_prompt_contains_aurora_restriction(self):
        assert "AURORA RESTRICTION" in EDITORIAL_SYSTEM_PROMPT
        assert "aurora" in EDITORIAL_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# DBA/DBRE audience boundary — editorial prompt content
# ---------------------------------------------------------------------------


class TestDbaAudienceBoundary:
    def test_editorial_prompt_contains_developer_exclusion(self):
        assert "DEVELOPER EXCLUSION" in EDITORIAL_SYSTEM_PROMPT
        lower = EDITORIAL_SYSTEM_PROMPT.lower()
        assert "application developer" in lower or "developer" in lower

    def test_editorial_prompt_contains_grounding_rule(self):
        assert "GROUNDING RULE" in EDITORIAL_SYSTEM_PROMPT

    def test_editorial_prompt_lists_dba_topics(self):
        lower = EDITORIAL_SYSTEM_PROMPT.lower()
        for topic in ("upgrades", "patching", "security", "backup", "replication"):
            assert topic in lower, f"Expected DBA topic '{topic}' in editorial prompt"

    def test_editorial_prompt_mentions_source_content_restriction(self):
        lower = EDITORIAL_SYSTEM_PROMPT.lower()
        assert "source content" in lower or "primary source" in lower
