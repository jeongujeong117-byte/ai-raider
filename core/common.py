"""Shared repository paths and clock helpers for core/ and agents/.

ROOT is the repository root (the parent of this package), never the package folder.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PRIVATE = ROOT / ".private"
UTC = timezone.utc
KST = timezone(timedelta(hours=9))


def now():
    return datetime.now(UTC)
