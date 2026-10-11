"""radar doctor on the shipped blank template and on a filled-in setup."""

import json
from dataclasses import replace

from conftest import CONFIG, MASTER, PROFILE, ROOT
from job_radar.cli import main
from job_radar.commands.doctor import checkup, resume_ready
from job_radar.commands.scan import generate_scan_resumes, scan_jobs
from job_radar.settings import Paths, load_json, load_settings

# A copy of the template as it ships: config/ itself is yours to fill in, and the tests must
# pass either way.
BLANK_DIR = ROOT / "tests/fixtures/blank"
BLANK = (BLANK_DIR / "search_config.yaml", BLANK_DIR / "resume_profile.json", BLANK_DIR / "master_resume.json")


def test_the_shipped_template_lists_what_to_fill_in():
    result = checkup(*BLANK)
    assert not result.ok
    problems = "\n".join(result.problems)
    for missing in ("search.country_indeed", "search.titles", "search.locations"):
        assert missing in problems
    warnings = "\n".join(result.warnings)
    assert "matching.skills is empty" in warnings
    assert "identity.name is empty" in warnings
    assert not resume_ready(load_json(BLANK[2]))


def test_a_filled_in_setup_passes(capsys):
    result = checkup(CONFIG, PROFILE, MASTER)
    assert result.ok and result.warnings == []
    assert main(["doctor", "--config", str(CONFIG), "--profile", str(PROFILE), "--master", str(MASTER)]) == 0
    assert "everything is set up" in capsys.readouterr().out


def test_bad_values_are_named(tmp_path):
    config = tmp_path / "search_config.yaml"
    config.write_text(
        "timezone: Mars/Olympus\nsearch:\n  sites: [indeed]\n  country_indeed: Canada\n  titles: [Nurse]\n"
        "  locations: [{name: Toronto}]\nmatching:\n  skills: {wound care: []}\n",
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"experience_years": "2", "skills": ["wound care", "phlebotomy"]}), encoding="utf-8")

    result = checkup(config, profile, MASTER)

    problems = "\n".join(result.problems)
    assert "'Mars/Olympus' is not an IANA timezone" in problems
    assert "search.locations[0] (Toronto) needs a query" in problems
    assert "experience_years must be a whole number" in problems
    assert "can never match a posting: phlebotomy" in "\n".join(result.warnings)


def test_missing_files_are_problems(tmp_path):
    result = checkup(tmp_path / "nope.yaml", tmp_path / "nope.json", tmp_path / "nope2.json")
    assert len(result.problems) == 3 and all("file not found" in item for item in result.problems)


def test_the_blank_template_scans_without_crashing_and_makes_no_resumes(tmp_path):
    settings = load_settings(BLANK[0], BLANK[1])
    settings = replace(
        settings,
        paths=Paths.from_config(
            {
                "report_path": str(tmp_path / "latest.md"),
                "latest_jobs_path": str(tmp_path / "latest_jobs.csv"),
                "seen_jobs_path": str(tmp_path / "seen.json"),
                "scan_matches_path": str(tmp_path / "matches.json"),
                "resume_manifest_path": str(tmp_path / "manifest.json"),
                "master_resume_path": str(BLANK[2]),
            }
        ),
    )
    report = scan_jobs(settings, ROOT / "tests/fixtures/sample_jobs.json")
    assert "Collected **3** unique jobs" in report
    assert generate_scan_resumes(settings) is None
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == []


def test_a_job_issue_waits_for_the_setup_instead_of_being_rejected(tmp_path, monkeypatch):
    from fake_github import FakeGitHub
    from job_radar.commands.issue import SETUP_MARKER, prepare, publish, route

    monkeypatch.setenv("AI_RESUME_ENABLED", "false")
    settings = load_settings(BLANK[0], BLANK[1])
    settings = replace(settings, paths=Paths.from_config({"pending_resume_path": str(tmp_path / "pending.json")}))
    body = "\n\n".join(
        [
            "### LinkedIn job URL",
            "https://www.linkedin.com/jobs/view/1/",
            "### Job title",
            "Registered Nurse",
            "### Company",
            "Example",
            "### Location",
            "Toronto",
            "### Job description",
            "Wound care.",
        ]
    )
    gh = FakeGitHub([{"number": 1, "title": "[LinkedIn Job] Registered Nurse — Example", "body": body}])
    kind = route(gh.issue(1), "opened")
    prepare(settings, gh.issue(1), kind)
    publish(gh, settings, gh.issue(1), kind)

    assert gh.state_of(1) == "OPEN" and gh.labels_of(1) == set()
    [comment] = gh.comments_of(1)
    assert comment.startswith(SETUP_MARKER) and "search.titles is empty" in comment


def test_alert_emails_wait_for_the_setup(tmp_path, monkeypatch, capsys):
    import shutil

    from job_radar import linkedin_email_ingest

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    shutil.copy(BLANK[0], tmp_path / "config/search_config.yaml")
    shutil.copy(BLANK[1], tmp_path / "config/resume_profile.json")
    for name in ("LINKEDIN_IMAP_HOST", "LINKEDIN_IMAP_USER", "LINKEDIN_IMAP_PASSWORD"):
        monkeypatch.setenv(name, "set")

    def no_mailbox(*args, **kwargs):
        raise AssertionError("the mailbox must not be opened before setup")

    monkeypatch.setattr(linkedin_email_ingest.imaplib, "IMAP4_SSL", no_mailbox)
    assert linkedin_email_ingest.main() == 0
    assert "isn't set up yet" in capsys.readouterr().out
    assert not (tmp_path / "data").exists()


def test_your_config_files_load():
    """config/ and your master résumé parse, whether still blank or filled in."""
    settings = load_settings(ROOT / "config/search_config.yaml", ROOT / "config/resume_profile.json")
    assert isinstance(settings.config.get("search"), dict)
    assert isinstance(load_json(ROOT / "resumes/master_resume.json").get("identity"), dict)
