"""
test_generate_email_html.py - Tests for scripts/generate_email_html.py

No network, no API calls, no secrets required.

Covers:
  - render_html includes title/date/digest body/stories
  - HTML escaping of untrusted story titles and URLs (XSS safety)
  - Zero-stories edge case
  - Missing optional story fields handled gracefully
  - Paragraph splitting helper
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_email_html import _split_paragraphs, render_html


# ---------------------------------------------------------------------------
# _split_paragraphs
# ---------------------------------------------------------------------------


class TestSplitParagraphs:
    def test_respects_existing_blank_line_breaks(self):
        text = "First paragraph.\n\nSecond paragraph."
        assert _split_paragraphs(text) == ["First paragraph.", "Second paragraph."]

    def test_groups_sentences_when_no_blank_lines(self):
        text = "One. Two. Three. Four. Five. Six."
        result = _split_paragraphs(text)
        assert len(result) == 2
        assert result[0] == "One. Two. Three."
        assert result[1] == "Four. Five. Six."

    def test_empty_text_returns_empty_list(self):
        assert _split_paragraphs("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert _split_paragraphs("   \n\n  ") == []


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------


STORY = {
    "title": "Aurora PostgreSQL 18 now generally available",
    "url": "https://aws.amazon.com/blogs/database/aurora-pg-18",
    "source": "AWS Database Blog",
    "published": "2026-08-10",
    "category": "Aurora PostgreSQL",
    "dba_relevance": "DBAs should plan upgrade testing before the next maintenance window.",
}


class TestRenderHtml:
    def test_includes_episode_title_and_date(self):
        out = render_html("My Digest Title", "2026-08-11", "Hello world.", [])
        assert "My Digest Title" in out
        assert "Tuesday, August 11, 2026" in out

    def test_includes_digest_body(self):
        out = render_html("Title", "2026-08-11", "This is the digest body.", [])
        assert "This is the digest body." in out

    def test_includes_story_card_fields(self):
        out = render_html("Title", "2026-08-11", "Body.", [STORY])
        assert "Aurora PostgreSQL 18 now generally available" in out
        assert "https://aws.amazon.com/blogs/database/aurora-pg-18" in out
        assert "AWS Database Blog" in out
        assert "DBAs should plan upgrade testing" in out
        assert "Aurora PostgreSQL" in out

    def test_zero_stories_does_not_crash_and_omits_section(self):
        out = render_html("Title", "2026-08-11", "Body.", [])
        assert "Today&#x27;s stories" not in out and "Today's stories" not in out

    def test_unknown_category_falls_back_to_default_color(self):
        story = dict(STORY, category="Something Unexpected")
        out = render_html("Title", "2026-08-11", "Body.", [story])
        assert "#6b7280" in out

    def test_missing_optional_story_fields_handled_gracefully(self):
        minimal_story = {"title": "Bare story"}
        out = render_html("Title", "2026-08-11", "Body.", [minimal_story])
        assert "Bare story" in out

    def test_escapes_malicious_story_title(self):
        malicious = dict(STORY, title="<script>alert(1)</script>")
        out = render_html("Title", "2026-08-11", "Body.", [malicious])
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_escapes_malicious_url(self):
        malicious = dict(STORY, url='javascript:alert(1)"><script>x</script>')
        out = render_html("Title", "2026-08-11", "Body.", [malicious])
        assert "<script>x</script>" not in out

    def test_falls_back_title_when_date_unparseable(self):
        out = render_html("Title", "not-a-date", "Body.", [])
        assert "not-a-date" in out

    def test_blank_episode_title_falls_back_to_podcast_name(self):
        out = render_html("", "2026-08-11", "Body.", [])
        assert "Database Daily" in out
