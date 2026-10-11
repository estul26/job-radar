"""radar scan + radar publish-scan on the sample fixture."""

import json
from pathlib import Path

from conftest import ROOT
from fake_github import FakeGitHub
from job_radar.commands.scan import (
    INDEED_MARKER,
    generate_scan_resumes,
    issue_fingerprints,
    publish_scan,
    scan_jobs,
)
from job_radar.issue_body import fingerprint_marker

FIXTURE = ROOT / "tests/fixtures/sample_jobs.json"


def matches(settings) -> list[dict]:
    return json.loads(settings.paths.scan_matches.read_text(encoding="utf-8"))


def test_scan_records_jobs_and_hands_off_indeed_matches(settings):
    report = scan_jobs(settings, FIXTURE)

    assert "Collected **3** unique jobs; **3** were new" in report
    assert "Senior Security Engineer" in report  # listed as automatically excluded
    assert len(json.loads(settings.paths.seen_jobs.read_text(encoding="utf-8"))) == 3
    # The ZipRecruiter match is reported, but only Indeed matches get Issues.
    assert [(job["title"], job["verdict"]) for job in matches(settings)] == [("SOC Analyst I", "good")]


def test_a_second_scan_sees_nothing_new(settings):
    scan_jobs(settings, FIXTURE)
    report = scan_jobs(settings, FIXTURE)

    assert "**0** were new to the tracker" in report
    assert matches(settings) == []


def test_jobs_that_already_have_an_issue_are_not_new(settings):
    scan_jobs(settings, FIXTURE)
    soc = matches(settings)[0]
    settings.paths.seen_jobs.unlink()

    report = scan_jobs(settings, FIXTURE, known_fingerprints=frozenset({soc["fingerprint"]}))
    assert "**2** were new to the tracker" in report
    assert matches(settings) == []


def test_issue_fingerprints_cover_indeed_markers_and_linkedin_bodies(issue_body):
    issues = [
        {"title": "[Indeed Job] Cybersecurity Analyst — Example School District", "body": issue_body("indeed")},
        {"title": "[LinkedIn Job] Entry-Level Cybersecurity Analyst — Jobright", "body": issue_body("linkedin_form")},
        {"title": "Job Radar: 1 new match", "body": "summary"},
    ]
    assert issue_fingerprints(issues) == {"f12784e3b632e3b21873", "c5b64f0850f97296dc1f"}


def test_good_matches_get_an_assigned_issue_with_their_resume(settings):
    scan_jobs(settings, FIXTURE)
    results = generate_scan_resumes(settings)
    assert [item["title"] for item in results] == ["SOC Analyst I"]
    assert Path(results[0]["resume_markdown"]).exists()

    gh = FakeGitHub()
    [number] = publish_scan(gh, settings)
    issue = gh.issue(number)
    assert issue["title"] == "[Indeed Job] SOC Analyst I — Northwind Security"
    assert fingerprint_marker(issue["body"]) == results[0]["fingerprint"]
    assert gh.labels_of(number) == {"source:indeed", "match:good", "status:new", "resume:ready"}
    assert gh._issues[number]["assignee"] == "owner"
    assert "/blob/main/" in gh.comments_of(number)[0]
    assert len(gh.issues()) == 1  # no separate summary Issue any more

    publish_scan(gh, settings)  # a re-run updates in place
    assert len(gh.issues()) == 1
    assert sum(INDEED_MARKER in comment for comment in gh.comments_of(number)) == 1


def test_possible_matches_get_an_unassigned_issue_without_a_resume(settings):
    settings.paths.scan_matches.parent.mkdir(parents=True)
    possible = {
        "fingerprint": "abc12345",
        "source": "indeed",
        "title": "IT Security Analyst",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "",
        "job_url": "https://example.com/1",
        "description": "Splunk.",
        "score": 57,
        "verdict": "possible",
    }
    settings.paths.scan_matches.write_text(json.dumps([possible]), encoding="utf-8")
    assert generate_scan_resumes(settings) == []

    gh = FakeGitHub()
    [number] = publish_scan(gh, settings)
    assert gh.labels_of(number) == {"source:indeed", "match:possible", "status:new"}
    assert gh._issues[number]["assignee"] == ""
    assert "resume:tailor" in gh.comments_of(number)[0]
