"""
test_generate_index.py - Tests for scripts/generate_index.py

Tests:
  - render_html() produces valid HTML with correct content
  - generate_index() writes index.html to disk
  - zero-episode and multi-episode cases
  - audio URLs are correctly constructed

No external dependencies beyond pyyaml.
"""

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_index import render_html, generate_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(base_url="https://testuser.github.io/database-daily-podcast"):
    return {
        "title": "Database Daily",
        "description": "A short weekday briefing.",
        "author": "Database Daily",
        "language": "en-us",
        "base_url": base_url,
        "episodes_dir": "episodes",
        "feed_output": "feed.xml",
    }


def make_episode(tmp_path: Path, date_str: str, title: str, episode_number: int = 1):
    """Create a minimal episode directory with metadata.yaml and a fake MP3."""
    ep_dir = tmp_path / "episodes" / date_str
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / "audio.mp3").write_bytes(b"\x00" * 100)
    with open(ep_dir / "metadata.yaml", "w", encoding="utf-8") as f:
        yaml.dump(
            {
                "title": title,
                "date": f"{date_str}T07:00:00+00:00",
                "audio_file": "audio.mp3",
                "guid": f"database-daily-{date_str}",
                "episode_number": episode_number,
            },
            f,
            allow_unicode=True,
        )
    return ep_dir


# ---------------------------------------------------------------------------
# render_html — unit tests (no file I/O)
# ---------------------------------------------------------------------------


class TestRenderHtml:
    def test_starts_with_doctype(self):
        html = render_html(make_config(), [], Path("/repo"))
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_title(self):
        html = render_html(make_config(), [], Path("/repo"))
        assert "Database Daily" in html

    def test_contains_description(self):
        html = render_html(make_config(), [], Path("/repo"))
        assert "A short weekday briefing." in html

    def test_contains_rss_link(self):
        html = render_html(make_config(), [], Path("/repo"))
        assert "feed.xml" in html

    def test_no_episodes_placeholder(self):
        html = render_html(make_config(), [], Path("/repo"))
        assert "No episodes" in html

    def test_charset_utf8(self):
        html = render_html(make_config(), [], Path("/repo"))
        assert "UTF-8" in html

    def test_has_lang_attribute(self):
        html = render_html(make_config(), [], Path("/repo"))
        assert 'lang="en"' in html


# ---------------------------------------------------------------------------
# generate_index — integration tests (with real files)
# ---------------------------------------------------------------------------


class TestGenerateIndex:
    def test_creates_file(self, tmp_path):
        config_path = tmp_path / "podcast.yaml"
        with open(config_path, "w") as f:
            yaml.dump(make_config(), f)
        (tmp_path / "episodes").mkdir()
        output = tmp_path / "index.html"
        generate_index(config_path, tmp_path / "episodes", output, tmp_path)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_output_is_utf8(self, tmp_path):
        config_path = tmp_path / "podcast.yaml"
        with open(config_path, "w") as f:
            yaml.dump(make_config(), f)
        (tmp_path / "episodes").mkdir()
        output = tmp_path / "index.html"
        generate_index(config_path, tmp_path / "episodes", output, tmp_path)
        # Should decode without errors
        html = output.read_text(encoding="utf-8")
        assert "Database Daily" in html

    def test_episode_title_appears(self, tmp_path):
        config_path = tmp_path / "podcast.yaml"
        with open(config_path, "w") as f:
            yaml.dump(make_config(), f)
        make_episode(tmp_path, "2026-08-11", "My Test Episode")
        output = tmp_path / "index.html"
        generate_index(config_path, tmp_path / "episodes", output, tmp_path)
        html = output.read_text(encoding="utf-8")
        assert "My Test Episode" in html

    def test_episode_date_appears(self, tmp_path):
        config_path = tmp_path / "podcast.yaml"
        with open(config_path, "w") as f:
            yaml.dump(make_config(), f)
        make_episode(tmp_path, "2026-08-11", "Test Episode")
        output = tmp_path / "index.html"
        generate_index(config_path, tmp_path / "episodes", output, tmp_path)
        html = output.read_text(encoding="utf-8")
        assert "2026-08-11" in html

    def test_audio_url_constructed_correctly(self, tmp_path):
        cfg = make_config(base_url="https://example.github.io/podcast")
        config_path = tmp_path / "podcast.yaml"
        with open(config_path, "w") as f:
            yaml.dump(cfg, f)
        make_episode(tmp_path, "2026-08-11", "Test Episode")
        output = tmp_path / "index.html"
        generate_index(config_path, tmp_path / "episodes", output, tmp_path)
        html = output.read_text(encoding="utf-8")
        assert "episodes/2026-08-11/audio.mp3" in html
        assert "example.github.io/podcast" in html

    def test_multiple_episodes_all_appear(self, tmp_path):
        config_path = tmp_path / "podcast.yaml"
        with open(config_path, "w") as f:
            yaml.dump(make_config(), f)
        make_episode(tmp_path, "2026-08-09", "Episode One", 1)
        make_episode(tmp_path, "2026-08-10", "Episode Two", 2)
        make_episode(tmp_path, "2026-08-11", "Episode Three", 3)
        output = tmp_path / "index.html"
        generate_index(config_path, tmp_path / "episodes", output, tmp_path)
        html = output.read_text(encoding="utf-8")
        assert "Episode One" in html
        assert "Episode Two" in html
        assert "Episode Three" in html
