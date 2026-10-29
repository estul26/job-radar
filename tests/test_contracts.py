"""The shared contracts: Issue bodies, job IDs, statuses, verdicts and settings."""

import pytest

from job_radar.ids import canonical_job_key, job_key, linkedin_job_id, make_fingerprint
from job_radar.issue_body import (
    PLACEHOLDER_DESCRIPTION,
    fingerprint_marker,
    job_url,
    parse_job,
    render_board_job,
    render_linkedin_alert,
)
from job_radar.labels import LABELS, STATUSES, normalize_status, status_label
from job_radar.models import Verdict, classify
from job_radar.settings import good_match_threshold


def test_linkedin_form_issue(issue_body):
    job = parse_job(issue_body("linkedin_form"))
    assert (job["source"], job["company"], job["is_remote"]) == ("linkedin", "Northwind Health", True)
    assert job["job_url"] == "https://www.linkedin.com/jobs/view/4471544570/"
    assert job["fingerprint"] == "46ef8e7bbe1ada01b935"


def test_indeed_issue_keeps_its_fingerprint_marker(issue_body):
    body = issue_body("indeed")
    job = parse_job(body)
    assert (job["source"], job["company"], job["date_posted"]) == ("indeed", "Example Health Region", "2026-10-05")
    assert job["fingerprint"] == fingerprint_marker(body) == "f12784e3b632e3b21873"


def test_linkedin_alert_issue_awaiting_its_description(issue_body):
    job = parse_job(issue_body("linkedin_alert"))
    assert (job["company"], job["location"], job["is_remote"]) == ("Northwind Care", "Canada (Remote)", True)
    assert job["description"] == PLACEHOLDER_DESCRIPTION


@pytest.mark.parametrize("name", ["linkedin_form", "indeed", "linkedin_alert"])
def test_job_url_is_found_in_every_issue_kind(issue_body, name):
    assert job_url(issue_body(name)) == parse_job(issue_body(name))["job_url"]


def test_indeed_body_round_trips(issue_body):
    job = parse_job(issue_body("indeed"))
    assert parse_job(render_board_job(job)) == job


def test_alert_body_round_trips():
    candidate = {
        "job_id": "4471532081",
        "job_url": "https://www.linkedin.com/jobs/view/4471532081/",
        "title": "Registered Nurse, New Graduate",
        "company": "Northwind Care",
        "location": "Canada (Remote)",
        "card_excerpt": "Registered Nurse, New Graduate\nNorthwind Care · Canada (Remote)",
    }
    job = parse_job(render_linkedin_alert(candidate, "New jobs for you"))
    assert (job["title"], job["company"]) == ("Registered Nurse, New Graduate", "Northwind Care")
    assert job["location"] == "Canada (Remote)"
    assert job["is_remote"] is True
    assert job["description"] == PLACEHOLDER_DESCRIPTION


def test_long_indeed_descriptions_are_truncated_for_github():
    body = render_board_job({"fingerprint": "abc12345", "title": "Registered Nurse", "description": "x" * 50000})
    assert len(body) < 65536
    assert "[Description truncated in GitHub Issue.]" in body


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/4471544570/",
        "https://www.linkedin.com/jobs/view/registered-nurse-at-northwind-health-4471544570?trk=x",
        "https://www.linkedin.com/comm/jobs/view/4471544570/?trackingId=abc",
        "https://www.linkedin.com/jobs/search-results/?currentJobId=4471544570&keywords=nurse",
        "https://www.linkedin.com/jobs/collections/recommended/?foo=1&amp;currentJobId=4471544570",
    ],
)
def test_linkedin_job_id_variants(url):
    assert linkedin_job_id(url) == "4471544570"
    assert canonical_job_key(url) == "linkedin:4471544570"


def test_job_keys():
    assert linkedin_job_id("https://ca.indeed.com/job/123") == ""
    assert canonical_job_key("HTTPS://Example.com/Job/") == "https://example.com/job"
    assert job_key("https://www.linkedin.com/jobs/view/42/", "abc") == "42"
    assert job_key("https://ca.indeed.com/job/123", "abc") == "abc"


def test_fingerprint_needs_url_only_without_company():
    assert make_fingerprint("Nurse", "Acme", "Toronto", "a") == make_fingerprint("Nurse", "Acme", "Toronto", "b")
    assert make_fingerprint("Nurse", "", "Toronto", "a") != make_fingerprint("Nurse", "", "Toronto", "b")


def test_statuses_and_labels():
    assert normalize_status(" applied ") == "Applied"
    assert status_label("Interview") == "status:interview"
    assert {f"status:{s.lower()}" for s in STATUSES} <= set(LABELS)
    with pytest.raises(ValueError):
        normalize_status("wishlist")


@pytest.mark.parametrize(
    ("score", "hard_reject", "expected"),
    [
        (80, False, Verdict.GOOD),
        (60, False, Verdict.GOOD),
        (59, False, Verdict.POSSIBLE),
        (55, False, Verdict.POSSIBLE),
        (54, False, Verdict.LOW),
        (95, True, Verdict.REJECTED),
    ],
)
def test_verdicts(score, hard_reject, expected):
    verdict = classify({"score": score, "hard_reject": hard_reject}, good_threshold=60, possible_threshold=55)
    assert verdict is expected
    assert verdict.tracked == (expected in (Verdict.GOOD, Verdict.POSSIBLE))


def test_repository_variable_overrides_good_threshold():
    config = {"ranking": {"good_match_threshold": 65}}
    assert good_match_threshold(config, env={}) == 65
    assert good_match_threshold(config, env={"GOOD_MATCH_THRESHOLD": "60"}) == 60
    assert good_match_threshold(config, env={"GOOD_MATCH_THRESHOLD": " "}) == 65


def test_headings_inside_a_job_description_stay_in_the_description(issue_body):
    # Job boards send Markdown descriptions, often starting with a "###" heading of their own.
    body = issue_body("indeed_markdown_headings")
    job = parse_job(body)
    assert (job["title"], job["location"]) == ("Assistant Accountant", "Leeds, ENG, UK")
    assert job["description"].startswith("### **About the role**")
    assert "Hybrid, three days a week" in job["description"]
    assert job["description"].endswith("This line is part of the description, not a field.")
    assert parse_job(render_board_job(job)) == job


def test_a_trailing_source_heading_still_ends_the_description():
    candidate = {
        "job_id": "4471532081",
        "job_url": "https://www.linkedin.com/jobs/view/4471532081/",
        "title": "Registered Nurse",
        "company": "Northwind Care",
        "location": "Toronto, ON",
        "card_excerpt": "Registered Nurse\nNorthwind Care · Toronto, ON",
    }
    body = render_linkedin_alert(candidate, "New jobs for you").replace(
        PLACEHOLDER_DESCRIPTION, "### Responsibilities\n\nAssess patients."
    )
    job = parse_job(body)
    assert job["description"] == "### Responsibilities\n\nAssess patients."


def test_a_missing_description_can_be_allowed(issue_body):
    body = issue_body("indeed").split("### Job description")[0] + "### Job description\n\n"
    with pytest.raises(ValueError, match="Job description"):
        parse_job(body)
    assert parse_job(body, require_description=False)["description"] == ""
