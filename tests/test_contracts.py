"""The shared contracts: Issue bodies, job IDs, statuses, verdicts and settings."""

import pytest

from job_radar.ids import canonical_job_key, job_key, linkedin_job_id, make_fingerprint
from job_radar.issue_body import (
    PLACEHOLDER_DESCRIPTION,
    fingerprint_marker,
    job_url,
    parse_job,
    render_indeed,
    render_linkedin_alert,
)
from job_radar.labels import LABELS, STATUSES, normalize_status, status_label
from job_radar.models import Verdict, classify
from job_radar.settings import good_match_threshold


def test_linkedin_form_issue(issue_body):
    job = parse_job(issue_body("linkedin_form"))
    assert (job["source"], job["company"], job["is_remote"]) == ("linkedin", "Jobright", True)
    assert job["job_url"] == "https://www.linkedin.com/jobs/view/4471544570/"
    # Matches the row the old parser wrote to data/applications.csv.
    assert job["fingerprint"] == "c5b64f0850f97296dc1f"


def test_indeed_issue_keeps_its_fingerprint_marker(issue_body):
    body = issue_body("indeed")
    job = parse_job(body)
    assert (job["source"], job["company"], job["date_posted"]) == ("indeed", "Example School District", "2026-10-05")
    assert job["fingerprint"] == fingerprint_marker(body) == "f12784e3b632e3b21873"


def test_linkedin_alert_issue_awaiting_its_description(issue_body):
    job = parse_job(issue_body("linkedin_alert"))
    assert (job["company"], job["location"], job["is_remote"]) == ("Jobright.ai", "Canada (Remote)", True)
    assert job["description"] == PLACEHOLDER_DESCRIPTION


@pytest.mark.parametrize("name", ["linkedin_form", "indeed", "linkedin_alert"])
def test_job_url_is_found_in_every_issue_kind(issue_body, name):
    assert job_url(issue_body(name)) == parse_job(issue_body(name))["job_url"]


def test_indeed_body_round_trips(issue_body):
    job = parse_job(issue_body("indeed"))
    assert parse_job(render_indeed(job)) == job


def test_alert_body_round_trips():
    candidate = {
        "job_id": "4471532081",
        "job_url": "https://www.linkedin.com/jobs/view/4471532081/",
        "title": "SOC Analyst, Entry Level",
        "company": "Jobright.ai",
        "location": "Canada (Remote)",
        "card_excerpt": "SOC Analyst, Entry Level\nJobright.ai · Canada (Remote)",
    }
    job = parse_job(render_linkedin_alert(candidate, "New jobs for you"))
    assert (job["title"], job["company"]) == ("SOC Analyst, Entry Level", "Jobright.ai")
    assert job["location"] == "Canada (Remote)"
    assert job["is_remote"] is True
    assert job["description"] == PLACEHOLDER_DESCRIPTION


def test_long_indeed_descriptions_are_truncated_for_github():
    body = render_indeed({"fingerprint": "abc12345", "title": "SOC Analyst", "description": "x" * 50000})
    assert len(body) < 65536
    assert "[Description truncated in GitHub Issue.]" in body


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/4471544570/",
        "https://www.linkedin.com/jobs/view/soc-analyst-at-jobright-4471544570?trk=x",
        "https://www.linkedin.com/comm/jobs/view/4471544570/?trackingId=abc",
        "https://www.linkedin.com/jobs/search-results/?currentJobId=4471544570&keywords=soc",
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
    assert make_fingerprint("SOC", "Acme", "Toronto", "a") == make_fingerprint("SOC", "Acme", "Toronto", "b")
    assert make_fingerprint("SOC", "", "Toronto", "a") != make_fingerprint("SOC", "", "Toronto", "b")


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
