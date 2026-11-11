# Security Policy

## Repository Status

**This repository is intentionally PUBLIC.**

All files committed here must be safe for anyone on the internet to read.

## Secrets and Credentials

**Never commit** any of the following to this repository, its Git history,
generated files, logs, documentation, examples, test fixtures, RSS metadata,
or source code:

- Passwords or passphrases
- API keys or API secrets
- Access tokens or bearer tokens
- OAuth credentials or refresh tokens
- GitHub tokens (personal access tokens, fine-grained tokens)
- Claude / Anthropic API credentials
- YouTube API credentials or OAuth tokens
- Cloud provider credentials (AWS, GCP, Azure)
- Private keys or certificates (`.pem`, `.key`, `.p12`)
- Browser cookies or session data
- Personal authentication information
- Real email passwords, App Passwords, or usernames/password combinations
  (e.g. `GMAIL_APP_PASSWORD`)
- Secrets belonging to any external service

Use **GitHub Actions Secrets** for any credentials required by CI/CD workflows.
Reference them as `${{ secrets.MY_SECRET }}` — they are never echoed into logs.

Use placeholder values such as `YOUR_API_KEY_HERE` in examples and documentation.

## Pre-Commit Checks

Before every commit, run the secret scanner:

```bash
python scripts/scan_secrets.py
```

This script inspects the working tree for common secret patterns.
If anything suspicious is detected, **do not commit** until the issue is resolved.

## If a Secret Is Accidentally Committed

Do NOT simply delete the secret and push a new commit. The secret will remain
in Git history and must be treated as compromised.

Steps:
1. Immediately revoke/rotate the exposed credential in the originating service.
2. Contact the repository owner to discuss history rewriting if necessary.
3. Use `git filter-repo` or BFG Repo Cleaner to scrub history — this rewrites
   history and requires all collaborators to re-clone.
4. Force-push the cleaned history (requires repository admin access).

## Reporting Security Issues

This is a personal podcast infrastructure project. If you discover a security
issue, please open a GitHub Issue describing the problem (without including
any actual secrets or exploit payloads).

## Dependency Security

Python dependencies are minimal and use the standard library only (for core
scripts). If third-party packages are added, they should be pinned in
`requirements.txt` and reviewed for known vulnerabilities before use.
