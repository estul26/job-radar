"""radar doctor on the shipped blank template and on a filled-in setup."""

import json
import re
from dataclasses import replace

import pytest

from conftest import CONFIG, MASTER, PROFILE, ROOT
from job_radar.cli import main
from job_radar.commands.doctor import check_sites, checkup, resume_ready
from job_radar.commands.scan import generate_scan_resumes, scan_jobs
from job_radar.matcher import score_job
from job_radar.settings import Paths, load_json, load_settings

# A copy of the template as it ships: config/ itself is yours to fill in, and the tests must
# pass either way.
BLANK_DIR = ROOT / "tests/fixtures/blank"
BLANK = (BLANK_DIR / "search_config.yaml", BLANK_DIR / "resume_profile.json", BLANK_DIR / "master_resume.json")


def test_the_shipped_template_lists_what_to_fill_in():
    # daily-jobs.yml skips the scan on NOT_SET_UP but fails the run on any other non-zero exit (a crash).
    assert main(["doctor", "--config", str(BLANK[0]), "--profile", str(BLANK[1]), "--master", str(BLANK[2])]) == 3
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
        "  locations: [{name: Toronto}, {name: Ottawa, query: Ottawa, distance: ten}]\n"
        "matching:\n  skills: {wound care: []}\n",
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"experience_years": "2", "skills": ["wound care", "phlebotomy"]}), encoding="utf-8")

    result = checkup(config, profile, MASTER)

    problems = "\n".join(result.problems)
    assert "'Mars/Olympus' is not an IANA timezone" in problems
    assert "search.locations[0] (Toronto) needs a query" in problems
    assert "search.locations[1] (Ottawa): distance must be a whole number of miles" in problems
    assert "experience_years must be a whole number" in problems
    assert "can never match a posting: phlebotomy" in "\n".join(result.warnings)


def _check_sites(sites, country):
    problems, warnings = [], []
    check_sites(sites, country, problems.append, warnings.append)
    return problems, warnings


@pytest.mark.parametrize("country", ["Germany", "united kingdom", " US ", "UAE", "Türkiye", "turkey"])
def test_countries_are_recognised_by_name_or_alias(country):
    assert _check_sites(["indeed"], country) == ([], [])


def test_every_country_the_docs_list_is_one_indeed_supports():
    docs = " ".join((ROOT / "docs/configure.md").read_text(encoding="utf-8").split())
    listed = re.search(r"Set `country_indeed` to one of: (.+?)\. Add to", docs).group(1)
    countries = re.split(r", | or ", listed)
    assert len(countries) > 50
    for country in countries:
        assert _check_sites(["indeed"], country) == ([], []), country


def test_a_country_indeed_doesnt_cover_is_a_problem():
    problems, _ = _check_sites(["indeed"], "Atlantis")
    assert len(problems) == 1 and "Indeed doesn't support 'Atlantis'" in problems[0]


def test_glassdoor_warns_only_where_it_has_no_site():
    assert _check_sites(["indeed", "glassdoor"], "Germany") == ([], [])
    assert _check_sites(["indeed", "glassdoor"], "Japan") == (
        [],
        ["search.sites: Glassdoor doesn't cover Japan, so only the other boards are searched"],
    )


def test_an_unknown_job_board_is_a_problem():
    problems, _ = _check_sites(["indeed", "monster"], "Canada")
    assert len(problems) == 1 and "'monster' isn't a job board JobSpy knows" in problems[0]


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


# How people write settings by hand on GitHub: one title without its "- ", skills as a list like
# the titles, one location without its "- ", and no ranking section at all.
HAND_WRITTEN = """timezone: America/Edmonton
search:
  sites: indeed
  country_indeed: Canada
  titles: IT Support Specialist
  locations:
    name: Edmonton
    query: Edmonton, AB
matching:
  skills:
    - windows
    - active directory: [active directory, AD]
  certifications:
    - CompTIA A+
"""


def test_settings_written_by_hand_are_understood(tmp_path, monkeypatch):
    config = tmp_path / "search_config.yaml"
    config.write_text(HAND_WRITTEN, encoding="utf-8")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"experience_years": 4, "skills": "windows", "certifications": []}), "utf-8")

    result = checkup(config, profile, MASTER)
    assert result.ok, result.problems

    settings = load_settings(config, profile)
    search = settings.config["search"]
    assert search["titles"] == ["IT Support Specialist"] and search["sites"] == ["indeed"]
    assert search["locations"] == [{"name": "Edmonton", "query": "Edmonton, AB"}]
    assert settings.config["matching"]["skills"] == {"windows": [], "active directory": ["active directory", "AD"]}
    assert settings.profile["skills"] == ["windows"]

    posting = {"title": "IT Support Specialist", "description": "Windows and AD support.", "location": "Edmonton, AB"}
    scored = score_job(posting, settings.profile, settings.config)
    assert scored["matched_skills"] == ["windows"] and scored["missing_skills"] == ["active directory"]
    assert "target-role title" in scored["score_reasons"]

    from job_radar import collector

    searched = []
    monkeypatch.setattr(collector, "scrape_jobs", lambda **kwargs: searched.append(kwargs["search_term"]))
    collector.collect_jobs(settings.config)
    assert searched == ["IT Support Specialist"]  # not "I", "T", " ", …


def test_shapes_the_radar_cannot_read_are_named(tmp_path):
    config = tmp_path / "search_config.yaml"
    config.write_text(
        "timezone: UTC\nsearch:\n  sites: [indeed]\n  country_indeed: Canada\n  titles: {Analyst: yes}\n"
        "  locations: Edmonton\nmatching:\n  skills: 3\n",
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"experience_years": True, "skills": {"windows": 1}}), encoding="utf-8")

    problems = "\n".join(checkup(config, profile, MASTER).problems)
    assert "search.titles must be a list: one entry per line, each starting with '- '" in problems
    assert "search.locations[0] needs a name" in problems
    assert "matching.skills must list names with their phrases" in problems
    assert "experience_years must be a whole number" in problems
    assert 'skills must be a list in square brackets, e.g. ["excel", "xero"]' in problems
