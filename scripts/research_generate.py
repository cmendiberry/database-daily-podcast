#!/usr/bin/env python3
"""
research_generate.py - Research authoritative database news and generate episode script.

FLOW (automated):
  1. Load previously used source URLs/titles from episodes/*/sources.json (dedup)
  2. Fetch RSS feeds for discovery
  3. Filter by keywords, age window, and cross-episode deduplication
  4. Fetch primary source page content for each candidate
  5. Drop candidates whose source page cannot be retrieved or is too thin
  6. Call Claude with full primary-source content (not just RSS summaries)
  7. Validate script length (600–750 words); retry once if outside range
  8. Write script.txt and sources.json

FLOW (manual override via EPISODE_SCRIPT env var):
  Skip all research and API calls. Write the supplied text directly.

Usage:
    python scripts/research_generate.py --date YYYY-MM-DD --output-dir /tmp/dir
    EPISODE_SCRIPT="..." python scripts/research_generate.py --date YYYY-MM-DD --output-dir /tmp/dir

Environment:
    ANTHROPIC_API_KEY   required for automated research
    EPISODE_SCRIPT      if non-empty, bypasses research entirely
    EPISODES_DIR        path to episodes directory (default: episodes)

Exit codes:
    0 - success
    1 - error
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Sources — authoritative primary sources only
#
# PostgreSQL and MySQL upstream feeds are intentionally excluded.
# Aurora-relevant PostgreSQL/MySQL news comes through AWS sources (AWS What's
# New, AWS Database Blog), which write specifically about Aurora-supported
# versions. Generic upstream PostgreSQL/MySQL news is not in editorial scope.
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
]

RESEARCH_WINDOW_DAYS = 7
FEED_TIMEOUT = 20
SOURCE_FETCH_TIMEOUT = 15
MAX_SOURCE_CONTENT_CHARS = 4000   # Per candidate primary source page
MIN_SOURCE_CONTENT_CHARS = 300    # Below this the page is considered insufficient
MAX_CANDIDATES_TO_FETCH = 15      # Cap to keep prompt size and fetch time reasonable
SCRIPT_MIN_WORDS = 600
SCRIPT_MAX_WORDS = 750
MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Editorial system prompt — embedded, core editorial intelligence
# ---------------------------------------------------------------------------

EDITORIAL_SYSTEM_PROMPT = """\
You are the script writer for Database Daily, a short weekday podcast for DBAs and \
DBREs responsible for production database environments.

PRIORITY ORDER for story selection:
1. AWS Aurora PostgreSQL  (highest priority)
2. AWS Aurora MySQL
3. Microsoft SQL Server
4. General DBA / DBRE operational news

AUDIENCE: Working DBAs and DBREs. Topics must be operational:
  upgrades, patching, security, authentication and authorization, backup and recovery,
  disaster recovery, high availability, replication, performance troubleshooting,
  monitoring and observability, capacity planning, storage, configuration, maintenance,
  operational automation, reliability.

DEVELOPER EXCLUSION: Reject stories primarily aimed at application developers.
The deciding question: "Does a DBA or DBRE responsible for production databases
need to know about or act on this?" If not, do not select it.
Normally reject: ORM features, SQL programming tutorials, schema design tutorials,
application framework integrations, general developer productivity features, new
programming language libraries — UNLESS they create a direct DBA/DBRE operational
impact (e.g. breaking authentication, exhausting connections, breaking TLS, or
creating a security or availability risk a DBA must address).

AURORA RESTRICTION (STRICT): Do NOT select PostgreSQL or MySQL stories unless the
source content explicitly confirms relevance to Amazon Aurora supported or compatible
versions, or directly enables Aurora upgrade or operational planning. The primary
authoritative source for Aurora PostgreSQL and Aurora MySQL news is AWS itself.
If Aurora relevance is not clearly stated in the provided source content, reject
the story. The podcast is NOT a generic PostgreSQL or MySQL news podcast.

