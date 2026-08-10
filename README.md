# Database Daily

A short weekday podcast briefing covering the latest important news in
**Amazon Aurora**, **Microsoft SQL Server**, and **PostgreSQL** — with a
quick explanation of why each story matters.

Target length: approximately 5 minutes per episode, published every weekday morning.

> **Repository status:** This repository is intentionally **PUBLIC**.
> All committed files are safe for anyone on the internet to read.
> See [SECURITY.md](SECURITY.md) before making any changes.

---

## Table of Contents

1. [Repository Structure](#repository-structure)
2. [How RSS Publishing Works](#how-rss-publishing-works)
3. [GitHub Pages Decision](#github-pages-decision)
4. [What Is Public](#what-is-public)
5. [Where Secrets Go](#where-secrets-go)
6. [Adding a New Episode (Manual)](#adding-a-new-episode-manual)
7. [Adding a New Episode (Automation)](#adding-a-new-episode-automation)
8. [Episode Structure](#episode-structure)
9. [YouTube Music / YouTube Podcasts Setup](#youtube-music--youtube-podcasts-setup)
10. [Manual Configuration Checklist](#manual-configuration-checklist)
11. [Local Development](#local-development)
12. [Running Tests](#running-tests)
13. [Running the Secret Scanner](#running-the-secret-scanner)

---

## Repository Structure

```
database-daily-podcast/
│
├── .gitignore                    # Excludes secrets, credentials, caches
├── .github/
│   └── workflows/
│       └── validate.yml          # CI: secret scan + tests + Pages deploy
│
├── SECURITY.md                   # Security policy and credential handling
├── README.md                     # This file
├── requirements.txt              # Python dependencies (pyyaml, pytest)
├── podcast.yaml                  # Podcast-level configuration (NO secrets)
│
├── feed.xml                      # Generated RSS feed (committed, served via Pages)
│
├── cover-art/
│   ├── README.md                 # Instructions for adding cover art
│   └── cover.jpg                 # Podcast cover art (add this manually)
│
├── episodes/
│   └── YYYY-MM-DD/               # One directory per episode
│       ├── audio.mp3             # Episode audio file
│       └── metadata.yaml         # Episode title, date, description, GUID, etc.
│
├── scripts/
│   ├── generate_feed.py          # Reads metadata, writes feed.xml
│   ├── add_episode.py            # Helper: copy audio + write metadata.yaml
│   └── scan_secrets.py           # Pre-commit secret scanner
│
└── tests/
    ├── test_feed.py              # Full test suite (no real credentials needed)
    └── fixtures/
        └── create_test_audio.py  # Generates minimal valid MP3 for tests
```

---

## How RSS Publishing Works

### Flow

```
1. Episode MP3 is generated
         |
         v
2. scripts/add_episode.py
   - Creates episodes/YYYY-MM-DD/
   - Copies audio.mp3 there
   - Writes metadata.yaml
         |
         v
3. scripts/generate_feed.py
   - Reads podcast.yaml (channel config)
   - Scans all episodes/*/metadata.yaml
   - Sorts episodes newest-first
   - Writes feed.xml at the repo root
         |
         v
4. git add episodes/YYYY-MM-DD/ feed.xml
   git commit -m "episode: add 2026-08-10"
   git push
         |
         v
5. GitHub Actions (validate.yml) runs:
   - Secret scanner
   - Feed validation
   - Test suite
   - Deploys to GitHub Pages
         |
         v
6. feed.xml is publicly accessible at:
   https://YOUR_GITHUB_USERNAME.github.io/database-daily-podcast/feed.xml
```

### Feed format

`feed.xml` is a standards-compliant RSS 2.0 feed with the iTunes podcast
namespace (`http://www.itunes.com/dtds/podcast-1.0.dtd`) and Podcasting 2.0
namespace. It includes:

- `<title>`, `<description>`, `<language>`, `<link>`
- `<itunes:author>`, `<itunes:type>`, `<itunes:explicit>`, `<itunes:image>`
- `<itunes:owner>` block (uses `noreply@example.com`, no real email)
- Per episode: `<title>`, `<description>`, `<pubDate>` (RFC 2822), `<guid>`,
  `<enclosure url="..." length="..." type="audio/mpeg">`,
  `<itunes:duration>`, `<itunes:episode>`

### Episode metadata format

Each episode's `metadata.yaml`:

```yaml
title: "Database Daily - 2026-08-10"
date: "2026-08-10T07:00:00+00:00"    # ISO 8601 with timezone
description: |
  Today: Aurora PostgreSQL 16.4 patch addresses CVE-2026-XXXXX...
  SQL Server 2025 CU1 released with 47 fixes...
  PostgreSQL 17 RC1 is out...
  Why this matters: ...
audio_file: "audio.mp3"
duration: "5:12"                     # MM:SS or H:MM:SS
episode_number: 1
season: 1
explicit: false
guid: "database-daily-2026-08-10"    # Immutable - never change after publishing
```

**The `guid` must never be changed after an episode is published.** Podcast
clients use it to track which episodes a listener has already heard.

---

## GitHub Pages Decision

### Decision: GitHub Pages from main branch root

The RSS feed and all episode audio files are served directly from GitHub Pages.

**Why this works for this podcast:**

| Factor | Detail |
|--------|--------|
| Audio size | ~5 MB per 5-minute episode at 128 kbps |
| Episodes/month | ~22 |
| Monthly audio added | ~110 MB/month |
| GitHub repo soft limit | 1 GB |
| GitHub Pages bandwidth | 100 GB/month soft limit |
| Cost | Zero |

At ~110 MB/month, the repository will approach the 1 GB soft limit after
approximately 9 months of episodes. GitHub's limits are soft recommendations,
not hard cutoffs — the repository can grow beyond 1 GB. When the repo grows
large, options include:

- Migrate audio to a free object storage service (Cloudflare R2, Backblaze B2)
  and update only the RSS feed via Pages — the feed remains tiny forever.
- Use Git LFS for audio files (adds cost above 1 GB/month free tier).
- Archive old episodes out of the repo while keeping them accessible via a
  redirecting URL.

**What is NOT stored in the repo:**
- No databases, no Docker, no AWS, no paid infrastructure.
- The entire system runs on GitHub's free tier.

### URL structure

Once configured:

| Resource | URL |
|----------|-----|
| RSS feed | `https://YOUR_GITHUB_USERNAME.github.io/database-daily-podcast/feed.xml` |
| Episode audio | `https://YOUR_GITHUB_USERNAME.github.io/database-daily-podcast/episodes/YYYY-MM-DD/audio.mp3` |
| Cover art | `https://YOUR_GITHUB_USERNAME.github.io/database-daily-podcast/cover-art/cover.jpg` |

---

## What Is Public

Because this repository is public, the following information is visible to anyone:

- All episode audio files (MP3s)
- All episode metadata (titles, dates, descriptions)
- The RSS feed (`feed.xml`)
- All scripts and configuration
- The podcast cover art
- Git commit history (including commit messages and author info)

**This is intentional.** The podcast is designed for RSS distribution, which
requires publicly accessible URLs for all assets.

**What is NOT in the repository:**
- API keys of any kind
- Authentication tokens
- Cloud credentials
- Email passwords
- Any personal or private information

---

## Where Secrets Go

This podcast infrastructure requires **no runtime secrets** for the core workflow
(generate → commit → push → Pages).

If future features require credentials, they go in **GitHub Actions Secrets**:

| Future feature | Where the secret lives |
|----------------|------------------------|
| Claude API (episode generation) | `ANTHROPIC_API_KEY` in repo Secrets |
| YouTube Data API | `YOUTUBE_API_KEY` in repo Secrets |
| Custom domain TLS | Configured in GitHub Pages settings, not in repo |

**Never** put secrets in:
- `podcast.yaml`
- Any `metadata.yaml`
- Any script
- Any workflow YAML (use `${{ secrets.MY_SECRET }}` references only)
- The RSS feed
- Commit messages

---

## Adding a New Episode (Manual)

```bash
# 1. Create episode directory and add audio
mkdir -p episodes/2026-08-11
cp /path/to/audio.mp3 episodes/2026-08-11/audio.mp3

# 2. Create metadata.yaml
cat > episodes/2026-08-11/metadata.yaml << 'EOF'
title: "Database Daily - 2026-08-11"
date: "2026-08-11T07:00:00+00:00"
description: |
  Today: ...
audio_file: "audio.mp3"
duration: "5:08"
episode_number: 2
season: 1
explicit: false
guid: "database-daily-2026-08-11"
EOF

# 3. Regenerate feed
python scripts/generate_feed.py

# 4. Scan for secrets (required before commit)
python scripts/scan_secrets.py

# 5. Commit and push
git add episodes/2026-08-11/ feed.xml
git commit -m "episode: add 2026-08-11"
git push
```

---

## Adding a New Episode (Automation)

The `add_episode.py` script is designed for the future automation agent:

```bash
python scripts/add_episode.py \
    --audio /path/to/generated.mp3 \
    --date 2026-08-11 \
    --title "Database Daily - 2026-08-11" \
    --description "Today we cover Aurora PostgreSQL 16.5, SQL Server 2025 CU2..." \
    --duration "5:08" \
    --episode-number 2 \
    --update-feed
```

Then commit and push:

```bash
python scripts/scan_secrets.py
git add episodes/2026-08-11/ feed.xml
git commit -m "episode: add 2026-08-11"
git push
```

---

## Episode Structure

Each episode targets approximately 5 minutes. Suggested structure:

1. **Introduction** (10-15 sec) — brief welcome
2. **Amazon Aurora news** — new releases, security, performance, pricing
3. **SQL Server news** — SQL Server only (not Azure SQL DB/MI unless directly related)
4. **PostgreSQL news** — core, security, major extensions, ecosystem
5. **Cross-database item** (optional) — only if genuinely important
6. **Why this matters** — brief analysis of the most important item(s)
7. **Closing** (5-10 sec)

Quality rules:
- Prioritize genuinely new information; skip yesterday's stories
- Prefer primary sources (official blogs, release notes, CVE databases)
- Distinguish announcements from actual releases
- Distinguish rumors from confirmed information
- Never invent a story or fabricate a source
- If there is little news, make a shorter episode rather than padding

---

## YouTube Music / YouTube Podcasts Setup

YouTube Podcasts (available in select regions via YouTube Studio) ingests
standard RSS feeds. As of 2025:

### RSS feed requirements for YouTube

| Requirement | Status |
|-------------|--------|
| RSS 2.0 with `<enclosure>` | Included in `feed.xml` |
| `<itunes:image>` (min 1400x1400 px) | Included; add cover.jpg manually |
| Audio file publicly accessible | Yes, via GitHub Pages |
| `<itunes:explicit>` | Included (`false`) |
| `<itunes:category>` | Included (`Technology`) |
| HTTPS URLs for all assets | Yes, GitHub Pages provides HTTPS |
| No authentication on audio URLs | Yes, GitHub Pages is fully public |

### What to configure in YouTube Studio manually

1. **Go to YouTube Studio** → **Content** → **Podcasts** (or search for it in the left nav)
2. Click **"New Podcast"** or **"Add show by RSS feed"**
3. Enter your RSS feed URL:
   ```
   https://YOUR_GITHUB_USERNAME.github.io/database-daily-podcast/feed.xml
   ```
4. YouTube will validate the feed and import existing episodes
5. New episodes are typically picked up within a few hours of the feed updating
6. You can set a custom podcast description, category, and country in YouTube Studio;
   these override the RSS values for the YouTube display

### Important YouTube notes

- YouTube Podcasts is currently limited to certain countries/regions
- YouTube does **not** host your audio — it streams from your GitHub Pages URL
- If you later change the audio URL structure, update the RSS feed first
- YouTube may cache the feed for up to a few hours; allow time for new episodes to appear
- Cover art must be square; YouTube will crop non-square images

---

## Manual Configuration Checklist

After cloning this repository, complete these steps before publishing:

- [ ] **`podcast.yaml`**: Replace `YOUR_GITHUB_USERNAME` with your real GitHub username
- [ ] **GitHub Pages**: Enable GitHub Pages in repo Settings → Pages → Source: `Deploy from a branch` or use the workflow
- [ ] **Cover art**: Add a 1400x1400 px (or larger) square JPEG as `cover-art/cover.jpg`
- [ ] **Regenerate feed**: Run `python scripts/generate_feed.py` after updating `podcast.yaml`
- [ ] **Commit feed**: Commit and push `feed.xml` and `cover-art/cover.jpg`
- [ ] **Verify feed URL**: Visit `https://YOUR_GITHUB_USERNAME.github.io/database-daily-podcast/feed.xml`
- [ ] **YouTube**: Submit feed URL in YouTube Studio → Content → Podcasts

Optional (for future automation):
- [ ] Add `ANTHROPIC_API_KEY` to GitHub Actions Secrets (for episode generation)
- [ ] Add `YOUTUBE_API_KEY` to GitHub Actions Secrets (for YouTube Data API, if needed)

---

## Local Development

```bash
# Clone
git clone https://github.com/YOUR_GITHUB_USERNAME/database-daily-podcast.git
cd database-daily-podcast

# Install dependencies
pip install -r requirements.txt

# Generate feed from existing episodes
python scripts/generate_feed.py

# Run secret scanner
python scripts/scan_secrets.py

# Run tests
pytest tests/ -v
```

---

## Running Tests

Tests require no real credentials, API keys, or external services.

```bash
pip install -r requirements.txt
pytest tests/ -v
```

The test suite:
1. Creates a minimal valid MP3 in a temp directory
2. Creates a sample episode with `metadata.yaml`
3. Generates the RSS feed
4. Validates the XML structure
5. Verifies enclosure URL, MIME type, file size, GUID, pubDate
6. Tests the empty-feed edge case
7. Tests multi-episode sorting (newest first)
8. Runs the secret scanner against the real repository

---

## Running the Secret Scanner

Always run this before committing:

```bash
python scripts/scan_secrets.py
```

Exit code `0` = clean, safe to commit.
Exit code `1` = findings detected, do NOT commit.

The scanner checks for AWS keys, GitHub tokens, Anthropic API keys,
Google API keys, generic password/token assignments, private key headers,
and connection strings with embedded credentials.

For full details, see [SECURITY.md](SECURITY.md).
