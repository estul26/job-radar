"""Seen-jobs state, and the tracker CSVs exported from the Issues."""

import csv
import json
from datetime import datetime, timedelta, timezone

from fake_github import FakeGitHub
from job_radar.commands.export import application_rows, export
from job_radar.state import prune_seen, update_seen

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def test_seen_entries_are_added_once_and_never_rewritten():
    seen = update_seen({}, [{"fingerprint": "a", "title": "Nurse"}], now=NOW - timedelta(days=3))
    before = json.dumps(seen, sort_keys=True)
    update_seen(seen, [{"fingerprint": "a", "title": "Nurse (reposted)"}], now=NOW)
    assert json.dumps(seen, sort_keys=True) == before


def test_old_entries_are_pruned_and_last_seen_dropped():
    seen = {
        "old": {"first_seen": (NOW - timedelta(days=91)).isoformat(), "last_seen": NOW.isoformat()},
        "recent": {"first_seen": (NOW - timedelta(days=5)).isoformat(), "last_seen": NOW.isoformat()},
    }
    assert prune_seen(seen, now=NOW) == {"recent": {"first_seen": (NOW - timedelta(days=5)).isoformat()}}


def _indeed_body(fingerprint: str) -> str:
    return "\n".join(
        [
            f"<!-- job-fingerprint:{fingerprint} -->",
            "",
            "### Job URL",
            "",
            "https://jobs.example.com/1",
            "",
            "### Job title",
            "",
            "Registered Nurse",
            "",
            "### Company",
            "",
            "Example",
            "",
            "### Location",
            "",
            "Toronto, ON",
            "",
            "### Source",
            "",
            "Indeed",
            "",
            "### Remote?",
            "",
            "No",
            "",
            "### Date posted",
            "",
            "2026-10-05",
            "",
            "### Job description",
            "",
            "Wound care.",
            "",
        ]
    )


def test_export_rebuilds_the_tracker_and_resume_index_from_issues(settings, issue_body):
    gh = FakeGitHub(
        [
            {
                "number": 1,
                "title": "[LinkedIn Job] Registered Nurse - Medical/Surgical — Northwind Health",
                "body": issue_body("linkedin_form"),
                "labels": {"status:applied", "match:good"},
                "comments": ["<!-- job-radar:match-review -->\n## 92% — Registered Nurse - Medical/Surgical"],
            },
            {
                "number": 5,
                "title": "[Indeed Job] Registered Nurse — Example",
                "body": _indeed_body("abc12345"),
                "labels": {"status:rejected", "match:good"},
                "state": "CLOSED",
                "comments": ["## 81% — Registered Nurse"],
            },
            {
                "number": 12,
                "title": "[LinkedIn Alert] Registered Nurse — Northwind Care",
                "body": issue_body("linkedin_alert"),
                "labels": {"needs:description"},
            },
            {"number": 13, "title": "Job Radar: 1 new match", "body": "summary", "labels": {"status:new"}},
        ]
    )
    folder = settings.paths.resume_dir / "abc12345-example-staff-nurse"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(
        json.dumps(
            {
                "job_key": "abc12345",
                "issue_number": "",
                "company": "Example",
                "role": "Registered Nurse",
                "score": 81,
                "generated_at": "2026-10-05T10:00:00+00:00",
                "ai": {"used": True, "model": "m"},
            }
        ),
        encoding="utf-8",
    )

    assert export(gh, settings) == (2, 1)

    rows = list(csv.DictReader(settings.paths.applications.open(encoding="utf-8-sig")))
    assert [(r["issue_number"], r["status"], r["match"], r["score"], r["source"]) for r in rows] == [
        ("1", "Applied", "good", "92", "linkedin"),
        ("5", "Rejected", "good", "81", "indeed"),
    ]
    assert rows[0]["job_key"] == "4471544570"

    [index] = list(csv.DictReader(settings.paths.resume_index.open(encoding="utf-8-sig")))
    assert (index["job_key"], index["issue_number"]) == ("abc12345", "5")  # matched to its Issue by fingerprint
    assert (index["status"], index["ai_used"]) == ("Rejected", "Yes")


def test_export_keeps_jobs_whose_description_has_headings_or_is_empty(issue_body):
    no_description = _indeed_body("def67890").replace("Wound care.", "")
    issues = [
        {
            "number": 2,
            "title": "[Indeed Job] Assistant Accountant — Example Freight Ltd",
            "body": issue_body("indeed_markdown_headings"),
            "labels": [{"name": "status:new"}],
        },
        {
            "number": 3,
            "title": "[Indeed Job] Registered Nurse — Example",
            "body": no_description,
            "labels": [{"name": "status:applied"}],
        },
        {
            "number": 4,
            "title": "[Indeed Job] Broken — Example",
            "body": "no fields at all",
            "labels": [{"name": "status:new"}],
        },
    ]
    skipped: list[str] = []
    rows = application_rows(issues, skipped)
    assert [(row["issue_number"], row["location"]) for row in rows] == [(2, "Leeds, ENG, UK"), (3, "Toronto, ON")]
    assert skipped == ["#4: Missing required Issue field: LinkedIn job URL"]