GROUNDING RULE: Every factual claim in the script MUST be supported by the PRIMARY
SOURCE CONTENT provided below. Do not supplement from your general training knowledge.
If a specific version number, date, feature name, or technical detail is not present
in the source content, omit it rather than guess. If a candidate story's source
content is insufficient to clearly explain DBA/DBRE relevance, do not select it.

For each selected story explain in the script:
  1. What changed?
  2. Which database versions / environments are affected?
  3. Why should a DBA or DBRE care?
  4. Is there anything they should check, patch, upgrade, configure, or prepare for?

Do not merely read release notes — translate announcements into operational consequences.

TONE: Concise, technical, practical, factual, vendor-neutral.

Always state clearly when something is: preview, beta, region-specific, version-specific,
deprecated, Extended Support only, or not yet generally available.

Never present speculation as fact. Omit rather than guess.

TARGET SCRIPT LENGTH: 600–750 spoken words for a ~5 minute episode.

FORMAT: Start with a brief intro, e.g.:
  "Welcome to Database Daily. Today is [full date]. \
I'm your host, and here is what DBAs and DBREs need to know."
End with a brief outro, e.g.:
  "That is all for today's Database Daily. Stay reliable out there."

Select 2–4 of the strongest DBA/DBRE-relevant stories. Do not force one story per
category. If a category has no meaningful new development today, skip it.\
"""

# ---------------------------------------------------------------------------
# HTML utilities
# ---------------------------------------------------------------------------


def _clean_html(html: str) -> str:
    """Strip HTML tags and normalise whitespace. Used for RSS summaries."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_text(html: str, max_chars: int = MAX_SOURCE_CONTENT_CHARS) -> str:
    """
    Extract readable text from a fetched HTML page.
    Removes <script> and <style> blocks, strips remaining tags,
    normalises whitespace, and truncates to max_chars.
    """
    # Remove script / style blocks entirely
    html = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    text = re.sub(r"&#\d+;", " ", text)
    # Normalise whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Title normalisation for cross-episode deduplication
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "the a an is in on at to for of and or with new now available this that are was"
    " has have been will be from by its".split()
)


