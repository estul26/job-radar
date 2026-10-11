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


def test_tailored_resume_never_adds_a_missing_skill():
    body = """### LinkedIn job URL

https://www.linkedin.com/jobs/view/4471544570/

### Job title

Registered Nurse I

### Company

Example Health

### Location

Remote Canada

### Remote?

Yes

### Date posted (optional)



### Job description

Wound care, IV therapy, infection control and charting on a surgical unit.
Epic is preferred.
"""
    job = parse_job(body)
    scored = score_job(job, PROFILE, CONFIG)
    content = tailor_content(MASTER, job, scored, vocab=Vocabulary.from_config(CONFIG))
    text = markdown_resume(content)

    assert "wound care" in text.lower()
    assert "IV therapy" in text
    assert "Epic" not in text
    assert "Registered Nurse | BLS Certified" in text
    # The Registered Nurse role keeps its three most relevant bullets (max_bullets: 3).
    assert "Dressed surgical and pressure wounds" in text
    assert "Assessed and cared for up to six patients" not in text


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


def test_a_right_to_left_resume_reads_from_the_right(tmp_path):
    import zipfile

    from job_radar.resume.render import docx_resume

    content = {
        "identity": {"name": "سارة أحمد", "headline": "ممرضة مسجلة", "email": "sara@example.com"},
        "summary": "ممرضة مسجلة بخبرة ثلاث سنوات.",
        "technical_skills": [{"text": "تقييم المرضى"}],
        "experience": [{"role": "ممرضة", "dates": "2022", "bullets": [{"text": "رعاية المرضى."}]}],
        "education": [],
        "certifications": [],
        "direction": "rtl",
    }
    docx_resume(content, tmp_path / "rtl.docx")
    docx_resume({**content, "direction": "ltr"}, tmp_path / "ltr.docx")

    rtl = zipfile.ZipFile(tmp_path / "rtl.docx").read("word/document.xml").decode()
    assert rtl.count("<w:bidi/>") == rtl.count("<w:p>") + rtl.count("<w:p ")
    assert "<w:rtl/>" in rtl
    assert "<w:bidi/>" not in zipfile.ZipFile(tmp_path / "ltr.docx").read("word/document.xml").decode()
