#!/usr/bin/env python3
"""
research_generate.py - Fetch authoritative database news and generate episode script.

Usage (automated research):
    python scripts/research_generate.py --date YYYY-MM-DD --output-dir /tmp/dir

Usage (manual script override — skips all research and LLM):
    EPISODE_SCRIPT="..." python scripts/research_generate.py --date YYYY-MM-DD --output-dir /tmp/dir

Outputs written to --output-dir:
    script.txt   - spoken episode script (~650-700 words)
    sources.json - research metadata and selected stories for audit

Environment:
    ANTHROPIC_API_KEY  required for automated research (not needed for manual override)
    EPISODE_SCRIPT     if non-empty, bypasses research entirely and uses this text

Exit codes:
    0 - success
    1 - error (missing API key, all feeds failed, script too short, JSON parse error)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

SOURCES = [
    {
        "name": "AWS What's New",
        "url": "https://aws.amazon.com/about-aws/whats-new/recent/feed/",
        "keywords": ["aurora", "rds", "database", "postgresql", "mysql", "sql server"],
    },
    {
        "name": "AWS Database Blog",
        "url": "https://aws.amazon.com/blogs/database/feed/",
        "keywords": [],  # All posts are database-relevant
    },
    {
        "name": "Microsoft SQL Server Blog",
        "url": "https://techcommunity.microsoft.com/t5/sql-server-blog/bg-p/SQLServerBlog/rss",
        "keywords": [],  # All posts are SQL Server-relevant
    },
    {
        "name": "PostgreSQL News",
        "url": "https://www.postgresql.org/news/feed/",
        # Only keep items that are likely Aurora-relevant
        "keywords": ["release", "security", "upgrade", "version", "aurora", "aws"],
    },
]

RESEARCH_WINDOW_DAYS = 7
FEED_TIMEOUT = 20
MIN_SCRIPT_WORDS = 500
MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Editorial system prompt (embedded — core intelligence of the script)
# ---------------------------------------------------------------------------

EDITORIAL_SYSTEM_PROMPT = """\
You are the script writer for Database Daily, a short weekday podcast for DBAs and \
DBREs responsible for production database environments.

PRIORITY ORDER for story selection:
1. AWS Aurora PostgreSQL  (highest priority)
2. AWS Aurora MySQL
3. Microsoft SQL Server
4. General DBA / DBRE operational news

AUDIENCE: Working DBAs and DBREs. Topics must be operational — administration, \
reliability, availability, upgrades, patching, security, auth, backup/recovery, \
disaster recovery, monitoring, performance troubleshooting, replication, maintenance, \
storage, capacity planning, HA, and operational automation.

EXCLUDE topics whose primary audience is application developers: ORM features, \
SQL programming tutorials, schema design tutorials, application framework integrations, \
new programming language libraries (unless they break authentication, TLS, or \
connection pooling in a way DBAs must address), generic application architecture.

AURORA RESTRICTION: Do NOT include generic PostgreSQL or MySQL upstream news \
unless it directly relates to an Aurora-supported or Aurora-compatible version, \
has been announced for Aurora, or is critical for planning an Aurora upgrade. \
The show is not a generic PostgreSQL or MySQL news podcast.

For each selected story explain:
  1. What changed?
  2. Which database versions / environments are affected?
  3. Why should a DBA or DBRE care?
  4. Is there anything they should check, patch, upgrade, configure, or prepare for?

Do not merely read release notes — translate announcements into operational consequences.

TONE: Concise, technical, practical, factual, vendor-neutral.

Always state clearly when something is: preview, beta, region-specific, \
version-specific, deprecated, Extended Support only, or not yet GA.

Never present speculation as fact. If a claim cannot be verified from the \
provided research items, omit it rather than guess.

TARGET SCRIPT LENGTH: approximately 650-700 spoken words for a ~5 minute episode.

FORMAT: Start with a brief intro, e.g.:
  "Welcome to Database Daily. Today is [full date]. \
I'm your host, and here's what DBAs and DBREs need to know today."
End with a brief outro, e.g.:
  "That's all for today's Database Daily. Stay reliable out there."

