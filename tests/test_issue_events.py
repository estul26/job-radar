"""The issue-events workflow: what each Issue event changes locally and on GitHub."""

import pytest

from fake_github import FakeGitHub
from job_radar.commands.issue import RESUME_MARKER, REVIEW_MARKER, prepare, publish, route
from job_radar.models import Verdict

JOB_URL = "https://www.linkedin.com/jobs/view/4471544570/"


def linkedin_issue(description: str, title="Registered Nurse I", location="Toronto, ON", **extra) -> dict:
    body = "\n".join(
        [
            "### LinkedIn job URL",
            "",
            JOB_URL,
            "",
            "### Job title",
            "",
            title,
            "",
            "### Company",
            "",
            "Example Health",
            "",
            "### Location",
            "",
            location,
            "",
            "### Remote?",
            "",
            "No",
            "",
            "### Job description",
            "",
            description,
            "",
        ]
    )
    return {"number": 7, "title": "[LinkedIn Job] Registered Nurse I — Example Health", "body": body, **extra}


GOOD = "1 year experience. Patient assessment, medication administration, wound care, IV therapy. BLS required."
# Partly related title, far away, 4 years and only skills the profile lacks: scores ~23.
LOW = {
    "description": "4 years of experience required. Epic, Meditech, telemetry and triage. ACLS and PALS required.",
    "title": "Nurse Educator",
    "location": "Vancouver, BC",
}


def run_event(gh: FakeGitHub, settings, number: int, event: str, label: str = "") -> str | None:
    """What the workflow does: prepare, (commit), publish — each with a fresh view of the Issue."""
    kind = route(gh.issue(number), event, label)
    if kind:
        prepare(settings, gh.issue(number), kind, label)
        publish(gh, settings, gh.issue(number), kind, label)
    return kind


@pytest.mark.parametrize(
    ("title", "body", "event", "label", "expected"),
    [
        ("[LinkedIn Job] Nurse", "desc", "opened", "", "intake"),
        ("[LinkedIn Alert] Nurse", "desc", "edited", "", "intake"),
        ("[LinkedIn Alert] Nurse", "_Paste full job description here, replacing this line", "edited", "", None),
        ("[Indeed Job] Nurse", "desc", "edited", "", None),
        ("[Indeed Job] Nurse", "desc", "labeled", "resume:tailor", "resume"),
        ("[Naukri Job] Nurse", "desc", "labeled", "resume:tailor", "resume"),
        ("[Glassdoor Job] Nurse", "desc", "edited", "", None),
        ("Job Radar: 1 new match", "desc", "labeled", "resume:tailor", None),
        ("[LinkedIn Job] Nurse", "desc", "labeled", "status:applied", "status"),
        ("[LinkedIn Job] Nurse", "desc", "labeled", "status:wishlist", None),
        ("[LinkedIn Job] Nurse", "desc", "labeled", "match:good", None),
    ],
)
def test_route(title, body, event, label, expected):
    assert route({"title": title, "body": body}, event, label) == expected


def test_good_match_is_scored_tracked_and_gets_a_resume(settings):
    gh = FakeGitHub([linkedin_issue(GOOD)])
    assert run_event(gh, settings, 7, "opened") == "intake"

    assert {"source:linkedin", "match:good", "status:new", "resume:ready"} <= gh.labels_of(7)
    comments = gh.comments_of(7)
    assert comments[0].startswith(REVIEW_MARKER) and "GOOD MATCH — APPLY" in comments[0]
    assert comments[1].startswith(RESUME_MARKER) and "/blob/main/" in comments[1]

    assert (settings.paths.resume_dir / "4471544570-example-health-registered-nurse-i" / "resume.md").exists()
    # The Issue is the tracker; nothing shared is written outside the résumé folder.
    assert not settings.paths.applications.exists() and not settings.paths.seen_jobs.exists()


def test_scoring_an_alert_clears_needs_description(settings):
    gh = FakeGitHub([linkedin_issue(GOOD, labels={"needs:description"})])
    run_event(gh, settings, 7, "edited")
    assert "needs:description" not in gh.labels_of(7)


def test_rescoring_keeps_a_status_you_set_and_does_not_duplicate_comments(settings):
    gh = FakeGitHub([linkedin_issue(GOOD, labels={"status:applied", "match:good"}, state="CLOSED")])
    run_event(gh, settings, 7, "edited")
    run_event(gh, settings, 7, "edited")

    assert "status:applied" in gh.labels_of(7) and "status:new" not in gh.labels_of(7)
    assert gh.state_of(7) == "CLOSED"
    assert sum(REVIEW_MARKER in comment for comment in gh.comments_of(7)) == 1


def test_low_match_is_skipped_and_closed(settings):
    gh = FakeGitHub([linkedin_issue(**LOW, labels={"status:new", "match:possible"})])
    run_event(gh, settings, 7, "edited")

    labels = gh.labels_of(7)
    assert {"match:low", "status:skipped"} <= labels and not labels & {"match:possible", "status:new"}
    assert gh.state_of(7) == "CLOSED"
    assert "LOW MATCH" in gh.comments_of(7)[0]
    assert "below the tracking threshold" in gh.comments_of(7)[-1]
    assert not settings.paths.pending_resume.exists()


def test_possible_match_comment_is_posted_once(settings, monkeypatch):
    monkeypatch.setattr("job_radar.commands.issue.classify", lambda *args: Verdict.POSSIBLE)
    gh = FakeGitHub([linkedin_issue(GOOD)])
    run_event(gh, settings, 7, "opened")
    run_event(gh, settings, 7, "edited")
    assert sum(comment.startswith("Tracked as status:new") for comment in gh.comments_of(7)) == 1


def test_status_label_is_exclusive_and_closes_without_any_commit(settings):
    gh = FakeGitHub([linkedin_issue(GOOD)])
    run_event(gh, settings, 7, "opened")
    resume_files = sorted(settings.paths.resume_dir.rglob("*"))

    gh.edit_issue(7, add_labels=["status:rejected"])
    assert run_event(gh, settings, 7, "labeled", "status:rejected") == "status"
    assert {name for name in gh.labels_of(7) if name.startswith("status:")} == {"status:rejected"}
    assert gh.state_of(7) == "CLOSED"
    assert sorted(settings.paths.resume_dir.rglob("*")) == resume_files
    assert not settings.paths.applications.exists()

    gh.edit_issue(7, add_labels=["status:interview"])
    run_event(gh, settings, 7, "labeled", "status:interview")
    assert gh.state_of(7) == "OPEN"


def test_resume_tailor_label_regenerates_and_marks_ready(settings):
    gh = FakeGitHub([linkedin_issue(**LOW, labels={"resume:tailor", "status:skipped"}, state="CLOSED")])
    assert run_event(gh, settings, 7, "labeled", "resume:tailor") == "resume"

    labels = gh.labels_of(7)
    assert "resume:ready" in labels and "resume:tailor" not in labels
    assert gh.comments_of(7)[-1].startswith(RESUME_MARKER)
    assert gh.state_of(7) == "CLOSED"


def test_a_status_event_for_a_label_already_removed_changes_nothing(settings):
    gh = FakeGitHub([linkedin_issue(GOOD, labels={"status:interview"})])
    assert run_event(gh, settings, 7, "labeled", "status:applied") == "status"
    assert gh.labels_of(7) == {"status:interview"}
    assert gh.state_of(7) == "OPEN"
