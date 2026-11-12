#!/usr/bin/env python3
"""
send_email.py - Send the rendered digest as an email via the Resend API.

Builds a JSON payload (plain-text fallback + HTML body) and POSTs it to
Resend's HTTP API. Raw SMTP (both port 465 and 587) proved unreliable from
GitHub-hosted runners -- connections to smtp.gmail.com were dropping
mid-handshake ("Connection unexpectedly closed"), most likely Google
rejecting traffic from well-known cloud/CI IP ranges. A transactional
email API avoids that entirely.

Usage:
    python scripts/send_email.py \\
        --html-file   /tmp/episode_generated/episode.html \\
        --script-file /tmp/episode_generated/script.txt \\
        --subject     "Database Daily - 2026-08-11 - ..."

Environment:
    RESEND_API_KEY  required - Resend API key
    EMAIL_TO        required - recipient address
    RESEND_FROM     optional - sender, default "Database Daily <onboarding@resend.dev>"

No external dependencies — uses Python standard library only.

Exit codes:
    0 - email sent
    1 - error (missing config, or the send itself failed)
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Database Daily <onboarding@resend.dev>"
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5


def build_payload(subject: str, from_addr: str, to_addr: str, html_body: str, text_body: str) -> dict:
    """Build the JSON payload for Resend's /emails endpoint."""
    return {
        "from": from_addr,
        "to": [to_addr],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }


def _send_once(payload: dict, api_key: str) -> None:
    """POST the payload to Resend once. Raises on any non-2xx response."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        RESEND_API_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # urllib's default "Python-urllib/3.x" User-Agent is a known bot
            # signature that Cloudflare (fronting api.resend.com) blocks with
            # a 403 (error code 1010) before the request ever reaches Resend.
            "User-Agent": "database-daily-digest/1.0 (+https://github.com/cmendiberry/database-daily-podcast)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend API error {exc.code}: {body}") from exc


def send(payload: dict, api_key: str) -> None:
    """Send via the Resend API, retrying on transient failures."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _send_once(payload, api_key)
            return
        except Exception as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                print(
                    f"  Send attempt {attempt}/{MAX_ATTEMPTS} failed ({exc}), "
                    f"retrying in {RETRY_DELAY_SECONDS}s...",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
    raise last_error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send the rendered digest as an email via the Resend API."
    )
    parser.add_argument("--html-file", required=True, help="Path to the rendered HTML email")
    parser.add_argument("--script-file", required=True, help="Path to script.txt (plain-text fallback)")
    parser.add_argument("--subject", required=True, help="Email subject line")
    args = parser.parse_args()

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    to_addr = os.environ.get("EMAIL_TO", "").strip()
    from_addr = os.environ.get("RESEND_FROM", "").strip() or DEFAULT_FROM

    if not api_key or not to_addr:
        print(
            "ERROR: RESEND_API_KEY and EMAIL_TO must both be set.",
            file=sys.stderr,
        )
        sys.exit(1)

    html_body = Path(args.html_file).read_text(encoding="utf-8")
    text_body = Path(args.script_file).read_text(encoding="utf-8")

    payload = build_payload(args.subject, from_addr, to_addr, html_body, text_body)

    try:
        send(payload, api_key)
    except Exception as exc:
        print(f"ERROR: Failed to send email: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Email sent: '{args.subject}' -> {to_addr}")


if __name__ == "__main__":
    main()