Select 2-4 of the strongest DBA-relevant stories from the research items provided. \
Do not force one story from each category. Quality and operational relevance matter \
more than category balance. If a category has no meaningful new development, skip it.\
"""

# ---------------------------------------------------------------------------
# Feed utilities
# ---------------------------------------------------------------------------


def _clean_html(html: str) -> str:
    """Strip HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_entry_date(entry) -> "datetime | None":
    """Parse feedparser entry date into a UTC-aware datetime, or None."""
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _item_matches_keywords(entry, keywords: list) -> bool:
    """Return True if entry title+summary contains at least one keyword (case-insensitive)."""
    if not keywords:
        return True
    text = (
        entry.get("title", "") + " " + entry.get("summary", "")
    ).lower()
    return any(kw.lower() in text for kw in keywords)


def fetch_all_feeds(max_age_days: int = RESEARCH_WINDOW_DAYS, timeout: int = FEED_TIMEOUT) -> dict:
    """
    Fetch items from all configured RSS feeds.

    Returns a dict keyed by source name:
        {
          "items": [...],
          "fetched": int,
          "relevant": int,
          "error": str | None,
        }
    """
    try:
        import feedparser
    except ImportError:
        print("ERROR: feedparser not installed. Run: pip install feedparser", file=sys.stderr)
        sys.exit(1)

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    results = {}

    for source in SOURCES:
        name = source["name"]
        url = source["url"]
        keywords = source.get("keywords", [])

        try:
            feed = feedparser.parse(
                url,
                request_headers={"User-Agent": "DatabaseDailyBot/1.0 podcast-research"},
                agent="DatabaseDailyBot/1.0",
            )

            if feed.get("bozo") and not feed.entries:
                raise ValueError(f"Feed parse error: {feed.get('bozo_exception', 'unknown')}")

            items = []
            for entry in feed.entries:
                pub_date = _parse_entry_date(entry)
                if pub_date and pub_date < cutoff:
                    continue  # Too old

                title = entry.get("title", "")
                summary = _clean_html(entry.get("summary", ""))
                url_item = entry.get("link", "")

                # Apply keyword filter
                mock_entry = {"title": title, "summary": summary}
                if not _item_matches_keywords(mock_entry, keywords):
                    continue

                items.append(
                    {
                        "title": title,
                        "url": url_item,
                        "summary": summary[:500],  # Truncate long summaries
                        "published": pub_date.strftime("%Y-%m-%d") if pub_date else "unknown",
                        "source": name,
                    }
                )

            results[name] = {
                "items": items,
                "fetched": len(feed.entries),
                "relevant": len(items),
                "error": None,
            }
            print(f"  {name}: {len(items)} relevant of {len(feed.entries)} fetched")

        except Exception as exc:
            print(f"  WARNING: Failed to fetch '{name}': {exc}", file=sys.stderr)
            results[name] = {
                "items": [],
                "fetched": 0,
                "relevant": 0,
                "error": str(exc),
            }

    return results


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------


