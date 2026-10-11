"""daily-jobs.yml: which trigger scans, for which slot, and when it skips."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from job_radar.commands.slot import check_claim, decide_slot, record_claim

TORONTO = ZoneInfo("America/Toronto")


def at(hour: int, minute: int = 0, day: int = 6) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TORONTO)


@pytest.mark.parametrize(
    ("event", "schedule", "ref", "skip_if_done", "now", "skip", "slot", "date", "check"),
    [
        ("schedule", "13 7 * * *", "", False, at(7, 14), False, "morning", "2026-10-06", True),
        ("schedule", "43 7 * * *", "", False, at(9, 2), False, "morning", "2026-10-06", True),
        ("schedule", "13 16 * * *", "", False, at(16, 20), False, "evening", "2026-10-06", True),
        # A delayed evening event that only runs after midnight belongs to the day before.
        ("schedule", "43 16 * * *", "", False, at(0, 30, day=7), False, "evening", "2026-10-06", True),
        # "Run workflow": always scans, recording the slot of the hour it ran in.
        ("workflow_dispatch", "", "refs/heads/main", False, at(10), False, "morning", "2026-10-06", False),
        ("workflow_dispatch", "", "refs/heads/main", False, at(13), False, "", "2026-10-06", False),
        ("workflow_dispatch", "", "refs/heads/main", False, at(18), False, "evening", "2026-10-06", False),
        ("workflow_dispatch", "", "refs/heads/feature", False, at(10), False, "", "2026-10-06", False),
        # The Mac backup trigger.
        ("workflow_dispatch", "", "refs/heads/main", True, at(7, 20), False, "morning", "2026-10-06", True),
        ("workflow_dispatch", "", "refs/heads/main", True, at(13), True, "", "2026-10-06", False),
    ],
)
def test_decide_slot(event, schedule, ref, skip_if_done, now, skip, slot, date, check):
    decision = decide_slot(event, schedule, ref, skip_if_done, now, TORONTO)
    assert (decision.skip, decision.slot, decision.date, decision.check_claim) == (skip, slot, date, check)


def test_a_claimed_slot_skips_and_another_day_does_not(tmp_path):
    record_claim(tmp_path, "morning", "2026-10-06")
    today = decide_slot("schedule", "43 7 * * *", "", False, at(7, 45), TORONTO)
    tomorrow = decide_slot("schedule", "13 7 * * *", "", False, at(7, 14, day=7), TORONTO)
    evening = decide_slot("schedule", "13 16 * * *", "", False, at(16, 14), TORONTO)

    assert check_claim(today, tmp_path).skip is True
    assert check_claim(tomorrow, tmp_path).skip is False
    assert check_claim(evening, tmp_path).skip is False


def test_manual_run_ignores_the_claim(tmp_path):
    record_claim(tmp_path, "morning", "2026-10-06")
    decision = decide_slot("workflow_dispatch", "", "refs/heads/main", False, at(10), TORONTO)
    assert check_claim(decision, tmp_path).skip is False


@pytest.mark.parametrize(
    ("schedule", "slot"), [("5 6 * * *", "morning"), ("59 11 * * *", "morning"), ("0 12 * * *", "evening")]
)
def test_the_cron_hour_decides_the_slot(schedule, slot):
    assert decide_slot("schedule", schedule, "", False, at(13), TORONTO).slot == slot


def test_the_timezone_comes_from_the_config(tmp_path):
    from job_radar.commands.slot import config_timezone

    path = tmp_path / "search_config.yaml"
    path.write_text("# timezone: Europe/Paris\ntimezone: 'Asia/Kolkata' # mine\nsearch: {}\n", encoding="utf-8")
    assert config_timezone(path) == ZoneInfo("Asia/Kolkata")
    path.write_text("search: {}\n", encoding="utf-8")
    assert config_timezone(path) == ZoneInfo("UTC")
    assert config_timezone(tmp_path / "missing.yaml") == ZoneInfo("UTC")
