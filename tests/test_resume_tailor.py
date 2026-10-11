from pathlib import Path

from job_radar.ids import linkedin_job_id
from job_radar.issue_body import parse_job
from job_radar.matcher import Vocabulary, score_job
from job_radar.resume.render import markdown_resume
from job_radar.resume.tailor import tailor_content
from job_radar.settings import load_json, load_yaml

FIXTURES = Path(__file__).parent / "fixtures"

MASTER = load_json(FIXTURES / "master_resume.json")
PROFILE = load_json(FIXTURES / "resume_profile.json")
CONFIG = load_yaml(FIXTURES / "config/search_config.yaml")


def test_linkedin_job_id():
    assert linkedin_job_id("https://www.linkedin.com/jobs/view/4471544570/") == "4471544570"


def test_tailored_resume_never_adds_missing_python():
    body = """### LinkedIn job URL

https://www.linkedin.com/jobs/view/4471544570/

### Job title

SOC Analyst I

### Company

Example Security

### Location

Remote Canada

### Remote?

Yes

### Date posted (optional)



### Job description

SOC alert triage using SIEM, Splunk, incident response, networking and documentation.
Python is preferred.
"""
    job = parse_job(body)
    scored = score_job(job, PROFILE, CONFIG)
    content = tailor_content(MASTER, job, scored, vocab=Vocabulary.from_config(CONFIG))
    text = markdown_resume(content)

    assert "Splunk" in text
    assert "incident response" in text.lower()
    assert "Python" not in text
    assert "SOC Analyst | Security+ Certified" in text


def test_empty_sections_are_left_out_and_company_is_shown():
    content = {
        "identity": {"name": "Sam Rivera", "headline": "", "email": "sam@example.com", "phone": ""},
        "summary": "Registered Nurse with three years of acute-care experience.",
        "technical_skills": [{"text": "Patient assessment, wound care"}],
        "experience": [{"role": "Registered Nurse", "company": "Example General", "dates": "2023 - Present"}],
        "education": [],
        "certifications": [],
    }
    text = markdown_resume(content)
    assert "sam@example.com" in text and " |  | " not in text
    assert "**Registered Nurse | Example General | 2023 - Present**" in text
    assert "- Patient assessment, wound care" in text
    assert "## EDUCATION" not in text and "## CERTIFICATIONS" not in text
