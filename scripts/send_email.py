#!/usr/bin/env python3
"""
send_email.py - Send the rendered digest as an email via Gmail SMTP.

Builds a multipart/alternative message (plain-text fallback + HTML body)
and sends it over STARTTLS using a Gmail address and App Password.

Usage:
    python scripts/send_email.py \\
        --html-file   /tmp/episode_generated/episode.html \\
        --script-file /tmp/episode_generated/script.txt \\
        --subject     "Database Daily - 2026-08-11 - ..."

Environment:
    GMAIL_ADDRESS      required - the sending Gmail account
    GMAIL_APP_PASSWORD required - a Google App Password for that account
    EMAIL_TO           optional - recipient address (default: GMAIL_ADDRESS, i.e. self-send)

No external dependencies — uses Python standard library only.

Exit codes:
    0 - email sent
    1 - error (missing config, or the send itself failed)
"""

import argparse
import os
import smtplib
import ssl
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5


def build_message(subject: str, from_addr: str, to_addr: str, html_body: str, text_body: str) -> MIMEMultipart:
    """Build a multipart/alternative email message (plain text + HTML)."""
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = to_addr
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))
    return message


def _send_once(message: MIMEMultipart, address: str, app_password: str) -> None:
    """Send the message via a single STARTTLS connection. Raises on failure."""
    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=context)
        server.login(address, app_password)
        server.send_message(message)


def send(message: MIMEMultipart, address: str, app_password: str) -> None:
    """Send the message, retrying on transient connection failures.

    Implicit-SSL (port 465) connections to Gmail intermittently drop from
    GitHub-hosted runners ("Connection unexpectedly closed"); STARTTLS on
    587 is more reliable, but a short retry still guards against one-off
    network blips.
    """
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _send_once(message, address, app_password)
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
        description="Send the rendered digest as an email via Gmail SMTP."
    )
    parser.add_argument("--html-file", required=True, help="Path to the rendered HTML email")
    parser.add_argument("--script-file", required=True, help="Path to script.txt (plain-text fallback)")
    parser.add_argument("--subject", required=True, help="Email subject line")
    args = parser.parse_args()

    address = os.environ.get("GMAIL_ADDRESS", "").strip()
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    to_addr = os.environ.get("EMAIL_TO", "").strip() or address

    if not address or not app_password:
        print(
            "ERROR: GMAIL_ADDRESS and GMAIL_APP_PASSWORD must both be set.",
            file=sys.stderr,
        )
        sys.exit(1)

    html_body = Path(args.html_file).read_text(encoding="utf-8")
    text_body = Path(args.script_file).read_text(encoding="utf-8")

    message = build_message(args.subject, address, to_addr, html_body, text_body)

    try:
        send(message, address, app_password)
    except Exception as exc:
        print(f"ERROR: Failed to send email: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Email sent: '{args.subject}' -> {to_addr}")


if __name__ == "__main__":
    main()
