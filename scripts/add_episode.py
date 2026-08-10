#!/usr/bin/env python3
"""
add_episode.py - Add a new episode to Database Daily

This script is designed to be called by the future automation agent after
an MP3 has been generated. It:

  1. Creates the episode directory under episodes/YYYY-MM-DD/
  2. Copies (or moves) the audio file into that directory
  3. Writes a metadata.yaml file with the episode details
  4. Optionally runs generate_feed.py to regenerate feed.xml

Usage:
    python scripts/add_episode.py \\
        --audio /path/to/generated.mp3 \\
        --date 2026-08-11 \\
        --title "Database Daily – 2026-08-11" \\
        --description "Today we cover..." \\
        --duration "5:12" \\
        --episode-number 2 \\
        [--update-feed]

All arguments except --audio are optional and have sensible defaults.

No secrets are written or required by this script.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install it with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent


def slugify_date(date_str: str) -> str:
    """Return a YYYY-MM-DD string from various date inputs."""
    date_str = date_str.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    for fmt in ("%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str!r}")


def next_episode_number(episodes_dir: Path) -> int:
    """Scan existing episodes and return the next episode number."""
    existing = sorted(episodes_dir.glob("*/metadata.yaml"))
    return len(existing) + 1


def write_metadata(
    episode_dir: Path,
    title: str,
    date_str: str,
    description: str,
    audio_filename: str,
    duration: str,
    episode_number: int,
    season: int,
    explicit: bool,
    guid: str,
) -> None:
    metadata = {
        "title": title,
        "date": f"{date_str}T07:00:00+00:00",
        "description": description,
        "audio_file": audio_filename,
        "duration": duration,
        "episode_number": episode_number,
        "season": season,
        "explicit": explicit,
        "guid": guid,
    }
    meta_path = episode_dir / "metadata.yaml"
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("# Database Daily - Episode Metadata\n")
        f.write("# Safe for public repositories - no secrets here\n\n")
        yaml.dump(metadata, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"Metadata written: {meta_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Add a new Database Daily episode and optionally regenerate the RSS feed."
    )
    parser.add_argument(
        "--audio",
        required=True,
        help="Path to the generated MP3 file",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Episode date YYYY-MM-DD (default: today UTC)",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Episode title (default: 'Database Daily – YYYY-MM-DD')",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Episode description / show notes",
    )
    parser.add_argument(
        "--duration",
        default="",
        help="Audio duration in HH:MM:SS or MM:SS format (e.g. '5:12')",
    )
    parser.add_argument(
        "--episode-number",
        type=int,
        default=None,
        help="Episode number (default: auto-detect from existing episodes)",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=1,
        help="Season number (default: 1)",
    )
    parser.add_argument(
        "--explicit",
        action="store_true",
        default=False,
        help="Mark episode as explicit (default: false)",
    )
    parser.add_argument(
        "--episodes-dir",
        default=str(REPO_ROOT / "episodes"),
        help="Path to episodes directory (default: repo root/episodes)",
    )
    parser.add_argument(
        "--update-feed",
        action="store_true",
        default=False,
        help="Run generate_feed.py after adding the episode",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        default=False,
        help="Move audio file instead of copying it",
    )
    args = parser.parse_args()

    # Resolve audio file
    audio_src = Path(args.audio).resolve()
    if not audio_src.exists():
        print(f"ERROR: Audio file not found: {audio_src}", file=sys.stderr)
        sys.exit(1)
    if audio_src.suffix.lower() != ".mp3":
        print(f"WARNING: Audio file does not have .mp3 extension: {audio_src}", file=sys.stderr)

    # Resolve date
    date_str = slugify_date(args.date) if args.date else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # Defaults
    title = args.title or f"Database Daily \u2013 {date_str}"
    episodes_dir = Path(args.episodes_dir)
    episode_dir = episodes_dir / date_str

    if episode_dir.exists():
        print(f"WARNING: Episode directory already exists: {episode_dir}")
        existing_audio = list(episode_dir.glob("*.mp3"))
        if existing_audio:
            print(f"  Existing audio: {existing_audio}")
            response = input("  Overwrite? [y/N] ").strip().lower()
            if response != "y":
                print("Aborted.")
                sys.exit(0)
    else:
        episode_dir.mkdir(parents=True, exist_ok=True)

    # Copy or move audio
    audio_filename = "audio.mp3"
    audio_dest = episode_dir / audio_filename
    if args.move:
        shutil.move(str(audio_src), str(audio_dest))
        print(f"Audio moved to: {audio_dest}")
    else:
        shutil.copy2(str(audio_src), str(audio_dest))
        print(f"Audio copied to: {audio_dest}")

    # Episode number
    episode_number = args.episode_number
    if episode_number is None:
        episode_number = next_episode_number(episodes_dir)

    # GUID — stable, derived from date
    guid = f"database-daily-{date_str}"

    # Write metadata
    write_metadata(
        episode_dir=episode_dir,
        title=title,
        date_str=date_str,
        description=args.description,
        audio_filename=audio_filename,
        duration=args.duration,
        episode_number=episode_number,
        season=args.season,
        explicit=args.explicit,
        guid=guid,
    )

    print(f"\nEpisode added: {episode_dir.name} (#{episode_number})")

    # Optionally regenerate feed
    if args.update_feed:
        print("\nRegenerating RSS feed...")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "generate_feed.py")],
            capture_output=False,
        )
        if result.returncode != 0:
            print("ERROR: Feed generation failed.", file=sys.stderr)
            sys.exit(result.returncode)

    print("\nDone. Next steps:")
    print("  1. Review episode directory and metadata.yaml")
    print("  2. Run: python scripts/generate_feed.py")
    print("  3. Run: python scripts/scan_secrets.py")
    print("  4. Commit: git add episodes/ feed.xml && git commit -m 'episode: add YYYY-MM-DD'")
    print("  5. Push:   git push")


if __name__ == "__main__":
    main()
