from job_radar.commands.issue import build_review
from job_radar.issue_body import parse_job, parse_sections
from job_radar.models import Verdict

ISSUE_BODY = """### LinkedIn job URL

https://www.linkedin.com/jobs/view/123

### Job title

Registered Nurse I

### Company

Example Health

### Location

Toronto, ON

### Remote?

No

### Date posted (optional)

2026-10-04

### Job description

1 year experience. Patient assessment, medication administration, wound care, IV therapy. BLS required.
"""


def test_parse_linkedin_issue_form():
    fields = parse_sections(ISSUE_BODY)
    assert fields["job title"] == "Registered Nurse I"
    assert fields["company"] == "Example Health"


def test_job_from_issue_creates_linkedin_job():
    job = parse_job(ISSUE_BODY)
    assert job["source"] == "linkedin"
    assert job["title"] == "Registered Nurse I"
    assert job["is_remote"] is False
    assert job["fingerprint"]


def test_review_shows_the_recommendation_and_how_to_track_it():
    scored = {
        "score": 82,
        "title": "Registered Nurse I",
        "company": "Example Health",
        "location": "Toronto, ON",
        "job_url": "https://www.linkedin.com/jobs/view/123",
        "matched_skills": ["wound care"],
        "missing_skills": [],
        "matched_certs": ["BLS"],
        "missing_certs": [],
        "score_reasons": ["target-role title"],
        "hard_reject": False,
        "hard_reject_reasons": [],
    }
    review = build_review(scored, Verdict.GOOD)
    assert "## 82% — Registered Nurse I" in review  # the score line the export and board read
    assert "GOOD MATCH" in review
    assert "**Tracked:** Yes — status:new" in review
    assert "data/applications.csv" not in review  # the CSV is an export now
    assert "**Tracked:** No — status:skipped" in build_review({**scored, "hard_reject": True}, Verdict.REJECTED)


def test_old_alert_issue_splits_company_and_infers_remote():
    body = "\n".join(
        [
            "### LinkedIn job URL",
            "",
            "https://www.linkedin.com/jobs/view/4471544570/",
            "",
            "### Job title",
            "",
            "Registered Nurse, New Graduate",
            "",
            "### Company",
            "",
            "Northwind Care · Canada (Remote)",
            "",
            "### Location",
            "",
            "Unknown — edit before scoring",
            "",
            "### Remote?",
            "",
            "Not sure",
            "",
            "### Job description",
            "",
            "Assess patients and administer medications.",
            "",
        ]
    )
    job = parse_job(body)
    assert (job["company"], job["location"], job["is_remote"]) == ("Northwind Care", "Canada (Remote)", True)


def test_explicit_no_remote_answer_wins_over_location_text():
    body = "\n".join(
        [
            "### LinkedIn job URL",
            "",
            "https://www.linkedin.com/jobs/view/1/",
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
            "Remote-friendly office, Toronto",
            "",
            "### Remote?",
            "",
            "No",
            "",
            "### Job description",
            "",
            "Assess patients.",
            "",
        ]
    )
    assert parse_job(body)["is_remote"] is False
