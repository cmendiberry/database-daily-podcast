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
│   ├── send_email.py              # Sends episode.html via the Resend API
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
   - Fetches each candidate's primary source page (not just the RSS summary)
   - Calls Claude to select 2-4 DBA/DBRE-relevant stories and write a brief
     150-250 word overview, grounded only in the fetched primary-source content
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
   - Sends episode.html (plus a plain-text fallback) via the Resend API
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

The written overview targets 150-250 words — brief and high-level, not a
detailed walkthrough. The per-story substance lives in the HTML's "Today's
stories" cards instead, each with a source link. Structure:

1. **Greeting** — one line, names the date
2. **Brief overview** — names the 2-4 selected stories and why this week's
   news matters as a whole; no version numbers or step-by-step detail here
3. **Sign-off** — one line
4. **Story cards** (rendered separately by `generate_email_html.py`) — one
   per selected story: title linked to its source, category tag, and a
   1-2 sentence `dba_relevance` note on what changed and what to check,
   patch, or prepare for

Selected stories are Aurora PostgreSQL, Aurora MySQL, SQL Server, or general
DBA/DBRE operational news.

Quality rules (enforced by the editorial prompt in `research_generate.py`):
- Every factual claim must be grounded in the fetched primary-source content —
  never filled in from general model knowledge
- PostgreSQL/MySQL stories are only selected when AWS explicitly confirms
  Aurora relevance (this is not a generic PostgreSQL/MySQL news digest)
- Developer-only stories (ORM features, SQL tutorials, etc.) are excluded
  unless they create a direct DBA/DBRE operational impact
- If a category has no meaningful news that week, it's simply skipped

---

## Where Secrets Go

All secrets live in **GitHub Actions Secrets**, referenced in workflows as
`${{ secrets.MY_SECRET }}` — never in a script, a workflow literal, or a
committed file.

| Secret | Purpose |
|--------|---------|
| `ANTHROPIC_API_KEY` | Claude API calls for story selection + digest writing |
| `RESEND_API_KEY` | API key from a [Resend](https://resend.com) account used to send the digest |
| `EMAIL_TO` | Recipient address |
| `RESEND_FROM` | *Optional.* Sender — defaults to Resend's shared sandbox address if unset. Without a verified domain, Resend only allows sending to the address the account itself was signed up with. |

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
- [ ] Create a [Resend](https://resend.com) account, generate an API key
- [ ] Add `RESEND_API_KEY` and `EMAIL_TO` to GitHub Actions Secrets
- [ ] Without a verified domain: either sign up to Resend with the recipient
      address itself, or sign up with a separate inbox and set up mail
      forwarding from that inbox to the real recipient
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
network and HTTP API interactions are mocked.

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