def _format_items_for_prompt(all_items: dict) -> str:
    """Format fetched feed items into a readable block for the LLM prompt."""
    sections = []
    for source_name, data in all_items.items():
        items = data["items"]
        if not items:
            sections.append(f"### {source_name}\n(no relevant items in the past {RESEARCH_WINDOW_DAYS} days)\n")
            continue
        lines = [f"### {source_name}"]
        for i, item in enumerate(items, 1):
            lines.append(f"\n{i}. [{item['published']}] {item['title']}")
            lines.append(f"   URL: {item['url']}")
            if item["summary"]:
                lines.append(f"   Summary: {item['summary']}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Script generation via Claude API
# ---------------------------------------------------------------------------


def generate_script(date_str: str, all_items: dict, api_key: str) -> dict:
    """
    Call Claude to select stories and generate the episode script.

    Returns:
        {
          "script": str,
          "stories_selected": list,
          "sources_consulted": list,
          "model": str,
        }
    """
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    # Check we have something to work with
    total_items = sum(d["relevant"] for d in all_items.values())
    all_errored = all(d["error"] is not None for d in all_items.values())

    if all_errored:
        print(
            "ERROR: All RSS feeds failed to load. Cannot generate episode without research data.",
            file=sys.stderr,
        )
        sys.exit(1)

    if total_items == 0:
        print(
            "WARNING: No relevant items found in the past "
            f"{RESEARCH_WINDOW_DAYS} days across all sources.",
            file=sys.stderr,
        )
        # Allow the LLM to explain there's no news rather than fail hard

    items_text = _format_items_for_prompt(all_items)

    # Parse the full date for the script intro
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        full_date = dt.strftime("%A, %B %-d, %Y")
    except (ValueError, AttributeError):
        full_date = date_str

    prompt = f"""\
Today is {full_date} ({date_str}).

Below are recent items fetched from authoritative sources. \
Select 2-4 of the strongest DBA/DBRE-relevant developments and write the episode script.

{items_text}

Return your response as valid JSON — no markdown fences, no extra text — \
with exactly this structure:
{{
  "stories_selected": [
    {{
      "title": "story title",
      "url": "source URL",
      "source": "source name",
      "category": "Aurora PostgreSQL | Aurora MySQL | SQL Server | General DBA",
      "dba_relevance": "one sentence on why DBAs need to know this"
    }}
  ],
  "script": "the complete spoken episode script, approximately 650-700 words"
}}"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=EDITORIAL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()

    # Parse JSON (handle occasional markdown fences from the model)
    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            print(f"ERROR: Could not parse JSON from model response:\n{response_text[:600]}", file=sys.stderr)
            sys.exit(1)

    return {
        "script": result.get("script", ""),
        "stories_selected": result.get("stories_selected", []),
        "sources_consulted": [
            {
                "source": name,
                "feed_url": next((s["url"] for s in SOURCES if s["name"] == name), ""),
                "items_fetched": data["fetched"],
                "items_relevant": data["relevant"],
                "error": data["error"],
            }
            for name, data in all_items.items()
        ],
        "model": MODEL,
    }


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def write_outputs(output_dir: Path, date_str: str, script: str, research_data: dict) -> None:
    """Write script.txt and sources.json to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "script.txt").write_text(script, encoding="utf-8")

    sources = {
        "episode_date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **research_data,
        "script_word_count": len(script.split()),
    }
    (output_dir / "sources.json").write_text(
        json.dumps(sources, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research authoritative database news and generate episode script."
    )
    parser.add_argument("--date", required=True, help="Episode date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", required=True, help="Directory to write script.txt and sources.json")
    args = parser.parse_args()

    date_str = args.date
    output_dir = Path(args.output_dir)

    # Manual override: use supplied script, skip research entirely
    script_override = os.environ.get("EPISODE_SCRIPT", "").strip()
    if script_override:
        print(f"Manual script override: {len(script_override.split())} words")
        write_outputs(
            output_dir,
            date_str,
            script_override,
            {
                "mode": "manual_override",
                "sources_consulted": [],
                "stories_selected": [],
                "model": None,
            },
        )
        print(f"Outputs written to: {output_dir}")
        return

    # Automated research
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY is not set. "
            "Add it as a GitHub Actions secret or supply EPISODE_SCRIPT for a manual override.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Fetching research feeds (window: {RESEARCH_WINDOW_DAYS} days)...")
    all_items = fetch_all_feeds()

    print("Generating script via Claude API...")
    result = generate_script(date_str, all_items, api_key)

    script = result["script"]
    word_count = len(script.split())
    print(f"Script generated: {word_count} words")

    if word_count < MIN_SCRIPT_WORDS:
        print(
            f"ERROR: Generated script is too short ({word_count} words, minimum {MIN_SCRIPT_WORDS}). "
            "Check the LLM response or source availability.",
            file=sys.stderr,
        )
        sys.exit(1)

    write_outputs(
        output_dir,
        date_str,
        script,
        {
            "mode": "automated_research",
            "sources_consulted": result["sources_consulted"],
            "stories_selected": result["stories_selected"],
            "model": result["model"],
        },
    )
    print(f"Outputs written to: {output_dir}")
    print(f"Stories selected  : {len(result['stories_selected'])}")


if __name__ == "__main__":
    main()
