# Database Daily

A short weekly digest covering the latest important news in
**Amazon Aurora**, **Microsoft SQL Server**, and **PostgreSQL** — with a
quick explanation of why each story matters.

This is a **personal** project: every Monday, automated research produces a
short written digest, which is rendered as a pretty HTML page and emailed
directly to the owner's inbox. There is no podcast, no audio, no public
website — just an email.

> **Repository status:** This repository is intentionally **PUBLIC**.
> All committed files are safe for anyone on the internet to read.
> See [SECURITY.md](SECURITY.md) before making any changes.

---

## Table of Contents

1. [Repository Structure](#repository-structure)
2. [How It Works](#how-it-works)
3. [Episode Structure](#episode-structure)
4. [Where Secrets Go](#where-secrets-go)
5. [Triggering a Digest Manually](#triggering-a-digest-manually)
6. [Manual Configuration Checklist](#manual-configuration-checklist)
7. [Local Development](#local-development)
8. [Running Tests](#running-tests)
9. [Running the Secret Scanner](#running-the-secret-scanner)

---

## Repository Structure

```
database-daily-podcast/
│
├── .gitignore                     # Excludes secrets, credentials, caches
├── .github/
│   └── workflows/
│       ├── validate.yml           # CI: secret scan + tests (push/PR)
│       └── publish_episode.yml    # Production: research → digest → email → commit
│
├── SECURITY.md                    # Security policy and credential handling
├── README.md                      # This file
├── requirements.txt                # Core dependencies (pytest)
├── requirements-research.txt       # Research/script-generation dependencies
│
├── episodes/
│   └── YYYY-MM-DD/                # One directory per digest, audit trail only
│       ├── script.txt             # The written digest body
│       ├── sources.json           # Stories selected, URLs, model used
│       └── episode.html           # The exact HTML that was emailed
│
├── scripts/
│   ├── research_generate.py       # RSS fetch + primary-source fetch + Claude script gen
│   ├── generate_email_html.py     # Renders script.txt + sources.json -> episode.html
│   ├── send_email.py              # Sends episode.html via Gmail SMTP
│   ├── preflight.py                # Date resolution + idempotency check
│   └── scan_secrets.py            # Pre-commit secret scanner
│
└── tests/
    └── ...                         # Full test suite (no real credentials needed)
```

---

## How It Works

```
1. scripts/preflight.py
   - Resolves the episode date (today, Buenos Aires time, unless overridden)
   - Refuses to regenerate a digest that already exists
         |
         v
2. scripts/research_generate.py
   - Fetches AWS What's New, AWS Database Blog, Microsoft SQL Server Blog (RSS)
   - Dedups against every previous episodes/*/sources.json
   - Fetches each candidate's primary source page (not just the RSS summary)
   - Calls Claude to select 2-4 DBA/DBRE-relevant stories and write a
     600-750 word digest, grounded only in the fetched primary-source content
   - Writes script.txt + sources.json
         |
         v
3. scripts/generate_email_html.py
   - Renders script.txt + sources.json into a single self-contained,
     inline-styled HTML email (episode.html)
         |
         v
4. python scripts/scan_secrets.py && pytest tests/ -v
   - Both must pass before anything is sent or committed
         |
         v
5. scripts/send_email.py
   - Sends episode.html (plus a plain-text fallback) via Gmail SMTP
   - Only on success does the workflow continue to the commit step
         |
         v
6. git add episodes/YYYY-MM-DD/ && git commit && git push
   - script.txt / sources.json / episode.html are kept as an audit trail
```

Everything after step 2 fails safely: if research, rendering, tests, or the
email send fails, nothing is committed and the episode is not marked as
published — the next scheduled run will try again for the same date.

---

## Episode Structure

Each digest targets 600-750 written words. Suggested structure:

1. **Greeting** — one line, names the date
2. **2-4 selected stories** — Aurora PostgreSQL, Aurora MySQL, SQL Server,
   or general DBA/DBRE operational news
3. For each story: what changed, which versions/environments are affected,
   why a DBA/DBRE should care, and what (if anything) to check or prepare for
4. **Sign-off** — one line

Quality rules (enforced by the editorial prompt in `research_generate.py`):
- Every factual claim must be grounded in the fetched primary-source content —
  never filled in from general model knowledge
- PostgreSQL/MySQL stories are only selected when AWS explicitly confirms
  Aurora relevance (this is not a generic PostgreSQL/MySQL news digest)
- Developer-only stories (ORM features, SQL tutorials, etc.) are excluded
  unless they create a direct DBA/DBRE operational impact
- If a category has no meaningful news that day, it's simply skipped

---

## Where Secrets Go

All secrets live in **GitHub Actions Secrets**, referenced in workflows as
`${{ secrets.MY_SECRET }}` — never in a script, a workflow literal, or a
committed file.

| Secret | Purpose |
|--------|---------|
| `ANTHROPIC_API_KEY` | Claude API calls for story selection + digest writing |
| `GMAIL_ADDRESS` | The Gmail account the digest is sent from |
| `GMAIL_APP_PASSWORD` | A Google App Password for that account (requires 2-Step Verification; generate at https://myaccount.google.com/apppasswords) |
| `EMAIL_TO` | *Optional.* Recipient address — defaults to `GMAIL_ADDRESS` (self-send) if unset |

**Never** put secrets in:
- Any script or workflow YAML literal
- `sources.json`, `script.txt`, or `episode.html`
- Commit messages

---

## Triggering a Digest Manually

The production workflow (`publish_episode.yml`) runs automatically every
Monday at 08:00 America/Argentina/Buenos_Aires. To trigger it manually:

1. GitHub → **Actions** → **Publish Episode (Production)** → **Run workflow**
2. Leave `episode_date` blank to use today, or set it explicitly
3. Leave `episode_script` blank for automated research, or paste a full
   digest to bypass research entirely
4. Optionally set `episode_title` to override the auto-generated title

If a digest for that date already exists, a manual run fails loudly rather
than overwriting it.

---

## Manual Configuration Checklist

After cloning this repository, before the first real run:

- [ ] Add `ANTHROPIC_API_KEY` to GitHub Actions Secrets
- [ ] Enable 2-Step Verification on the sending Gmail account
- [ ] Generate a Google App Password and add it as `GMAIL_APP_PASSWORD`
- [ ] Add `GMAIL_ADDRESS` to GitHub Actions Secrets
- [ ] (Optional) Add `EMAIL_TO` if the recipient differs from `GMAIL_ADDRESS`
- [ ] Trigger `publish_episode.yml` manually once to confirm an email arrives

---

## Local Development

```bash
# Clone
git clone https://github.com/cmendiberry/database-daily-podcast.git
cd database-daily-podcast

# Install dependencies
pip install -r requirements.txt -r requirements-research.txt

# Run secret scanner
python scripts/scan_secrets.py

# Run tests
pytest tests/ -v

# Render a digest HTML locally from an existing episode
python scripts/generate_email_html.py \
    --script-file  episodes/2026-08-10/script.txt \
    --sources-file episodes/2026-08-10/sources.json \
    --output       /tmp/preview.html
```

---

## Running Tests

Tests require no real credentials, API keys, or external services — all
network and SMTP interactions are mocked.

```bash
pip install -r requirements.txt -r requirements-research.txt
pytest tests/ -v
```

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
