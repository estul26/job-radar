"""Which postings the scan has already seen (data/seen_jobs.json).

Entries are only ever added, never rewritten, so a scan's commit touches just the
lines of jobs it found for the first time. Entries older than the retention
window are dropped; by then the job boards no longer list the posting.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SEEN_RETENTION = timedelta(days=90)


def load_seen(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_seen(path: str | Path, seen: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_seen(seen: dict[str, Any], jobs: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """Record jobs seen for the first time; jobs already recorded stay exactly as they are."""
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    for job in jobs:
        seen.setdefault(
            job["fingerprint"],
            {
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "job_url": job.get("job_url", ""),
                "first_seen": timestamp,
            },
        )
    return seen


def prune_seen(seen: dict[str, Any], now: datetime | None = None, keep: timedelta = SEEN_RETENTION) -> dict[str, Any]:
    """Drop entries first seen longer ago than keep (and the old, constantly rewritten last_seen field)."""
    cutoff = (now or datetime.now(timezone.utc)) - keep
    pruned: dict[str, Any] = {}
    for fingerprint, entry in seen.items():
        try:
            first_seen = datetime.fromisoformat(str(entry.get("first_seen", "")))
        except ValueError:
            first_seen = None
        if first_seen is not None and first_seen < cutoff:
            continue
        pruned[fingerprint] = {key: value for key, value in entry.items() if key != "last_seen"}
    return pruned
