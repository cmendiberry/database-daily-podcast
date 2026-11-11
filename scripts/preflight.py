#!/usr/bin/env python3
"""
preflight.py - Resolve episode date and perform idempotency check.

Behavior by trigger type:
  schedule         + episode already exists  -> skip=true,  exit 0 (normal no-op)
  schedule         + episode does not exist  -> skip=false, exit 0
  workflow_dispatch + episode already exists -> exit 1 (refuse to overwrite)
  workflow_dispatch + episode does not exist -> skip=false, exit 0

Writes to $GITHUB_OUTPUT:
  skip=true|false
  episode_date=YYYY-MM-DD
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def resolve_date(episode_date_input: str) -> str:
    """Return YYYY-MM-DD: use input if provided, else today in Buenos Aires time."""
    date_str = episode_date_input.strip()
    if date_str:
        return date_str
    art = timezone(timedelta(hours=-3))
    return datetime.now(art).strftime("%Y-%m-%d")


def write_github_output(skip: bool, episode_date: str) -> None:
    """Write skip and episode_date to $GITHUB_OUTPUT if the file is available."""
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as f:
        f.write(f"skip={'true' if skip else 'false'}\n")
        f.write(f"episode_date={episode_date}\n")


def write_step_summary(message: str) -> None:
    """Append message to $GITHUB_STEP_SUMMARY if available."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary_file:
        return
    with open(summary_file, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def main() -> None:
    event_name = os.environ.get("EVENT_NAME", "workflow_dispatch")
    episode_date_input = os.environ.get("EPISODE_DATE", "")
    episodes_dir = Path(os.environ.get("EPISODES_DIR", "episodes"))

    date_str = resolve_date(episode_date_input)
    ep_dir = episodes_dir / date_str

    print(f"Event      : {event_name}")
    print(f"Date       : {date_str}")
    print(f"Episode dir: {ep_dir}")

    if ep_dir.exists():
        if event_name == "schedule":
            msg = f"Episode {date_str} already exists. Scheduled publication skipped."
            print(msg)
            write_github_output(skip=True, episode_date=date_str)
            write_step_summary(
                f"## Scheduled run: episode {date_str} already published\n\n"
                "No new episode generated. Scheduled publication skipped (no-op)."
            )
            sys.exit(0)
        else:
            print(f"ERROR: Episode {date_str} already exists.", file=sys.stderr)
            print("Refusing to overwrite or create a duplicate.", file=sys.stderr)
            sys.exit(1)

    print(f"OK: No existing episode for {date_str} — proceeding.")
    write_github_output(skip=False, episode_date=date_str)


if __name__ == "__main__":
    main()
