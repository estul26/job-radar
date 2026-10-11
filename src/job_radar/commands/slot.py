"""Decide whether a daily-jobs.yml run should scan, and for which morning/evening slot.

GitHub schedules each slot twice (a 30-minute fallback) and the Mac launchd
trigger backs both up, so the first successful scan of a slot records a claim
(data/radar_<slot>_claim.txt) and later triggers for that slot skip.

A scheduled run before noon (in the cron's own hour) is the morning scan, any
other the evening scan, so the scan times live only in daily-jobs.yml. Dates are
in the `timezone` of config/search_config.yaml. Standard library only: the
workflow runs this before installing anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE_KEY = re.compile(r"""^timezone:\s*["']?([^"'#\s]+)""", re.MULTILINE)


def config_timezone(config_path: Path) -> ZoneInfo:
    """The top-level `timezone:` of search_config.yaml, read without PyYAML; UTC when unset."""
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    match = TIMEZONE_KEY.search(text)
    return ZoneInfo(match.group(1) if match else "UTC")


def _cron_hour(schedule: str) -> int | None:
    parts = schedule.split()
    return int(parts[1]) if len(parts) == 5 and parts[1].isdigit() else None


@dataclass(frozen=True)
class SlotDecision:
    skip: bool
    slot: str  # "morning", "evening", or "" for a manual scan outside both windows
    date: str  # the local date the slot belongs to
    check_claim: bool
    reason: str


def decide_slot(event: str, schedule: str, ref: str, skip_if_done: bool, now: datetime, tz: ZoneInfo) -> SlotDecision:
    """Pick the slot from the trigger alone; claims are checked afterwards by check_claim()."""
    local = now.astimezone(tz)
    day = local.date()
    slot = ""
    check_claim = False
    cron_hour = _cron_hour(schedule) if event == "schedule" else None

    if cron_hour is not None and cron_hour < 12:
        slot, check_claim = "morning", True
    elif cron_hour is not None:
        slot, check_claim = "evening", True
        if local.hour < 12:
            # An evening event delayed past midnight still belongs to yesterday.
            day -= timedelta(days=1)
    elif event == "workflow_dispatch":
        if ref == "refs/heads/main":
            if local.hour < 12:
                slot = "morning"
            elif local.hour >= 15:
                slot = "evening"
        if skip_if_done:
            check_claim = True
            if not slot:
                return SlotDecision(
                    True,
                    "",
                    day.isoformat(),
                    False,
                    "Backup trigger fired outside the morning/evening windows; nothing to back up.",
                )

    reason = f"Running the {slot} scan for {day.isoformat()}." if slot else "Running a manual scan."
    return SlotDecision(False, slot, day.isoformat(), check_claim, reason)


def claim_path(data_dir: Path, slot: str) -> Path:
    return data_dir / f"radar_{slot}_claim.txt"


def check_claim(decision: SlotDecision, data_dir: Path) -> SlotDecision:
    """Skip when this slot's scan already completed for the day."""
    if not decision.check_claim or not decision.slot:
        return decision
    path = claim_path(data_dir, decision.slot)
    if path.exists() and path.read_text(encoding="utf-8").strip() == decision.date:
        return replace(
            decision,
            skip=True,
            reason=f"The {decision.slot} scan already completed for {decision.date}; skipping this duplicate trigger.",
        )
    return decision


def record_claim(data_dir: Path, slot: str, date: str) -> Path:
    path = claim_path(data_dir, slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{date}\n", encoding="utf-8")
    return path
