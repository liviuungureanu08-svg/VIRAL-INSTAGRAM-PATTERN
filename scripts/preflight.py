#!/usr/bin/env python3
"""Pre-run safety checks.

The single worst failure mode for this kind of pipeline is committing the OAuth
credentials it depends on — a leaked refresh token hands over write access to
the connected YouTube channel, and deleting the file later does not remove it
from git history. This runs before the pipeline and fails the build loudly.

Usage: python scripts/preflight.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that must never be tracked by git, at any path.
FORBIDDEN_NAMES = {
    "client_secrets.json",
    "credentials.json",
    "token.json",
    "token.pickle",
    ".env",
}
FORBIDDEN_PREFIXES = ("encoded_",)
FORBIDDEN_SUFFIXES = ("-service-account.json", "_secret.json", "_secrets.json")


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def check_tracked_secrets() -> list[str]:
    problems = []
    for path in _tracked_files():
        name = Path(path).name
        if name in FORBIDDEN_NAMES:
            problems.append(f"{path} is tracked by git and must not be.")
        elif name.startswith(FORBIDDEN_PREFIXES):
            problems.append(f"{path} looks like an encoded credential blob.")
        elif name.endswith(FORBIDDEN_SUFFIXES):
            problems.append(f"{path} looks like a service-account key.")
    return problems


def check_environment() -> list[str]:
    problems = []
    if not os.getenv("GOOGLE_API_KEY"):
        problems.append("GOOGLE_API_KEY is not set — content generation will fail.")
    return problems


def check_warnings() -> list[str]:
    warnings = []
    if not os.getenv("PEXELS_API_KEY"):
        warnings.append("PEXELS_API_KEY is not set — slides will use a flat backdrop.")
    if os.getenv("PRIVACY_STATUS", "unlisted") == "public":
        warnings.append(
            "PRIVACY_STATUS is 'public' — this run will publish publicly with no review."
        )
    if not (ROOT / "assets" / "music" / "bg_music.mp3").exists():
        warnings.append("No background music at assets/music/bg_music.mp3 — audio will be narration only.")
    return warnings


def main() -> int:
    print("🔍 Preflight checks...")

    problems = check_tracked_secrets() + check_environment()
    for warning in check_warnings():
        print(f"   ⚠️  {warning}")

    if problems:
        print("\n❌ Preflight failed:")
        for problem in problems:
            print(f"   - {problem}")
        print(
            "\nIf a credential was committed, rotate it immediately — removing the file "
            "does not remove it from git history."
        )
        return 1

    print("✅ Preflight passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
