"""
test_feed.py - Test suite for Database Daily RSS feed generation

Tests:
  1. Minimal MP3 creation (no real audio tools required)
  2. Episode metadata creation
  3. RSS feed generation
  4. RSS XML validation (structure, required elements)
  5. Enclosure URL, MIME type, length, GUID, pubDate correctness
  6. No-episode edge case (empty feed is still valid XML)
  7. Secret-scan clean check on the repository

Requires:
    pytest
    pyyaml

No real Claude, YouTube, or any paid API credentials are needed.

Run:
    pip install pytest pyyaml
    pytest tests/test_feed.py -v
"""

import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

# Add scripts directory so we can import generate_feed
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_feed import load_config, load_episodes, generate_feed, to_rfc2822


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"

def itunes(tag):
    return f"{{{ITUNES_NS}}}{tag}"


def make_mp3_frame() -> bytes:
    """One silent MPEG1 Layer 3 frame (417 bytes)."""
    header = bytes([0xFF, 0xFB, 0x90, 0x44])
    return header + bytes(413)


def create_test_mp3(path: Path, num_frames: int = 10) -> int:
    frame = make_mp3_frame()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        for _ in range(num_frames):
            f.write(frame)
    return path.stat().st_size


def make_test_config(base_url: str = "https://testuser.github.io/database-daily-podcast") -> dict:
    return {
        "title": "Database Daily",
        "description": "A short weekday briefing covering the latest important news in "
                       "Amazon Aurora, Microsoft SQL Server, and PostgreSQL.",
        "author": "Database Daily",
        "language": "en-us",
        "category": "Technology",
        "subcategory": "Tech News",
        "explicit": False,
        "type": "episodic",
        "base_url": base_url,
        "cover_art_path": "cover-art/cover.jpg",
        "episodes_dir": "episodes",
        "feed_output": "feed.xml",
        "copyright": "Database Daily",
        "managing_editor": "noreply@example.com (Database Daily)",
        "web_master": "noreply@example.com (Database Daily)",
        "itunes_owner_name": "Database Daily",
        "itunes_owner_email": "noreply@example.com",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """
    Temporary directory tree mimicking the repo structure:
        tmp_path/
          podcast.yaml
          episodes/
            2026-08-10/
              audio.mp3
              metadata.yaml
          cover-art/
    """
    config = make_test_config()

    # Write podcast.yaml
    config_path = tmp_path / "podcast.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    # Create cover-art dir
    (tmp_path / "cover-art").mkdir()

    # Create one episode
    episode_dir = tmp_path / "episodes" / "2026-08-10"
    episode_dir.mkdir(parents=True)

    # Create minimal MP3
    audio_path = episode_dir / "audio.mp3"
    audio_size = create_test_mp3(audio_path, num_frames=20)

    # Write metadata.yaml
    metadata = {
        "title": "Database Daily \u2013 2026-08-10",
        "date": "2026-08-10T07:00:00+00:00",
        "description": (
            "Today: Aurora PostgreSQL 16.4 patch released with performance "
            "improvements. SQL Server 2025 CU1 drops. PostgreSQL 17 RC1 out. "
            "Why this matters: patch early, patch often."
        ),
        "audio_file": "audio.mp3",
        "duration": "5:12",
        "episode_number": 1,
        "season": 1,
        "explicit": False,
        "guid": "database-daily-2026-08-10",
    }
    meta_path = episode_dir / "metadata.yaml"
    with open(meta_path, "w", encoding="utf-8") as f:
        yaml.dump(metadata, f, default_flow_style=False, allow_unicode=True)

    return tmp_path, config, episode_dir, audio_path, audio_size


# ---------------------------------------------------------------------------
# Test 1: Minimal MP3 creation
# ---------------------------------------------------------------------------

class TestMinimalMp3:
    def test_mp3_created(self, tmp_path):
        path = tmp_path / "test.mp3"
        size = create_test_mp3(path, num_frames=5)
        assert path.exists()
        assert size == 5 * 417  # 5 frames × 417 bytes each

    def test_mp3_starts_with_sync_word(self, tmp_path):
        path = tmp_path / "test.mp3"
        create_test_mp3(path)
        data = path.read_bytes()
        # MPEG sync word: first 11 bits = 1
        assert data[0] == 0xFF
        assert data[1] & 0xE0 == 0xE0  # top 3 bits of byte 2 are 111

    def test_mp3_layer3_header(self, tmp_path):
        path = tmp_path / "test.mp3"
        create_test_mp3(path)
        data = path.read_bytes()
        # Byte 1: 0xFB = 1111 1011
        # bits 5-4 of byte 1 = 01 → Layer 3
        assert data[1] == 0xFB


# ---------------------------------------------------------------------------
# Test 2: Episode metadata loading
# ---------------------------------------------------------------------------

class TestEpisodeLoading:
    def test_episodes_found(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        assert len(episodes) == 1

    def test_episode_title(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        assert "Database Daily" in episodes[0]["title"]

    def test_episode_guid(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        assert episodes[0]["guid"] == "database-daily-2026-08-10"

    def test_empty_episodes_dir(self, tmp_path):
        empty_dir = tmp_path / "episodes"
        empty_dir.mkdir()
        episodes = load_episodes(empty_dir)
        assert episodes == []

    def test_missing_episodes_dir(self, tmp_path):
        missing = tmp_path / "nonexistent"
        episodes = load_episodes(missing)
        assert episodes == []


# ---------------------------------------------------------------------------
# Test 3: Config loading
# ---------------------------------------------------------------------------

class TestConfigLoading:
    def test_config_loads(self, tmp_repo):
        tmp_path, config, *_ = tmp_repo
        loaded = load_config(tmp_path / "podcast.yaml")
        assert loaded["title"] == "Database Daily"
        assert loaded["language"] == "en-us"
        assert loaded["author"] == "Database Daily"

    def test_config_warns_on_placeholder_url(self, tmp_path, capsys):
        cfg = make_test_config(base_url="https://YOUR_GITHUB_USERNAME.github.io/database-daily-podcast")
        cfg_path = tmp_path / "podcast.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(cfg, f)
        load_config(cfg_path)
        captured = capsys.readouterr()
        assert "YOUR_GITHUB_USERNAME" in captured.err


# ---------------------------------------------------------------------------
# Test 4: RSS feed generation
# ---------------------------------------------------------------------------

class TestFeedGeneration:
    def test_feed_file_created(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        output = tmp_path / "feed.xml"
        generate_feed(config, episodes, tmp_path, output)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_feed_is_valid_xml(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        output = tmp_path / "feed.xml"
        generate_feed(config, episodes, tmp_path, output)
        # Should not raise
        tree = ET.parse(output)
        root = tree.getroot()
        assert root.tag == "rss"

    def test_feed_rss_version(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        output = tmp_path / "feed.xml"
        generate_feed(config, episodes, tmp_path, output)
        tree = ET.parse(output)
        root = tree.getroot()
        assert root.attrib.get("version") == "2.0"

    def test_feed_has_channel(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        output = tmp_path / "feed.xml"
        generate_feed(config, episodes, tmp_path, output)
        tree = ET.parse(output)
        channel = tree.find("channel")
        assert channel is not None

    def test_empty_feed_is_valid_xml(self, tmp_path):
        """Feed with zero episodes should still be valid XML."""
        config = make_test_config()
        output = tmp_path / "feed.xml"
        generate_feed(config, [], tmp_path, output)
        tree = ET.parse(output)
        root = tree.getroot()
        assert root.tag == "rss"
        items = tree.findall(".//item")
        assert len(items) == 0


# ---------------------------------------------------------------------------
# Test 5: Channel metadata correctness
# ---------------------------------------------------------------------------

class TestChannelMetadata:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        output = tmp_path / "feed.xml"
        generate_feed(config, episodes, tmp_path, output)
        self.tree = ET.parse(output)
        self.channel = self.tree.find("channel")

    def test_title(self):
        assert self.channel.findtext("title") == "Database Daily"

    def test_language(self):
        assert self.channel.findtext("language") == "en-us"

    def test_itunes_author(self):
        assert self.channel.findtext(itunes("author")) == "Database Daily"

    def test_itunes_type(self):
        assert self.channel.findtext(itunes("type")) == "episodic"

    def test_itunes_explicit_false(self):
        assert self.channel.findtext(itunes("explicit")) == "false"

    def test_itunes_image(self):
        img = self.channel.find(itunes("image"))
        assert img is not None
        href = img.attrib.get("href", "")
        assert href.startswith("https://testuser.github.io")
        assert "cover" in href

    def test_itunes_owner(self):
        owner = self.channel.find(itunes("owner"))
        assert owner is not None
        assert owner.findtext(itunes("name")) == "Database Daily"


# ---------------------------------------------------------------------------
# Test 6: Episode item correctness
# ---------------------------------------------------------------------------

class TestEpisodeItem:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_repo):
        self.tmp_path, config, self.episode_dir, self.audio_path, self.audio_size = tmp_repo
        episodes = load_episodes(self.tmp_path / "episodes")
        output = self.tmp_path / "feed.xml"
        generate_feed(config, episodes, self.tmp_path, output)
        self.tree = ET.parse(output)
        self.item = self.tree.find(".//item")

    def test_item_exists(self):
        assert self.item is not None

    def test_episode_title(self):
        title = self.item.findtext("title")
        assert "2026-08-10" in title
        assert "Database Daily" in title

    def test_guid_value(self):
        guid = self.item.find("guid")
        assert guid is not None
        assert guid.text == "database-daily-2026-08-10"

    def test_guid_is_not_permalink(self):
        guid = self.item.find("guid")
        assert guid.attrib.get("isPermaLink") == "false"

    def test_pub_date_format(self):
        pub_date = self.item.findtext("pubDate")
        assert pub_date is not None
        # RFC 2822 format: "Mon, 10 Aug 2026 07:00:00 +0000"
        # Just check key parts
        assert "2026" in pub_date
        assert "Aug" in pub_date or "08" in pub_date

    def test_enclosure_exists(self):
        enc = self.item.find("enclosure")
        assert enc is not None

    def test_enclosure_mime_type(self):
        enc = self.item.find("enclosure")
        assert enc.attrib.get("type") == "audio/mpeg"

    def test_enclosure_url(self):
        enc = self.item.find("enclosure")
        url = enc.attrib.get("url", "")
        assert url.startswith("https://testuser.github.io/database-daily-podcast")
        assert "episodes/2026-08-10/audio.mp3" in url

    def test_enclosure_length_nonzero(self):
        enc = self.item.find("enclosure")
        length = int(enc.attrib.get("length", "0"))
        assert length > 0
        assert length == self.audio_size

    def test_duration(self):
        dur = self.item.findtext(itunes("duration"))
        assert dur == "5:12"

    def test_episode_number(self):
        ep_num = self.item.findtext(itunes("episode"))
        assert ep_num == "1"

    def test_description_not_empty(self):
        desc = self.item.findtext("description")
        assert desc and len(desc) > 10


# ---------------------------------------------------------------------------
# Test 7: Date conversion
# ---------------------------------------------------------------------------

class TestDateConversion:
    def test_iso_with_tz(self):
        result = to_rfc2822("2026-08-10T07:00:00+00:00")
        assert "2026" in result
        assert "Aug" in result

    def test_iso_naive(self):
        result = to_rfc2822("2026-08-10T07:00:00")
        assert "2026" in result

    def test_date_only(self):
        result = to_rfc2822("2026-08-10")
        assert "2026" in result

    def test_datetime_object(self):
        dt = datetime(2026, 8, 10, 7, 0, 0, tzinfo=timezone.utc)
        result = to_rfc2822(dt)
        assert "2026" in result
        assert "Aug" in result


# ---------------------------------------------------------------------------
# Test 8: Multiple episodes sorted newest-first
# ---------------------------------------------------------------------------

class TestMultipleEpisodes:
    def test_episodes_sorted_newest_first(self, tmp_path):
        ep_dir = tmp_path / "episodes"
        dates = ["2026-08-08", "2026-08-11", "2026-08-09", "2026-08-10"]
        for d in dates:
            d_dir = ep_dir / d
            d_dir.mkdir(parents=True)
            create_test_mp3(d_dir / "audio.mp3", num_frames=3)
            with open(d_dir / "metadata.yaml", "w", encoding="utf-8") as f:
                yaml.dump({
                    "title": f"Database Daily \u2013 {d}",
                    "date": f"{d}T07:00:00+00:00",
                    "audio_file": "audio.mp3",
                    "guid": f"database-daily-{d}",
                }, f)

        episodes = load_episodes(ep_dir)
        assert len(episodes) == 4
        titles = [ep["title"] for ep in episodes]
        assert "2026-08-11" in titles[0]
        assert "2026-08-08" in titles[-1]

    def test_multiple_episodes_in_feed(self, tmp_path):
        ep_dir = tmp_path / "episodes"
        for i, d in enumerate(["2026-08-08", "2026-08-09", "2026-08-10"], start=1):
            d_dir = ep_dir / d
            d_dir.mkdir(parents=True)
            create_test_mp3(d_dir / "audio.mp3", num_frames=5)
            with open(d_dir / "metadata.yaml", "w", encoding="utf-8") as f:
                yaml.dump({
                    "title": f"Episode {i}",
                    "date": f"{d}T07:00:00+00:00",
                    "audio_file": "audio.mp3",
                    "guid": f"database-daily-{d}",
                    "episode_number": i,
                }, f)

        config = make_test_config()
        episodes = load_episodes(ep_dir)
        output = tmp_path / "feed.xml"
        generate_feed(config, episodes, tmp_path, output)
        tree = ET.parse(output)
        items = tree.findall(".//item")
        assert len(items) == 3


# ---------------------------------------------------------------------------
# Test 9: Secret scan on the real repository
# ---------------------------------------------------------------------------

class TestSecretScan:
    def test_repo_has_no_secrets(self):
        """
        Run the secret scanner on the actual repository.
        This test verifies that no secrets have been committed.
        """
        import subprocess
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "scan_secrets.py")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Secret scanner found potential secrets in the repository!\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        assert "CLEAN" in result.stdout


# ---------------------------------------------------------------------------
# Test 10: Feed XML declaration
# ---------------------------------------------------------------------------

class TestFeedXmlDeclaration:
    def test_feed_starts_with_xml_declaration(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        output = tmp_path / "feed.xml"
        generate_feed(config, episodes, tmp_path, output)
        raw = output.read_bytes()
        assert raw.startswith(b"<?xml")

    def test_feed_encoding_is_utf8(self, tmp_repo):
        tmp_path, config, episode_dir, audio_path, audio_size = tmp_repo
        episodes = load_episodes(tmp_path / "episodes")
        output = tmp_path / "feed.xml"
        generate_feed(config, episodes, tmp_path, output)
        raw = output.read_bytes().decode("utf-8")
        assert "encoding" in raw[:100].lower() or "UTF-8" in raw[:100]
