from pathlib import Path

from job_radar.ids import linkedin_job_id
from job_radar.issue_body import parse_job
from job_radar.matcher import Vocabulary, detect_skills, score_job
from job_radar.resume.render import markdown_resume
from job_radar.resume.tailor import sorted_certifications, tailor_content, tailored_summary
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


CAPABILITIES = [item["text"] for item in MASTER["summary"]["capabilities"]]


def summary_capabilities(job_text: str) -> list[str]:
    vocab = Vocabulary.from_config(CONFIG)
    summary = tailored_summary(MASTER, job_text, detect_skills(job_text, vocab))
    return [text for text in CAPABILITIES if text in summary.split("Experience includes", 1)[1]]


def test_summary_names_at_most_four_capabilities():
    # All six of the fixture's capabilities match this posting; one readable sentence keeps four.
    job_text = "Patient assessment, medication administration, wound care, IV therapy, infection control and charting."
    assert len(summary_capabilities(job_text)) == 4


def test_summary_falls_back_to_your_first_three_capabilities():
    assert summary_capabilities("Front desk scheduling and phone reception.") == CAPABILITIES[:3]


def cert_entries(*entries: tuple[str, list[str], int]) -> list[dict]:
    return [{"text": text, "tags": tags, "priority": priority} for text, tags, priority in entries]


def test_certifications_the_posting_names_come_first_then_your_priority():
    vocab = Vocabulary.from_config(CONFIG)
    certs = cert_entries(
        ("Basic Life Support (BLS)", ["bls"], 1),
        # Broad skill tags: they used to lift this certificate above the ones a posting names.
        ("Online Wound Care Certificate", ["wound care", "patient assessment", "charting"], 3),
        ("Registered Nurse, College of Nurses of Ontario", ["cno"], 2),
    )
    asks_for_cno = "Wound care and charting. Must be registered with the College of Nurses of Ontario."
    order = [item["text"] for item in sorted_certifications(certs, asks_for_cno, vocab)]
    assert order == [
        "Registered Nurse, College of Nurses of Ontario",
        "Basic Life Support (BLS)",
        "Online Wound Care Certificate",
    ]

    no_certs_named = "Wound care, patient assessment and charting."
    order = [item["text"] for item in sorted_certifications(certs, no_certs_named, vocab)]
    assert order == [
        "Basic Life Support (BLS)",
        "Registered Nurse, College of Nurses of Ontario",
        "Online Wound Care Certificate",
    ]
