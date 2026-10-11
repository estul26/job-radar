from job_radar.commands.issue import build_review
from job_radar.issue_body import parse_job, parse_sections
from job_radar.models import Verdict

ISSUE_BODY = """### LinkedIn job URL

https://www.linkedin.com/jobs/view/123

### Job title

SOC Analyst I

### Company

Example Security

### Location

Toronto, ON

### Remote?

No

### Date posted (optional)

2026-10-04

### Job description

1 year experience. Splunk, QRadar, incident response, Active Directory, DNS, Security+.
"""


def test_parse_linkedin_issue_form():
    fields = parse_sections(ISSUE_BODY)
    assert fields["job title"] == "SOC Analyst I"
    assert fields["company"] == "Example Security"


def test_job_from_issue_creates_linkedin_job():
    job = parse_job(ISSUE_BODY)
    assert job["source"] == "linkedin"
    assert job["title"] == "SOC Analyst I"
    assert job["is_remote"] is False
    assert job["fingerprint"]


def test_review_shows_the_recommendation_and_how_to_track_it():
    scored = {
        "score": 82,
        "title": "SOC Analyst I",
        "company": "Example Security",
        "location": "Toronto, ON",
        "job_url": "https://www.linkedin.com/jobs/view/123",
        "matched_skills": ["splunk"],
        "missing_skills": [],
        "matched_certs": ["CompTIA Security+"],
        "missing_certs": [],
        "score_reasons": ["target-role title"],
        "hard_reject": False,
        "hard_reject_reasons": [],
    }
    review = build_review(scored, Verdict.GOOD)
    assert "## 82% — SOC Analyst I" in review  # the score line the export and board read
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
            "SOC Analyst, Entry Level",
            "",
            "### Company",
            "",
            "Jobright.ai · Canada (Remote)",
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
            "Monitor SIEM alerts and escalate incidents.",
            "",
        ]
    )
    job = parse_job(body)
    assert (job["company"], job["location"], job["is_remote"]) == ("Jobright.ai", "Canada (Remote)", True)


def test_explicit_no_remote_answer_wins_over_location_text():
    body = "\n".join(
        [
            "### LinkedIn job URL",
            "",
            "https://www.linkedin.com/jobs/view/1/",
            "",
            "### Job title",
            "",
            "SOC Analyst",
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
            "Monitor SIEM alerts.",
            "",
        ]
    )
    assert parse_job(body)["is_remote"] is False
