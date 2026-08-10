#!/usr/bin/env python3
"""
scan_secrets.py - Repository-wide secret scanner for Database Daily

Scans all tracked and untracked files in the repository working tree for
common secret patterns. Run this before every commit.

Usage:
    python scripts/scan_secrets.py
    python scripts/scan_secrets.py --path /path/to/scan
    python scripts/scan_secrets.py --verbose

Exit code:
    0 - No secrets detected (safe to commit)
    1 - Potential secrets found (DO NOT COMMIT)

No external dependencies — uses Python standard library only.
"""

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Patterns that strongly indicate secrets
# Each entry: (label, compiled_regex)
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    # AWS keys
    ("AWS Access Key ID",       re.compile(r"AKIA[A-Z0-9]{16}")),
    ("AWS Secret Access Key",   re.compile(r"(?i)aws[_\-.]?secret[_\-.]?(access[_\-.]?)?key\s*[=:]\s*['\"]?[A-Za-z0-9/+]{40}['\"]?")),
    # GitHub tokens
    ("GitHub Token (classic)",  re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("GitHub Token (fine-grained)", re.compile(r"github_pat_[A-Za-z0-9_]{82}")),
    ("GitHub OAuth token",      re.compile(r"gho_[A-Za-z0-9]{36}")),
    ("GitHub Actions token",    re.compile(r"ghs_[A-Za-z0-9]{36}")),
    # Anthropic / Claude
    ("Anthropic API Key",       re.compile(r"sk-ant-[A-Za-z0-9\-_]{40,}")),
    # OpenAI
    ("OpenAI API Key",          re.compile(r"sk-[A-Za-z0-9]{48}")),
    # Google API keys
    ("Google API Key",          re.compile(r"AIza[A-Za-z0-9\-_]{35}")),
    ("Google OAuth Client",     re.compile(r"[0-9]+-[A-Za-z0-9_]{32}\.apps\.googleusercontent\.com")),
    # Generic high-entropy secrets in assignments
    ("Generic API key assignment",
        re.compile(r"(?i)(api[_\-.]?key|apikey|api[_\-.]?secret)\s*[=:]\s*['\"][A-Za-z0-9\-_/+.]{16,}['\"]")),
    ("Generic password assignment",
        re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{6,}['\"]")),
    ("Generic token assignment",
        re.compile(r"(?i)(access[_\-.]?token|auth[_\-.]?token|bearer[_\-.]?token)\s*[=:]\s*['\"][A-Za-z0-9\-_/+.]{16,}['\"]")),
    ("Generic secret assignment",
        re.compile(r"(?i)(secret[_\-.]?key|client[_\-.]?secret)\s*[=:]\s*['\"][A-Za-z0-9\-_/+.]{16,}['\"]")),
    # Private key headers
    ("Private key header",      re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    # Connection strings with embedded credentials
    ("Connection string with password",
        re.compile(r"(?i)(mysql|postgresql|postgres|mongodb|redis|amqp|smtp)://[^:]+:[^@]{4,}@")),
]

# ---------------------------------------------------------------------------
# Allowlist: patterns that are safe to ignore (false positives)
# ---------------------------------------------------------------------------
ALLOWLIST_PATTERNS = [
    # Placeholder values
    re.compile(r"YOUR_[A-Z_]+_HERE"),
    re.compile(r"YOUR_GITHUB_USERNAME"),
    re.compile(r"noreply@example\.com"),
    # This script itself contains the patterns as strings — skip self
    # (handled separately by path exclusion)
    # Generic-looking but safe patterns in SECURITY.md / README
    re.compile(r"(?i)my[_\-]?secret|example[_\-]?key|sample[_\-]?token|test[_\-]?password|dummy[_\-]?api"),
    re.compile(r"(?i)password\s*[=:]\s*['\"]?(?:YOUR|PLACEHOLDER|EXAMPLE|SAMPLE|INSERT|CHANGE|REPLACE)"),
]

# ---------------------------------------------------------------------------
# File paths and extensions to skip entirely
# ---------------------------------------------------------------------------
SKIP_PATHS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
}

SKIP_EXTENSIONS = {
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".aac",  # audio
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico",  # images
    ".pdf",                                              # documents
    ".zip", ".tar", ".gz", ".bz2", ".xz",              # archives
    ".pyc", ".pyo",                                     # compiled Python
    ".so", ".dll", ".dylib",                            # binaries
}

# Files whose content we trust (patterns appear as documentation/comments)
TRUSTED_FILES = {
    "scan_secrets.py",   # this script itself
}


def should_skip(path: Path) -> bool:
    """Return True if this file/directory should not be scanned."""
    for part in path.parts:
        if part in SKIP_PATHS:
            return True
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return True
    if path.name in TRUSTED_FILES:
        return True
    return False


def is_allowlisted(line: str) -> bool:
    """Return True if the line matches a known-safe allowlist pattern."""
    for pattern in ALLOWLIST_PATTERNS:
        if pattern.search(line):
            return True
    return False


def scan_file(path: Path, verbose: bool) -> list[tuple[str, int, str, str]]:
    """
    Scan a single file for secret patterns.
    Returns list of (label, line_number, matched_text, file_path) tuples.
    """
    findings = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError) as e:
        if verbose:
            print(f"  SKIP (unreadable): {path} — {e}")
        return findings

    for line_no, line in enumerate(text.splitlines(), start=1):
        if is_allowlisted(line):
            continue
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                findings.append((label, line_no, match.group(0)[:60], str(path)))
    return findings


def scan_directory(root: Path, verbose: bool) -> list[tuple[str, int, str, str]]:
    """Recursively scan all files under root."""
    all_findings = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if should_skip(rel):
            if verbose:
                print(f"  SKIP: {rel}")
            continue
        if verbose:
            print(f"  Scanning: {rel}")
        findings = scan_file(path, verbose)
        all_findings.extend(findings)
    return all_findings


def main():
    parser = argparse.ArgumentParser(
        description="Scan repository for potential secrets. Exit 0 = clean, Exit 1 = findings."
    )
    parser.add_argument(
        "--path",
        default=str(REPO_ROOT),
        help="Directory to scan (default: repository root)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print each file as it is scanned",
    )
    args = parser.parse_args()

    scan_root = Path(args.path).resolve()
    print(f"Scanning: {scan_root}")
    print("-" * 60)

    findings = scan_directory(scan_root, args.verbose)

    print("-" * 60)
    if not findings:
        print("RESULT: CLEAN — No secrets detected.")
        print("Safe to commit.")
        sys.exit(0)
    else:
        print(f"RESULT: {len(findings)} potential secret(s) found — DO NOT COMMIT\n")
        for label, line_no, matched, file_path in findings:
            rel = Path(file_path).relative_to(scan_root)
            print(f"  [{label}]")
            print(f"    File: {rel}:{line_no}")
            print(f"    Match: {matched!r}")
            print()
        print("Resolve all findings before committing.")
        print("See SECURITY.md for guidance.")
        sys.exit(1)


if __name__ == "__main__":
    main()
