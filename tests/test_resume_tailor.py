from pathlib import Path

from job_radar.ids import linkedin_job_id
from job_radar.issue_body import parse_job
from job_radar.matcher import Vocabulary, detect_skills, score_job
from job_radar.resume.render import markdown_resume
from job_radar.resume.tailor import (
    sorted_certifications,
    tag_relevance,
    tailor_content,
    tailored_projects,
    tailored_summary,
)
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


def test_markdown_is_standard_so_converters_keep_lines_and_bullets():
    job = {"title": "Registered Nurse", "description": "Wound care and charting."}
    content = tailor_content(MASTER, job, {}, vocab=Vocabulary.from_config(CONFIG))
    content["certifications"] = [{"text": f"Certificate {n}"} for n in range(1, 6)]
    lines = markdown_resume(content).split("\n")

    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        # A list needs a blank line before it, or strict converters (pandoc) fold it into the paragraph above.
        if line.startswith("- "):
            assert previous == "" or previous.startswith("- "), f"no blank line before: {line}"
        # A paragraph right after a list item would be read as part of that item.
        elif line and previous.startswith("- "):
            raise AssertionError(f"no blank line after the list: {line}")
        # Two lines of one paragraph need a hard break, or they are joined into one line.
        elif line and previous and not line.startswith("#"):
            assert previous.endswith("  "), f"no line break before: {line}"
    assert lines[-2].startswith("Additional certificates: Certificate 5") and lines[-1] == ""


def test_projects_get_their_own_section_between_experience_and_education():
    job = {"title": "Registered Nurse", "description": "Wound care and charting."}
    content = tailor_content(MASTER, job, {}, vocab=Vocabulary.from_config(CONFIG))
    text = markdown_resume(content)

    assert text.index("## PROFESSIONAL EXPERIENCE") < text.index("## PROJECTS") < text.index("## EDUCATION")
    project = text.split("## PROJECTS", 1)[1].split("## EDUCATION", 1)[0]
    heading = "**Ward Handover Checklist**  \nSelf-directed project, https://example.com/handover | 2024\n\n- Wrote"
    assert heading in project
    # A master résumé without the key (every copy made before it existed) has no such section.
    without = {key: value for key, value in MASTER.items() if key != "projects"}
    assert "## PROJECTS" not in markdown_resume(tailor_content(without, job, {}, vocab=Vocabulary.from_config(CONFIG)))


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


def test_tags_match_whole_words_only():
    # "ai" used to match inside "maintain" and "email", lifting an AI line for every posting.
    assert tag_relevance(["ai"], "Maintain the email system and detail every repair.", set()) == 0
    assert tag_relevance(["ai"], "Experience with AI tools is an asset.", set()) == 3
    assert tag_relevance(["comptia security+"], "CompTIA Security+ preferred.", set()) == 3
    # Words of a tag the posting doesn't name count one each, as whole words too.
    assert tag_relevance(["log analysis"], "Run root-cause analysis on outages.", set()) == 1
    assert tag_relevance(["log analysis"], "Analyses of outages.", set()) == 0
    # A skill the posting asks for (detected through its config phrases) counts most.
    assert tag_relevance(["wound care"], "Dressings.", {"wound care"}) == 5


def _project(name, *bullets, **extra):
    return {"name": name, "dates": "2026", "bullets": [{"text": t, "tags": tags} for t, tags in bullets], **extra}


PROJECTS = {
    "projects": [
        _project("Clinic Rota", ("Built a staff rota.", ["scheduling"]), ("Wrote its guide.", ["documentation"])),
        _project(
            "Wound Audit",
            ("Audited wound dressings.", ["wound care"]),
            ("Charted the results.", ["charting"]),
            ("Presented them.", ["presenting"]),
            max_bullets=2,
        ),
    ]
}


def test_the_most_relevant_project_comes_first_with_its_most_relevant_bullets():
    projects = tailored_projects(PROJECTS, "Wound care and charting.", {"wound care", "charting"})

    assert [p["name"] for p in projects] == ["Wound Audit", "Clinic Rota"]
    assert [b["text"] for b in projects[0]["bullets"]] == ["Audited wound dressings.", "Charted the results."]
    # Without max_bullets a project keeps every bullet.
    assert len(projects[1]["bullets"]) == 2


def test_ties_keep_your_order_and_max_projects_keeps_the_most_relevant():
    assert [p["name"] for p in tailored_projects(PROJECTS, "Unrelated.", set())] == ["Clinic Rota", "Wound Audit"]
    only_one = {**PROJECTS, "max_projects": 1}
    assert [p["name"] for p in tailored_projects(only_one, "Staff scheduling.", set())] == ["Clinic Rota"]
    assert tailored_projects({}, "Anything.", set()) == []


def test_a_project_with_many_bullets_on_one_topic_does_not_outrank_a_broader_one():
    narrow = _project("Narrow", *[(f"Wound step {n}.", ["wound care"]) for n in range(4)])
    broad = _project("Broad", ("Wound check.", ["wound care"]), ("Chart it.", ["charting"]))
    detected = {"wound care", "charting"}
    names = [p["name"] for p in tailored_projects({"projects": [narrow, broad]}, "Wound care, charting.", detected)]
    assert names == ["Broad", "Narrow"]
