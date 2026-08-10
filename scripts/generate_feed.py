#!/usr/bin/env python3
"""
generate_feed.py - Database Daily RSS Feed Generator

Reads podcast.yaml and all episode metadata.yaml files under episodes/,
then writes a standards-compliant RSS 2.0 feed (with iTunes extensions)
to feed.xml (or a custom output path).

Usage:
    python scripts/generate_feed.py
    python scripts/generate_feed.py --config podcast.yaml --output feed.xml
    python scripts/generate_feed.py --episodes-dir /path/to/episodes

No external dependencies — uses Python standard library only.
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent
import xml.etree.ElementTree as ET

# PyYAML is the only non-stdlib dependency. It is widely available and
# installable via: pip install pyyaml
try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install it with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


REPO_ROOT = Path(__file__).parent.parent


def load_config(config_path: Path) -> dict:
    """Load and validate podcast.yaml."""
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    required = ["title", "description", "author", "language", "base_url"]
    for key in required:
        if not config.get(key):
            print(f"ERROR: Missing required config key: {key}", file=sys.stderr)
            sys.exit(1)
    if "YOUR_GITHUB_USERNAME" in config.get("base_url", ""):
        print(
            "WARNING: base_url still contains placeholder 'YOUR_GITHUB_USERNAME'.\n"
            "         Update podcast.yaml before publishing the feed.",
            file=sys.stderr,
        )
    return config


def load_episodes(episodes_dir: Path) -> list[dict]:
    """
    Scan episodes_dir for metadata.yaml files.

    Expected layout:
        episodes/
          YYYY-MM-DD/
            metadata.yaml
            audio.mp3

    Returns episodes sorted by date descending (newest first).
    """
    episodes = []
    if not episodes_dir.exists():
        return episodes

    for meta_path in sorted(episodes_dir.rglob("metadata.yaml")):
        with open(meta_path, encoding="utf-8") as f:
            ep = yaml.safe_load(f)
        ep["_meta_path"] = meta_path
        ep["_episode_dir"] = meta_path.parent
        episodes.append(ep)

    # Sort newest first
    def episode_date(ep):
        d = ep.get("date")
        if isinstance(d, datetime):
            return d
        if isinstance(d, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(d, fmt)
                except ValueError:
                    continue
        return datetime.min

    episodes.sort(key=episode_date, reverse=True)
    return episodes


def to_rfc2822(date_value) -> str:
    """Convert a date string or datetime to RFC 2822 format for pubDate."""
    if isinstance(date_value, datetime):
        dt = date_value
    elif isinstance(date_value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(date_value, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Cannot parse date: {date_value!r}")
    else:
        raise ValueError(f"Unsupported date type: {type(date_value)}")

    # If no timezone info, assume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt)


def get_audio_size(audio_path: Path) -> int:
    """Return file size in bytes, or 0 if file not found."""
    if audio_path.exists():
        return audio_path.stat().st_size
    return 0


def build_enclosure_url(base_url: str, episode_dir: Path, audio_filename: str, repo_root: Path) -> str:
    """Build the public URL for an episode audio file."""
    rel = episode_dir.relative_to(repo_root)
    # Normalize path separators to forward slashes for URLs
    rel_posix = rel.as_posix()
    return f"{base_url.rstrip('/')}/{rel_posix}/{audio_filename}"


def generate_feed(config: dict, episodes: list[dict], repo_root: Path, output_path: Path) -> None:
    """Build the RSS XML tree and write it to output_path."""

    base_url = config["base_url"].rstrip("/")

    # Namespaces
    namespaces = {
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
        "xmlns:podcast": "https://podcastindex.org/namespace/1.0",
    }

    rss = Element("rss", {"version": "2.0", **namespaces})
    channel = SubElement(rss, "channel")

    # --- Channel metadata ---
    def sub(parent, tag, text=None, **attrib):
        el = SubElement(parent, tag, attrib)
        if text is not None:
            el.text = str(text)
        return el

    sub(channel, "title", config["title"])
    sub(channel, "link", base_url)
    sub(channel, "description", config["description"].strip())
    sub(channel, "language", config["language"])
    sub(channel, "copyright", config.get("copyright", config["author"]))
    sub(channel, "managingEditor", config.get("managing_editor", f"noreply@example.com ({config['author']})"))
    sub(channel, "webMaster", config.get("web_master", f"noreply@example.com ({config['author']})"))

    # Build date (now, in RFC 2822)
    now_rfc = format_datetime(datetime.now(tz=timezone.utc))
    sub(channel, "lastBuildDate", now_rfc)
    sub(channel, "pubDate", now_rfc)

    # iTunes channel tags
    sub(channel, "itunes:author", config["author"])
    sub(channel, "itunes:type", config.get("type", "episodic"))

    itunes_explicit = "true" if config.get("explicit", False) else "false"
    sub(channel, "itunes:explicit", itunes_explicit)

    # iTunes category — uses XML attribute "text", not element text content
    category = config.get("category", "Technology")
    cat_el = SubElement(channel, "itunes:category")
    cat_el.set("text", category)
    subcategory = config.get("subcategory")
    if subcategory:
        subcat_el = SubElement(cat_el, "itunes:category")
        subcat_el.set("text", subcategory)

    # iTunes image
    cover_art_path = config.get("cover_art_path", "cover-art/cover.jpg")
    cover_url = f"{base_url}/{cover_art_path}"
    sub(channel, "itunes:image", **{"href": cover_url})

    # iTunes owner block
    owner_el = sub(channel, "itunes:owner")
    sub(owner_el, "itunes:name", config.get("itunes_owner_name", config["author"]))
    sub(owner_el, "itunes:email", config.get("itunes_owner_email", "noreply@example.com"))

    # iTunes summary (same as description for compatibility)
    sub(channel, "itunes:summary", config["description"].strip())

    # --- Episodes ---
    for ep_num, ep in enumerate(episodes, start=1):
        item = SubElement(channel, "item")

        title = ep.get("title", f"Database Daily – Episode {ep_num}")
        sub(item, "title", title)

        # GUID — immutable unique identifier
        guid_val = ep.get("guid")
        if not guid_val:
            # Fall back to deriving from directory name
            guid_val = f"database-daily-{ep['_episode_dir'].name}"
        guid_el = sub(item, "guid", guid_val)
        guid_el.set("isPermaLink", "false")

        # Publication date
        date_val = ep.get("date")
        if date_val:
            pub_date = to_rfc2822(date_val)
        else:
            pub_date = now_rfc
        sub(item, "pubDate", pub_date)

        # Description / show notes
        description = ep.get("description", "").strip()
        sub(item, "description", description)
        sub(item, "itunes:summary", description)

        # Enclosure (audio file)
        audio_filename = ep.get("audio_file", "audio.mp3")
        audio_path = ep["_episode_dir"] / audio_filename
        audio_size = get_audio_size(audio_path)
        audio_url = build_enclosure_url(base_url, ep["_episode_dir"], audio_filename, repo_root)

        enclosure_el = SubElement(item, "enclosure")
        enclosure_el.set("url", audio_url)
        enclosure_el.set("length", str(audio_size))
        enclosure_el.set("type", "audio/mpeg")

        # iTunes episode metadata
        duration = ep.get("duration", "")
        if duration:
            sub(item, "itunes:duration", str(duration))

        sub(item, "itunes:explicit", "true" if ep.get("explicit", False) else "false")

        episode_number = ep.get("episode_number")
        if episode_number is not None:
            sub(item, "itunes:episode", str(episode_number))

        season = ep.get("season")
        if season is not None:
            sub(item, "itunes:season", str(season))

        # Link to episode page (same as audio URL for now)
        sub(item, "link", audio_url)

    # Pretty-print with indentation (Python 3.9+)
    try:
        indent(rss, space="  ")
    except AttributeError:
        pass  # Python < 3.9 — write without indentation

    tree = ElementTree(rss)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="unicode", xml_declaration=False)

    print(f"Feed written to: {output_path}")
    print(f"  Episodes included: {len(episodes)}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate the Database Daily RSS feed from episode metadata."
    )
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "podcast.yaml"),
        help="Path to podcast.yaml (default: repo root)",
    )
    parser.add_argument(
        "--episodes-dir",
        default=None,
        help="Path to episodes directory (default: from config)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for feed.xml (default: from config)",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))

    episodes_dir = Path(args.episodes_dir) if args.episodes_dir else REPO_ROOT / config.get("episodes_dir", "episodes")
    output_path = Path(args.output) if args.output else REPO_ROOT / config.get("feed_output", "feed.xml")

    episodes = load_episodes(episodes_dir)
    generate_feed(config, episodes, REPO_ROOT, output_path)


if __name__ == "__main__":
    main()