def _normalize_title(title: str) -> str:
    """
    Normalise a story title for duplicate detection.
    Lower-cases, removes punctuation, strips common stop words.
    """
    title = title.lower()
    title = re.sub(r"[^\w\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    words = [w for w in title.split() if w not in _STOP_WORDS]
    return " ".join(words)


# ---------------------------------------------------------------------------
# Feed entry date parsing
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Keyword filter
# ---------------------------------------------------------------------------


def _item_matches_keywords(entry: dict, keywords: list) -> bool:
    """Return True if entry title+summary contains at least one keyword (case-insensitive)."""
    if not keywords:
        return True
    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(kw.lower() in text for kw in keywords)


# ---------------------------------------------------------------------------
# Script length validation
# ---------------------------------------------------------------------------


def _validate_script_length(script: str) -> "tuple[bool, int]":
    """Return (is_valid, word_count). Valid range: SCRIPT_MIN_WORDS–SCRIPT_MAX_WORDS."""
    count = len(script.split())
    return (SCRIPT_MIN_WORDS <= count <= SCRIPT_MAX_WORDS), count


# ---------------------------------------------------------------------------
# Cross-episode deduplication
# ---------------------------------------------------------------------------


def load_used_stories(episodes_dir: Path) -> dict:
    """
    Scan all episodes/*/sources.json files and build a dedup set.

    Returns:
        {
          "urls": set of previously used source URLs,
          "normalized_titles": set of normalised story titles,
        }
    """
    used_urls: set = set()
    used_normalized_titles: set = set()

    if not episodes_dir.exists():
        return {"urls": used_urls, "normalized_titles": used_normalized_titles}

    for sources_file in sorted(episodes_dir.glob("*/sources.json")):
        try:
            data = json.loads(sources_file.read_text(encoding="utf-8"))
            for story in data.get("stories_selected", []):
                url = story.get("url", "").strip()
                if url:
                    used_urls.add(url)
                title = story.get("title", "").strip()
                if title:
                    norm = _normalize_title(title)
                    if norm:
                        used_normalized_titles.add(norm)
        except Exception:
            pass  # Skip malformed files silently

    return {"urls": used_urls, "normalized_titles": used_normalized_titles}


def is_duplicate(item: dict, used: dict) -> bool:
    """
    Return True if this item has already been covered in a previous episode.
    Checks exact URL match first, then normalised title match.
    """
    url = item.get("url", "").strip()
    if url and url in used["urls"]:
        return True
    title = item.get("title", "").strip()
    if title:
        norm = _normalize_title(title)
        if norm and norm in used["normalized_titles"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Primary source content fetching
# ---------------------------------------------------------------------------


def is_sufficient_content(content: "str | None") -> bool:
    """Return True if the fetched content is long enough to support a story."""
    if not content:
        return False
    return len(content.strip()) >= MIN_SOURCE_CONTENT_CHARS


def fetch_source_content(url: str, timeout: int = SOURCE_FETCH_TIMEOUT) -> "str | None":
    """
    Fetch the text content of a primary source URL.
    Returns extracted text, or None if retrieval fails or status != 200.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; DatabaseDailyBot/1.0; "
                    "podcast research bot)"
                ),
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            raw = resp.read(512 * 1024)  # Read max 512 KB
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].strip().split(";")[0].strip()
            try:
                html = raw.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                html = raw.decode("utf-8", errors="replace")
            return _extract_text(html)
    except Exception as exc:
        print(f"    fetch failed ({type(exc).__name__}): {url[:80]}", file=sys.stderr)
        return None


def fetch_candidate_content(candidates: list, timeout: int = SOURCE_FETCH_TIMEOUT) -> list:
    """
    For each candidate, fetch its primary source page.
    Returns only candidates with sufficient content; others are dropped.
    """
    result = []
    for item in candidates:
        url = item.get("url", "")
        if not url:
            continue
        content = fetch_source_content(url, timeout=timeout)
        if not is_sufficient_content(content):
            print(f"  SKIP (source unavailable/thin): {item['title'][:70]}")
            continue
        candidate = dict(item)
        candidate["full_content"] = content
        result.append(candidate)
    return result


# ---------------------------------------------------------------------------
# Feed fetching
# ---------------------------------------------------------------------------


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
            )
            if feed.get("bozo") and not feed.entries:
                raise ValueError(f"Feed parse error: {feed.get('bozo_exception', 'unknown')}")

            items = []
            for entry in feed.entries:
                pub_date = _parse_entry_date(entry)
                if pub_date and pub_date < cutoff:
                    continue
                title = entry.get("title", "")
                summary = _clean_html(entry.get("summary", ""))
                item_url = entry.get("link", "")
                mock = {"title": title, "summary": summary}
                if not _item_matches_keywords(mock, keywords):
                    continue
                items.append(
                    {
                        "title": title,
                        "url": item_url,
                        "summary": summary[:400],
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
            results[name] = {"items": [], "fetched": 0, "relevant": 0, "error": str(exc)}

    return results


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _format_candidates_for_prompt(candidates: list) -> str:
    """Format candidates (with full primary source content) for the LLM prompt."""
    if not candidates:
        return "(no candidates with retrievable primary source content)"
    sections = []
    for i, item in enumerate(candidates, 1):
        content = item.get("full_content", item.get("summary", "(no content)"))
        block = "\n".join(
            [
                f"### CANDIDATE {i}: {item['title']}",
                f"Source    : {item['source']}",
                f"Published : {item['published']}",
                f"URL       : {item['url']}",
                "",
                "PRIMARY SOURCE CONTENT:",
                content,
                f"--- END CANDIDATE {i} ---",
            ]
        )
        sections.append(block)
    return "\n\n".join(sections)


def _build_user_prompt(date_str: str, candidates: list) -> str:
    """Build the full user prompt including candidates and grounding instructions."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        full_date = f"{dt.strftime('%A, %B')} {dt.day}, {dt.year}"
    except (ValueError, AttributeError):
        full_date = date_str

    candidates_text = _format_candidates_for_prompt(candidates)

    return (
        f"Today is {full_date} ({date_str}).\n\n"
        f"The following {len(candidates)} candidate stories have been retrieved from "
        "authoritative primary sources. Their full page content is provided.\n\n"
        "REMINDER — GROUNDING RULE: Every factual claim in the script must come from "
        "the PRIMARY SOURCE CONTENT below. Do not fill gaps from general knowledge. "
        "If a fact is not in the source content, omit it. If a candidate's content "
        "is insufficient to explain DBA/DBRE relevance, do not select it.\n\n"
        f"{candidates_text}\n\n"
        "Select 2–4 of the strongest DBA/DBRE-relevant stories. "
        "Write the complete episode script (600–750 words).\n\n"
        "Return valid JSON only — no markdown fences, no extra text:\n"
        "{\n"
        '  "stories_selected": [\n'
        "    {\n"
        '      "title": "story title",\n'
        '      "url": "source URL",\n'
        '      "source": "source name",\n'
        '      "published": "YYYY-MM-DD",\n'
        '      "category": "Aurora PostgreSQL | Aurora MySQL | SQL Server | General DBA",\n'
        '      "dba_relevance": "one sentence on why DBAs need to know this"\n'
        "    }\n"
        "  ],\n"
        '  "script": "the complete spoken episode script"\n'
        "}"
    )


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------


def _call_claude(client, messages: list, system: str) -> str:
    """Make a single Claude API call. Returns raw response text."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=system,
        messages=messages,
    )
    return message.content[0].text.strip()


def _parse_json_response(response_text: str) -> dict:
    """Parse JSON from a Claude response, handling markdown fences."""
    text = response_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON from model response: {text[:500]}")


def generate_script(date_str: str, candidates: list, api_key: str) -> dict:
    """
    Call Claude to select stories and write the episode script.
    Validates length (600–750 words); retries once with correction if out of range.

    Returns:
        {"script": str, "stories_selected": list, "model": str}
    """
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic not installed. Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    user_prompt = _build_user_prompt(date_str, candidates)
    messages = [{"role": "user", "content": user_prompt}]

    # --- Attempt 1 ---
    print("  LLM attempt 1...")
    response_text = _call_claude(client, messages, EDITORIAL_SYSTEM_PROMPT)

    try:
        result = _parse_json_response(response_text)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: JSON parse failed on attempt 1: {exc}", file=sys.stderr)
        sys.exit(1)

    script = result.get("script", "")
    valid, word_count = _validate_script_length(script)

    if not valid:
        # --- Retry with length correction ---
        direction = (
            "shorter — cut non-essential content"
            if word_count > SCRIPT_MAX_WORDS
            else "longer — expand operational guidance and DBA action items"
        )
        correction = (
            f"Your script has {word_count} words. "
            f"The required range is {SCRIPT_MIN_WORDS}–{SCRIPT_MAX_WORDS} words. "
            f"Please rewrite it to be {direction}. "
            "Keep all selected stories and their source URLs. "
            "Return the complete JSON structure with the corrected script."
        )
        messages = messages + [
            {"role": "assistant", "content": response_text},
            {"role": "user", "content": correction},
        ]
        print(
            f"  Script: {word_count} words — outside {SCRIPT_MIN_WORDS}–{SCRIPT_MAX_WORDS}. "
            "Retrying..."
        )
        response_text = _call_claude(client, messages, EDITORIAL_SYSTEM_PROMPT)

        try:
            result = _parse_json_response(response_text)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: JSON parse failed on retry: {exc}", file=sys.stderr)
            sys.exit(1)

        script = result.get("script", "")
        valid, word_count = _validate_script_length(script)

        if not valid:
            print(
                f"ERROR: Script has {word_count} words after retry "
                f"(required: {SCRIPT_MIN_WORDS}–{SCRIPT_MAX_WORDS}). "
                "Failing safely — episode will not be published.",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"  Script: {word_count} words (valid: {SCRIPT_MIN_WORDS}–{SCRIPT_MAX_WORDS})")
    return {
        "script": script,
        "stories_selected": result.get("stories_selected", []),
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
    parser.add_argument(
        "--output-dir", required=True, help="Directory to write script.txt and sources.json"
    )
    args = parser.parse_args()

    date_str = args.date
    output_dir = Path(args.output_dir)

    # Manual override: use supplied script, skip all research
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

    episodes_dir = Path(os.environ.get("EPISODES_DIR", "episodes"))

    # 1. Load cross-episode dedup data
    print("Loading cross-episode deduplication data...")
    used_stories = load_used_stories(episodes_dir)
    print(
        f"  Previously covered: {len(used_stories['urls'])} URLs, "
        f"{len(used_stories['normalized_titles'])} titles (normalized)"
    )

    # 2. Fetch RSS feeds
    print(f"Fetching research feeds (window: {RESEARCH_WINDOW_DAYS} days)...")
    all_items = fetch_all_feeds()

    all_errored = all(d["error"] is not None for d in all_items.values())
    if all_errored:
        print(
            "ERROR: All RSS feeds failed. Cannot generate episode without research data.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Collect and deduplicate candidates
    candidates = []
    skipped_dedup = 0
    for data in all_items.values():
        for item in data["items"]:
            if is_duplicate(item, used_stories):
                print(f"  DEDUP: {item['title'][:70]}")
                skipped_dedup += 1
            else:
                candidates.append(item)

    # Sort most-recent first, cap at MAX_CANDIDATES_TO_FETCH
    candidates.sort(key=lambda x: x.get("published", ""), reverse=True)
    if len(candidates) > MAX_CANDIDATES_TO_FETCH:
        print(
            f"  Capping at {MAX_CANDIDATES_TO_FETCH} most recent "
            f"(of {len(candidates)} after dedup)"
        )
        candidates = candidates[:MAX_CANDIDATES_TO_FETCH]

    print(f"Candidates after dedup: {len(candidates)} (excluded {skipped_dedup} duplicates)")

    # 4. Fetch primary source content
    print("Fetching primary source content...")
    candidates_with_content = fetch_candidate_content(candidates)
    print(f"Candidates with sufficient content: {len(candidates_with_content)}")

    if not candidates_with_content:
        print(
            "ERROR: No candidates with retrievable primary source content. "
            "Cannot generate episode.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 5. Generate script
    print("Generating script via Claude API...")
    result = generate_script(date_str, candidates_with_content, api_key)

    # 6. Write outputs
    sources_consulted = [
        {
            "source": name,
            "feed_url": next((s["url"] for s in SOURCES if s["name"] == name), ""),
            "items_fetched": data["fetched"],
            "items_relevant": data["relevant"],
            "error": data["error"],
        }
        for name, data in all_items.items()
    ]
    write_outputs(
        output_dir,
        date_str,
        result["script"],
        {
            "mode": "automated_research",
            "sources_consulted": sources_consulted,
            "stories_selected": result["stories_selected"],
            "model": result["model"],
            "research_stats": {
                "candidates_after_dedup": len(candidates),
                "candidates_with_content": len(candidates_with_content),
                "skipped_dedup": skipped_dedup,
            },
        },
    )
    print(f"Outputs written to: {output_dir}")
    print(f"Stories selected  : {len(result['stories_selected'])}")


if __name__ == "__main__":
    main()
