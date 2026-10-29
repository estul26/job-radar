from dataclasses import replace
from pathlib import Path

import pytest

from job_radar.settings import Paths, load_settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
ISSUE_FIXTURES = FIXTURES / "issues"
# A filled-in setup for a made-up registered nurse; the shipped config/ is a blank template.
CONFIG = FIXTURES / "config" / "search_config.yaml"
PROFILE = FIXTURES / "resume_profile.json"
MASTER = FIXTURES / "master_resume.json"


@pytest.fixture
def issue_body():
    """Job Issue bodies as the radar writes them: linkedin_form, indeed, indeed_markdown_headings, linkedin_alert."""

    def load(name: str) -> str:
        return (ISSUE_FIXTURES / f"{name}.md").read_text(encoding="utf-8")

    return load


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """The fixture config and profile, a 60% good-match threshold, AI off, and all state under tmp_path."""
    monkeypatch.setenv("AI_RESUME_ENABLED", "false")
    base = load_settings(CONFIG, PROFILE, env={"GOOD_MATCH_THRESHOLD": "60"})
    paths = Paths.from_config(
        {
            "report_path": str(tmp_path / "reports/latest.md"),
            "latest_jobs_path": str(tmp_path / "data/latest_jobs.csv"),
            "seen_jobs_path": str(tmp_path / "data/seen_jobs.json"),
            "applications_path": str(tmp_path / "data/applications.csv"),
            "scan_matches_path": str(tmp_path / "reports/scan-matches.json"),
            "resume_manifest_path": str(tmp_path / "reports/indeed-resume-manifest.json"),
            "resume_dir": str(tmp_path / "resumes/jobs"),
            "resume_index_path": str(tmp_path / "resumes/index.csv"),
            "master_resume_path": str(MASTER),
            "pending_resume_path": str(tmp_path / "reports/resume-generation.json"),
        }
    )
    return replace(base, paths=paths)
