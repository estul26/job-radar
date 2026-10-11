from pathlib import Path

from job_radar.matcher import score_job
from job_radar.settings import load_json, load_yaml

FIXTURES = Path(__file__).parent / "fixtures"

CONFIG = load_yaml(FIXTURES / "config/search_config.yaml")
PROFILE = load_json(FIXTURES / "resume_profile.json")


def test_high_match_soc_job():
    job = {
        "fingerprint": "1",
        "title": "SOC Analyst I",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "2026-10-04T12:00:00+00:00",
        "description": "1 year experience. Splunk, QRadar, incident response, Active Directory, DNS, Security+.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert scored["score"] >= 70
    assert scored["hard_reject"] is False
    assert "splunk" in scored["matched_skills"]


def test_missing_skill_is_not_invented():
    job = {
        "fingerprint": "2",
        "title": "Security Operations Analyst",
        "company": "Example",
        "location": "Canada",
        "is_remote": True,
        "date_posted": "2026-10-04T12:00:00+00:00",
        "description": "Microsoft Sentinel and CrowdStrike EDR required.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert "microsoft sentinel" in scored["missing_skills"]
    assert "crowdstrike" in scored["missing_skills"]


def test_senior_role_is_rejected():
    job = {
        "fingerprint": "3",
        "title": "Senior SOC Analyst",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "2026-10-04T12:00:00+00:00",
        "description": "5+ years experience.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert scored["hard_reject"] is True


def test_unrelated_title_is_rejected():
    job = {
        "fingerprint": "4",
        "title": "Technical Support Analyst",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "2026-10-04T12:00:00+00:00",
        "description": "Active Directory, Windows, documentation, escalation.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert scored["hard_reject"] is True
    assert "unrelated title" in scored["hard_reject_reasons"]


def test_security_guard_is_rejected():
    job = {
        "fingerprint": "5",
        "title": "Security Guard - Casual",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "2026-10-04T12:00:00+00:00",
        "description": "Documentation and escalation.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert scored["hard_reject"] is True


def test_associate_does_not_match_soc_substring():
    job = {
        "fingerprint": "6",
        "title": "Analyst/Associate, Corporate Banking",
        "company": "Example",
        "location": "Ottawa, ON",
        "is_remote": False,
        "date_posted": "2026-10-04T12:00:00+00:00",
        "description": "Documentation and financial analysis.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert scored["hard_reject"] is True
    assert "unrelated title" in scored["hard_reject_reasons"]


def test_optional_section_does_not_penalize_core_fit():
    job = {
        "fingerprint": "7",
        "title": "Cyber Defense Engineer",
        "company": "Example",
        "location": "Canada",
        "is_remote": True,
        "date_posted": "",
        "description": (
            "2+ years of SOC experience. SIEM, incident response, detection engineering, "
            "documentation. Nice To Have Python, PowerShell, and SOAR."
        ),
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert scored["hard_reject"] is False
    assert "python" in scored["optional_missing_skills"]
    assert "python" not in scored["missing_skills"]
    assert scored["score"] >= 65


def test_detection_word_alone_is_not_a_cyber_title():
    job = {
        "fingerprint": "k9",
        "title": "K9 Handler (Detection Services)",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "2026-10-05",
        "description": "Maintain documentation of each search.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert scored["hard_reject"] is True
    assert "unrelated title" in scored["hard_reject_reasons"]


def test_threat_word_counts_with_security_context():
    job = {
        "fingerprint": "threat",
        "title": "Security Engineer (Threat Response)",
        "company": "Example",
        "location": "Canada",
        "is_remote": True,
        "date_posted": "2026-10-05",
        "description": "Splunk and incident response.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert "unrelated title" not in scored["hard_reject_reasons"]


def test_soft_skills_alone_do_not_earn_full_skill_points():
    job = {
        "fingerprint": "soft",
        "title": "Security Analyst",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "2026-10-05",
        "description": "Keep clear documentation and escalate issues.",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert "few explicit technology requirements detected" in scored["score_reasons"]
    assert "documentation" in scored["matched_skills"]


def test_reject_terms_respect_word_boundaries():
    job = {
        "fingerprint": "guardium",
        "title": "IBM Guardium Security Analyst",
        "company": "Example",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "2026-10-05",
        "description": "",
    }
    scored = score_job(job, PROFILE, CONFIG)
    assert "guard" not in scored["hard_reject_reasons"]


def test_location_points_come_from_the_configured_locations():
    from job_radar.matcher import location_score

    places = CONFIG["search"]["locations"]
    assert location_score({"location": "Toronto, ON"}, places) == (5, "Toronto location")
    assert location_score({"location": "Ottawa, ON, CA"}, places) == (4, "Ontario location")
    assert location_score({"location": "Vancouver, BC, Canada"}, places) == (3, "Canada location")
    assert location_score({"location": "Remote", "is_remote": True}, places, remote_score=4) == (4, "remote role")
    # The province abbreviation only counts after a comma, on a word boundary.
    assert location_score({"location": "Abbotsford, BC"}, places) == (1, "location needs review")
    assert location_score({"location": "Remote - Oneida"}, places) == (1, "location needs review")
    assert location_score({"location": "Toronto"}, []) == (1, "location needs review")


def test_phrases_match_whole_words_and_re_prefix_means_regex():
    from job_radar.normalize import phrase_found

    assert phrase_found("Registered Nurse (RN)", ["nurse"])
    assert not phrase_found("Nursery Teacher", ["nurse"])
    assert phrase_found("Needs CompTIA  Security+", ["comptia security+"])
    assert phrase_found("TCP/IP and TCPIP", ["re:tcp/?ip"])
    assert phrase_found("C++ developer", ["re:c\\+\\+"])
    assert not phrase_found("anything", ["", "re:"])


def test_a_skill_without_phrases_is_looked_for_by_name():
    from job_radar.matcher import Vocabulary, detect_skills

    vocab = Vocabulary.from_config(
        {"matching": {"skills": {"wound care": [], "IV therapy": ["iv therapy", "re:\\biv\\b"]}}}
    )
    assert detect_skills("Wound care and IV starts.", vocab) == {"wound care", "IV therapy"}
    assert Vocabulary.from_config({}).skills == {}


NURSING = {
    "timezone": "America/Toronto",
    "search": {
        "titles": ["Registered Nurse", "Staff Nurse"],
        "locations": [{"name": "Toronto", "query": "Toronto, ON", "score": 5, "match": ["toronto"]}],
    },
    "ranking": {
        "fresh_hours": 24,
        "hard_reject_unrelated_titles": True,
        "hard_reject_title_terms": ["nursing assistant", "manager"],
        "hard_reject_min_years": 5,
    },
    "matching": {
        "skills": {
            "patient assessment": ["patient assessment", "assess patients"],
            "medication administration": ["medication administration", "administer medication"],
            "epic": ["epic"],
            "wound care": [],
            "communication": [],
        },
        "soft_skills": ["communication"],
        "certifications": {"BLS": ["bls", "basic life support"], "ACLS": ["acls"]},
        "related_title_keywords": ["nurse", "nursing", "rn"],
        "context_title_keywords": ["care"],
        "context_words": ["patient", "clinical"],
    },
}
NURSE_PROFILE = {
    "experience_years": 2,
    "skills": ["patient assessment", "medication administration", "wound care", "communication"],
    "certifications": ["BLS"],
}


def _nursing_job(title: str, description: str = "") -> dict:
    return {
        "fingerprint": title,
        "title": title,
        "company": "Example General Hospital",
        "location": "Toronto, ON",
        "is_remote": False,
        "date_posted": "",
        "description": description,
    }


def test_any_field_scores_from_config_alone():
    scored = score_job(
        _nursing_job(
            "Registered Nurse - Medical/Surgical",
            "2+ years of acute care. Patient assessment, medication administration and wound care. "
            "Current BLS required. Strong communication.",
        ),
        NURSE_PROFILE,
        NURSING,
    )
    assert scored["hard_reject"] is False
    assert scored["score"] >= 80
    assert scored["matched_skills"] == [
        "communication",
        "medication administration",
        "patient assessment",
        "wound care",
    ]
    assert scored["matched_certs"] == ["BLS"]
    assert "Toronto location" in scored["score_reasons"]

    gap = score_job(_nursing_job("Staff Nurse", "Epic charting and ACLS required."), NURSE_PROFILE, NURSING)
    assert gap["missing_skills"] == ["epic"] and gap["missing_certs"] == ["ACLS"]


def test_any_field_titles_and_rejects_come_from_config():
    related = score_job(_nursing_job("Nurse Practitioner"), NURSE_PROFILE, NURSING)
    assert related["hard_reject"] is False and "partially related title" in related["score_reasons"]
    assert score_job(_nursing_job("Patient Care Coordinator"), NURSE_PROFILE, NURSING)["hard_reject"] is False
    assert (
        "unrelated title"
        in score_job(_nursing_job("Customer Care Agent"), NURSE_PROFILE, NURSING)["hard_reject_reasons"]
    )
    assert score_job(_nursing_job("Nursing Assistant"), NURSE_PROFILE, NURSING)["hard_reject"] is True
