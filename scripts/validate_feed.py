#!/usr/bin/env python3
"""
validate_feed.py - Validate that feed.xml is a well-formed RSS 2.0 document.

Checks:
  - feed.xml can be parsed as XML
  - Root element is <rss>
  - RSS version attribute is "2.0"
  - <channel> element is present
  - <title> element is present and non-empty

Exit code:
  0 - Valid
  1 - Invalid (error message printed to stderr)

Usage:
    python scripts/validate_feed.py
    python scripts/validate_feed.py --feed /path/to/feed.xml
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def validate(feed_path: Path) -> None:
    tree = ET.parse(feed_path)
    root = tree.getroot()

    assert root.tag == "rss", f"Root element should be 'rss', got '{root.tag}'"
    assert root.attrib.get("version") == "2.0", (
        f"RSS version should be '2.0', got '{root.attrib.get('version')}'"
    )

    channel = root.find("channel")
    assert channel is not None, "Missing <channel> element"

    title = channel.findtext("title")
    assert title, "Missing or empty <title> in <channel>"

    episode_count = len(root.findall(".//item"))
    print(f"Feed valid: {title!r}, {episode_count} episode(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the Database Daily RSS feed.")
    parser.add_argument(
        "--feed",
        default=str(REPO_ROOT / "feed.xml"),
        help="Path to feed.xml (default: repo root/feed.xml)",
    )
    args = parser.parse_args()

    feed_path = Path(args.feed)
    if not feed_path.exists():
        print(f"Feed file not found: {feed_path}", file=sys.stderr)
        sys.exit(1)

    try:
        validate(feed_path)
    except (ET.ParseError, AssertionError, Exception) as e:
        print(f"Feed validation FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
