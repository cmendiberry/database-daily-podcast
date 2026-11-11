#!/usr/bin/env python3
"""
generate_email_html.py - Render the daily digest as a self-contained HTML email.

Reads script.txt (the written digest body) and sources.json (episode_title,
episode_date, stories_selected) and renders a single HTML document with all
styling inlined, suitable for sending as an email body.

Usage:
    python scripts/generate_email_html.py \\
        --script-file  /tmp/episode_generated/script.txt \\
        --sources-file /tmp/episode_generated/sources.json \\
        --output       /tmp/episode_generated/episode.html

No external dependencies — uses Python standard library only.
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

PODCAST_TITLE = "Database Daily"

CATEGORY_COLORS = {
    "Aurora PostgreSQL": "#2f6fed",
    "Aurora MySQL": "#0f9d8c",
    "SQL Server": "#c0392b",
    "General DBA": "#6b7280",
}
DEFAULT_CATEGORY_COLOR = "#6b7280"


def _split_paragraphs(text: str) -> list:
    """Split digest text into paragraphs.

    Respects existing blank-line breaks if present; otherwise groups
    sentences into chunks of three for readability.
    """
    text = text.strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return parts
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = [" ".join(sentences[i : i + 3]) for i in range(0, len(sentences), 3)]
    return [c for c in chunks if c] or [text]


def _format_date(date_str: str) -> str:
    """Return a human-readable date, falling back to the raw string."""
    from datetime import datetime

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.strftime('%A, %B')} {dt.day}, {dt.year}"
    except (ValueError, TypeError):
        return date_str or ""


def _render_story_card(story: dict) -> str:
    """Render a single story as an HTML card."""
    title = html.escape(story.get("title", "Untitled story"))
    url = html.escape(story.get("url", ""), quote=True)
    source = html.escape(story.get("source", ""))
    published = html.escape(story.get("published", ""))
    category = story.get("category", "General DBA")
    relevance = html.escape(story.get("dba_relevance", ""))
    color = CATEGORY_COLORS.get(category, DEFAULT_CATEGORY_COLOR)
    category_safe = html.escape(category)

    meta_bits = [b for b in (source, published) if b]
    meta_line = " · ".join(meta_bits)

    title_html = f'<a href="{url}" style="color:#111827;text-decoration:none;">{title}</a>' if url else title

    return f"""
      <tr>
        <td style="padding:16px 20px;border:1px solid #e5e7eb;border-radius:10px;" >
          <span style="display:inline-block;background:{color};color:#ffffff;font-size:12px;
            font-weight:600;letter-spacing:.02em;padding:2px 10px;border-radius:999px;
            margin-bottom:10px;">{category_safe}</span>
          <div style="font-size:17px;font-weight:700;line-height:1.4;color:#111827;margin:4px 0 6px;">
            {title_html}
          </div>
          <div style="font-size:13px;color:#6b7280;margin-bottom:8px;">{meta_line}</div>
          <div style="font-size:15px;color:#374151;line-height:1.5;">{relevance}</div>
        </td>
      </tr>
      <tr><td style="height:12px;line-height:12px;font-size:0;">&nbsp;</td></tr>"""


def render_html(episode_title: str, date_str: str, script_text: str, stories_selected: list) -> str:
    """Render the full HTML email document."""
    title_safe = html.escape(episode_title or PODCAST_TITLE)
    date_display = html.escape(_format_date(date_str))

    paragraphs_html = "\n".join(
        f'<p style="font-size:16px;line-height:1.65;color:#1f2937;margin:0 0 16px;">{html.escape(p)}</p>'
        for p in _split_paragraphs(script_text)
    )

    if stories_selected:
        stories_html = (
            '<h2 style="font-size:14px;letter-spacing:.04em;text-transform:uppercase;'
            'color:#6b7280;margin:32px 0 14px;">Today\'s stories</h2>\n'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;">\n'
            + "\n".join(_render_story_card(s) for s in stories_selected)
            + "\n</table>"
        )
    else:
        stories_html = ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_safe}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
          style="max-width:640px;background:#ffffff;border-radius:14px;overflow:hidden;
          box-shadow:0 1px 3px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:#111827;padding:24px 32px;">
              <div style="font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
                color:#9ca3af;">{PODCAST_TITLE}</div>
              <div style="font-size:14px;color:#e5e7eb;margin-top:4px;">{date_display}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 32px 8px;">
              <h1 style="font-size:24px;line-height:1.3;color:#111827;margin:0 0 20px;">{title_safe}</h1>
              {paragraphs_html}
              {stories_html}
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px 28px;border-top:1px solid #e5e7eb;">
              <p style="font-size:12px;color:#9ca3af;margin:0;">
                Personal daily digest — generated by Claude from automated research.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the daily digest as a self-contained HTML email."
    )
    parser.add_argument("--script-file", required=True, help="Path to script.txt")
    parser.add_argument("--sources-file", required=True, help="Path to sources.json")
    parser.add_argument("--output", required=True, help="Output path for the rendered HTML")
    args = parser.parse_args()

    script_text = Path(args.script_file).read_text(encoding="utf-8")
    sources = json.loads(Path(args.sources_file).read_text(encoding="utf-8"))

    episode_title = sources.get("episode_title") or f"{PODCAST_TITLE} – {sources.get('episode_date', '')}"
    date_str = sources.get("episode_date", "")
    stories_selected = sources.get("stories_selected", [])

    html_out = render_html(episode_title, date_str, script_text, stories_selected)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_out, encoding="utf-8")
    print(f"HTML digest written to: {output_path}")


if __name__ == "__main__":
    main()
