"""radar scan + radar publish-scan on the sample fixture."""

import json
from pathlib import Path

from conftest import ROOT
from fake_github import FakeGitHub
from job_radar.commands.scan import (
    MATCH_MARKER,
    generate_scan_resumes,
    issue_fingerprints,
    publish_scan,
    scan_jobs,
)
from job_radar.issue_body import fingerprint_marker, parse_job

FIXTURE = ROOT / "tests/fixtures/sample_jobs.json"


def matches(settings) -> list[dict]:
    return json.loads(settings.paths.scan_matches.read_text(encoding="utf-8"))


def test_scan_records_jobs_and_hands_off_matches_from_every_board(settings):
    report = scan_jobs(settings, FIXTURE)

    assert "Collected **3** unique jobs; **3** were new" in report
    assert "Nurse Manager, Emergency" in report  # listed as automatically excluded
    assert len(json.loads(settings.paths.seen_jobs.read_text(encoding="utf-8"))) == 3
    assert [(job["title"], job["verdict"], job["source"]) for job in matches(settings)] == [
        ("Registered Nurse - Medical/Surgical", "good", "indeed"),
        ("Telehealth Staff Nurse", "possible", "glassdoor"),
    ]


def test_linkedin_results_are_reported_but_get_no_scan_issue(settings, tmp_path):
    jobs = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for job in jobs:
        job["site"] = "linkedin"
    linkedin = tmp_path / "linkedin_jobs.json"
    linkedin.write_text(json.dumps(jobs), encoding="utf-8")

    report = scan_jobs(settings, linkedin)
    assert "Registered Nurse - Medical/Surgical" in report
    assert matches(settings) == []


def test_a_second_scan_sees_nothing_new(settings):
    scan_jobs(settings, FIXTURE)
    report = scan_jobs(settings, FIXTURE)

    assert "**0** were new to the tracker" in report
    assert matches(settings) == []


def test_jobs_that_already_have_an_issue_are_not_new(settings):
    scan_jobs(settings, FIXTURE)
    tracked = matches(settings)[0]
    settings.paths.seen_jobs.unlink()

    report = scan_jobs(settings, FIXTURE, known_fingerprints=frozenset({tracked["fingerprint"]}))
    assert "**2** were new to the tracker" in report
    assert [job["title"] for job in matches(settings)] == ["Telehealth Staff Nurse"]


def test_issue_fingerprints_cover_indeed_markers_and_linkedin_bodies(issue_body):
    issues = [
        {"title": "[Indeed Job] Charge Nurse — Example Health Region", "body": issue_body("indeed")},
        {
            "title": "[LinkedIn Job] Registered Nurse - Medical/Surgical — Northwind Health",
            "body": issue_body("linkedin_form"),
        },
        {"title": "Job Radar: 1 new match", "body": "summary"},
    ]
    assert issue_fingerprints(issues) == {"f12784e3b632e3b21873", "46ef8e7bbe1ada01b935"}


def test_good_matches_get_an_assigned_issue_with_their_resume(settings):
    scan_jobs(settings, FIXTURE)
    results = generate_scan_resumes(settings)
    assert [item["title"] for item in results] == ["Registered Nurse - Medical/Surgical"]
    assert Path(results[0]["resume_markdown"]).exists()

    gh = FakeGitHub()
    number, other = publish_scan(gh, settings)
    issue = gh.issue(number)
    assert issue["title"] == "[Indeed Job] Registered Nurse - Medical/Surgical — Lakeside Health"
    assert fingerprint_marker(issue["body"]) == results[0]["fingerprint"]
    assert gh.labels_of(number) == {"source:indeed", "match:good", "status:new", "resume:ready"}
    assert gh._issues[number]["assignee"] == "owner"
    assert "/blob/main/" in gh.comments_of(number)[0]
    # Any job board gets the same kind of Issue, named after the board.
    assert gh.issue(other)["title"] == "[Glassdoor Job] Telehealth Staff Nurse — Contoso Care"
    assert gh.labels_of(other) == {"source:glassdoor", "match:possible", "status:new"}
    assert "**Source:** Glassdoor" in gh.comments_of(other)[0]
    assert parse_job(gh.issue(other)["body"])["source"] == "glassdoor"
    assert len(gh.issues()) == 2  # no separate summary Issue any more

    publish_scan(gh, settings)  # a re-run updates in place
    assert len(gh.issues()) == 2
    assert sum(MATCH_MARKER in comment for comment in gh.comments_of(number)) == 1


def test_possible_matches_get_an_unassigned_issue_without_a_resume(settings):
    settings.paths.scan_matches.parent.mkdir(parents=True)
    possible = {
        "fingerprint": "abc12345",
        "source": "indeed",
        "title": "Clinical Nurse",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "",
        "job_url": "https://example.com/1",
        "description": "Wound care.",
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
