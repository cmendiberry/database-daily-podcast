#!/usr/bin/env python3
"""
generate_index.py - Generate a minimal index.html for the GitHub Pages site.

Reads podcast.yaml and all episode metadata to produce a simple landing page
at the podcast's GitHub Pages URL. No external dependencies beyond PyYAML.

Usage:
    python scripts/generate_index.py
    python scripts/generate_index.py --config podcast.yaml --output index.html
    python scripts/generate_index.py --episodes-dir /path/to/episodes

Exit codes:
    0 - Success
    1 - Error (config not found)
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
# Reuse config and episode loading from generate_feed
sys.path.insert(0, str(Path(__file__).parent))
from generate_feed import load_config, load_episodes


def _episode_audio_url(ep: dict, base_url: str, repo_root: Path) -> str:
    """Build the public audio URL for an episode."""
    episode_dir = ep["_episode_dir"]
    rel = episode_dir.relative_to(repo_root)
    audio_filename = ep.get("audio_file", "audio.mp3")
    return f"{base_url.rstrip('/')}/{rel.as_posix()}/{audio_filename}"


def render_html(config: dict, episodes: list[dict], repo_root: Path) -> str:
    """Render the index.html string from config and episode list."""
    base_url = config["base_url"].rstrip("/")
    title = config["title"]
    description = config.get("description", "").strip()
    feed_url = f"{base_url}/feed.xml"

    # Episodes table (up to 10 most recent; load_episodes already sorts newest first)
    if episodes:
        rows = []
        for ep in episodes[:10]:
            date_raw = ep.get("date", "")
            date_str = str(date_raw)[:10] if date_raw else "Unknown"
            ep_title = ep.get("title", f"Episode {ep.get('episode_number', '?')}")
            audio_url = _episode_audio_url(ep, base_url, repo_root)
            rows.append(
                f"      <tr>\n"
                f"        <td>{date_str}</td>\n"
                f"        <td>{ep_title}</td>\n"
                f'        <td><a href="{audio_url}">&#9654; Listen</a></td>\n'
                f"      </tr>"
            )
        episodes_html = (
            "    <table>\n"
            "      <thead><tr><th>Date</th><th>Title</th><th></th></tr></thead>\n"
            "      <tbody>\n"
            + "\n".join(rows)
            + "\n      </tbody>\n"
            "    </table>"
        )
    else:
        episodes_html = '    <p class="none">No episodes published yet.</p>'

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"  <title>{title}</title>\n"
        "  <style>\n"
        "    body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;"
        "padding:0 1rem;color:#1a1a1a;line-height:1.6}\n"
        "    h1{font-size:1.75rem;margin-bottom:.25rem}\n"
        "    .desc{color:#444;margin-top:0}\n"
        "    .rss{display:inline-block;margin:1rem 0;padding:.4rem 1rem;"
        "background:#f5813f;color:#fff;text-decoration:none;border-radius:4px;"
        "font-weight:600}\n"
        "    .rss:hover{background:#d96f2a}\n"
        "    h2{margin-top:2rem;border-top:1px solid #e0e0e0;padding-top:1rem}\n"
        "    table{width:100%;border-collapse:collapse}\n"
        "    th{text-align:left;padding:.4rem .5rem;border-bottom:2px solid #ddd;"
        "color:#555;font-size:.875rem}\n"
        "    td{padding:.4rem .5rem;border-bottom:1px solid #eee}\n"
        "    a{color:#0969da}\n"
        "    .none{color:#888;font-style:italic}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{title}</h1>\n"
        f'  <p class="desc">{description}</p>\n'
        f'  <a class="rss" href="{feed_url}">&#9733; Subscribe via RSS</a>\n'
        "  <h2>Episodes</h2>\n"
        f"{episodes_html}\n"
        "</body>\n"
        "</html>\n"
    )


def generate_index(
    config_path: Path,
    episodes_dir: Path,
    output_path: Path,
    repo_root: Path,
) -> None:
    """Generate index.html and write it to output_path."""
    config = load_config(config_path)
    episodes = load_episodes(episodes_dir)
    html = render_html(config, episodes, repo_root)
    output_path.write_text(html, encoding="utf-8")
    listed = min(len(episodes), 10)
    print(f"Index written to: {output_path}")
    print(f"  Episodes listed: {listed} of {len(episodes)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate index.html for the Database Daily GitHub Pages site."
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
        default=str(REPO_ROOT / "index.html"),
        help="Output path for index.html (default: repo root/index.html)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)
    config = load_config(config_path)
    episodes_dir = (
        Path(args.episodes_dir)
        if args.episodes_dir
        else REPO_ROOT / config.get("episodes_dir", "episodes")
    )

    generate_index(config_path, episodes_dir, output_path, REPO_ROOT)


if __name__ == "__main__":
    main()
