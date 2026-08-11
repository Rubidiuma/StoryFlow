#!/usr/bin/env python3
"""Scan a directory for accidentally committed secrets.

Usage:
    python scripts/secret_scan.py .
    python scripts/secret_scan.py src/

Exit 0 if clean, 1 if any secrets found.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Patterns that indicate a real secret (not a test fixture placeholder)
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9\-_]{20,}"),           # OpenAI/Anthropic style keys
    re.compile(r"(?i)api[_\-]?key\s*[:=]\s*['\"]?[A-Za-z0-9\-_\.]{16,}"),
    re.compile(r"(?i)secret\s*[:=]\s*['\"]?[A-Za-z0-9\-_\.]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]{20,}"),
]

# Path fragments that are safe to skip
_SKIP_PATTERNS = [
    "__pycache__", ".git", ".venv", ".uv-cache",
    "uv.lock",  # lock files may contain hashes
]

# Known safe test-fixture placeholder patterns (never real keys)
_WHITELIST = [
    re.compile(r"sk-abcdefghijklmnopqrstuvwxyz"),
    re.compile(r"env-key-xyz"),
    re.compile(r"file-key-abc"),
    re.compile(r"fallback-key"),
    re.compile(r"super-secret-token"),
    re.compile(r"top-secret-key"),
]


def _is_whitelisted(line: str) -> bool:
    return any(p.search(line) for p in _WHITELIST)


def scan_directory(root: Path) -> list[tuple[Path, int, str]]:
    """Return (file, line_no, snippet) for each suspected secret."""
    findings: list[tuple[Path, int, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(skip in path.parts for skip in _SKIP_PATTERNS):
            continue
        if path.suffix in (".pyc", ".pyo", ".db", ".sqlite3"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _is_whitelisted(line):
                continue
            for pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append((path, lineno, line.strip()[:120]))
                    break
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan for accidentally committed secrets.")
    parser.add_argument("path", help="Directory to scan")
    args = parser.parse_args()
    root = Path(args.path).resolve()
    findings = scan_directory(root)
    if findings:
        print(f"❌ Found {len(findings)} potential secret(s):")
        for path, lineno, snippet in findings:
            print(f"  {path}:{lineno}: {snippet}")
        sys.exit(1)
    print("✅ No secrets found.")


if __name__ == "__main__":
    main()
