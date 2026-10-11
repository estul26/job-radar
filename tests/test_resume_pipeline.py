from pathlib import Path

from job_radar.issue_body import fingerprint_marker, parse_job, render_indeed
from job_radar.matcher import Vocabulary
from job_radar.resume.pipeline import generate_resume
from job_radar.settings import load_json, load_yaml

FIXTURES = Path(__file__).parent / "fixtures"

MASTER = load_json(FIXTURES / "master_resume.json")
VOCAB = Vocabulary.from_config(load_yaml(FIXTURES / "config/search_config.yaml"))


def sample_job():
    return {
        "fingerprint": "abc123def456",
        "source": "indeed",
        "title": "Security Operations Analyst",
        "company": "Example Security",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "2026-10-05",
        "job_url": "https://jobs.example.com/security-operations-analyst",
        "description": (
            "Monitor SIEM alerts, support incident response, document findings, "
            "and work with networking technologies. Python is nice to have."
        ),
        "score": 78,
        "hard_reject": False,
        "matched_skills": ["siem", "incident response", "documentation", "networking"],
        "missing_skills": [],
        "optional_missing_skills": ["python"],
        "matched_certs": [],
        "missing_certs": [],
        "score_reasons": [],
    }


def test_generate_indeed_resume_without_ai_network(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_RESUME_ENABLED", "false")

    result = generate_resume(sample_job(), MASTER, vocab=VOCAB)

    assert result["source"] == "indeed"
    assert result["job_key"] == "abc123def456"
    assert result["ai_used"] is False
    assert Path(result["resume_markdown"]).exists()
    assert Path(result["resume_docx"]).exists()
    assert Path(result["ai_audit"]).exists()
    # Only the job's own folder is written; `radar export` rebuilds resumes/index.csv.
    assert not Path("resumes/index.csv").exists()


def test_linkedin_resume_is_keyed_by_job_id(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_RESUME_ENABLED", "false")
    job = {**sample_job(), "source": "linkedin", "job_url": "https://www.linkedin.com/jobs/view/4471544570/"}

    result = generate_resume(job, MASTER, vocab=VOCAB, issue_number="1")

    assert result["job_key"] == "4471544570"
    assert result["folder"].startswith("resumes/jobs/4471544570-example-security-")
    assert result["issue_number"] == "1"


def test_indeed_issue_body_contains_stable_fingerprint():
    job = sample_job()
    item = {
        **job,
        "resume_markdown": "resumes/jobs/example/resume.md",
        "resume_docx": "resumes/jobs/example/resume.docx",
        "ai_used": True,
        "ai_model": "gpt-6.1-sol",
        "ai_status": "ai_validated",
    }
    body = render_indeed(item)
    assert fingerprint_marker(body) == job["fingerprint"]
    assert "### Job URL" in body
    assert job["job_url"] in body


def test_manual_indeed_issue_can_be_parsed_for_regeneration():
    job = sample_job()
    item = {
        **job,
        "resume_markdown": "resumes/jobs/example/resume.md",
        "resume_docx": "resumes/jobs/example/resume.docx",
        "ai_used": True,
        "ai_model": "gpt-6.1-sol",
        "ai_status": "ai_validated",
    }
    parsed = parse_job(render_indeed(item))
    assert parsed["source"] == "indeed"
    assert parsed["fingerprint"] == job["fingerprint"]
    assert parsed["job_url"] == job["job_url"]
    assert parsed["description"] == job["description"]
