"""radar refresh-resumes: regenerate out-of-date résumés of jobs not yet applied to after the master changes."""

import json

import yaml

from conftest import MASTER, ROOT
from fake_github import FakeGitHub
from job_radar.commands.issue import RESUME_MARKER
from job_radar.commands.refresh import prepare_refresh, publish_refresh, stale_issues
from job_radar.issue_body import parse_job
from job_radar.resume.pipeline import generate_resume
from job_radar.settings import load_json
from test_issue_events import GOOD, linkedin_issue

CURRENT = load_json(MASTER)["version"]
OLD = {**load_json(MASTER), "version": "fixture-0"}


def old_resume(settings, issue, *, with_issue_number=True):
    """A résumé made for the Issue's job from an older master version."""
    job = {**parse_job(issue["body"]), "score": 80}
    number = str(issue["number"]) if with_issue_number else ""
    return generate_resume(job, OLD, vocab=settings.vocab, issue_number=number, resume_dir=settings.paths.resume_dir)


def versions(settings):
    return {
        json.loads(path.read_text())["job_key"]: json.loads(path.read_text())["master_version"]
        for path in settings.paths.resume_dir.glob("*/metadata.json")
    }


def test_an_out_of_date_resume_is_regenerated_and_linked(settings):
    issue = linkedin_issue(GOOD, labels={"status:new", "resume:ready"})
    old_resume(settings, issue)
    gh = FakeGitHub([issue])

    results = prepare_refresh(settings, gh.issues())

    assert [r["issue_number"] for r in results] == ["7"]
    assert versions(settings) == {"4471544570": CURRENT}
    assert publish_refresh(gh, settings) == [7]
    assert "resume:ready" in gh.labels_of(7)
    comment = next(c for c in gh.comments_of(7) if c.startswith(RESUME_MARKER))
    assert f"Master version: {CURRENT}" in comment


def test_saved_jobs_are_refreshed_too(settings):
    issue = linkedin_issue(GOOD, labels={"status:saved"})
    old_resume(settings, issue)
    assert [i["number"] for i in stale_issues(FakeGitHub([issue]).issues(), settings.paths.resume_dir, CURRENT)] == [7]


def test_resumes_you_sent_or_skipped_are_kept(settings):
    for labels, state in (({"status:applied"}, "OPEN"), ({"status:interview"}, "OPEN"), ({"status:skipped"}, "CLOSED")):
        issue = linkedin_issue(GOOD, labels=labels, state=state)
        old_resume(settings, issue)
        gh = FakeGitHub([issue])
        assert prepare_refresh(settings, gh.issues()) == []
        assert publish_refresh(gh, settings) == []
        assert versions(settings) == {"4471544570": "fixture-0"}


def test_up_to_date_and_resume_less_jobs_are_left_alone(settings):
    issue = linkedin_issue(GOOD, labels={"status:new"})
    gh = FakeGitHub([issue])
    assert prepare_refresh(settings, gh.issues()) == []  # never had a résumé

    generate_resume(
        {**parse_job(issue["body"]), "score": 80},
        load_json(MASTER),
        vocab=settings.vocab,
        issue_number="7",
        resume_dir=settings.paths.resume_dir,
    )
    assert prepare_refresh(settings, gh.issues()) == []  # already made from the current master


def test_a_job_board_resume_is_found_by_its_job_key(settings, issue_body):
    # The scan makes a board job's résumé before its Issue exists, so its metadata has no Issue number.
    issue = {"number": 12, "title": "[Indeed Job] Charge Nurse — Example Health Region", "body": issue_body("indeed")}
    issue["labels"] = {"status:new", "resume:ready"}
    old_resume(settings, issue, with_issue_number=False)
    gh = FakeGitHub([issue])

    assert [r["issue_number"] for r in prepare_refresh(settings, gh.issues())] == ["12"]
    assert set(versions(settings).values()) == {CURRENT}


def test_the_workflow_runs_when_the_master_changes_and_commits_only_resumes():
    workflow = yaml.safe_load((ROOT / ".github/workflows/refresh-resumes.yml").read_text(encoding="utf-8"))
    on = workflow[True]  # YAML reads the bare key `on` as True
    assert on["push"]["paths"] == ["resumes/master_resume.json"]
    steps = workflow["jobs"]["refresh"]["steps"]
    runs = [step.get("run") for step in steps if step.get("run")]
    assert runs == ["radar refresh-resumes", "radar refresh-resumes --publish"]
    commit = next(step for step in steps if step.get("uses") == "./.github/actions/commit-state")
    assert commit["with"]["paths"] == "resumes/jobs"
