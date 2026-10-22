"""Scoring, driven entirely by config: the fixture is a registered nurse in Toronto."""

from pathlib import Path

from job_radar.matcher import Vocabulary, detect_skills, location_score, score_job
from job_radar.normalize import phrase_found
from job_radar.settings import load_json, load_yaml

FIXTURES = Path(__file__).parent / "fixtures"

CONFIG = load_yaml(FIXTURES / "config/search_config.yaml")
PROFILE = load_json(FIXTURES / "resume_profile.json")


def job(title: str, description: str = "", location: str = "Toronto, ON", remote: bool = False) -> dict:
    return {
        "fingerprint": title,
        "title": title,
        "company": "Example Health",
        "location": location,
        "is_remote": remote,
        "date_posted": "2026-10-04T12:00:00+00:00",
        "description": description,
    }


def test_a_strong_match_scores_high():
    scored = score_job(
        job(
            "Registered Nurse - Medical/Surgical",
            "1 year experience. Patient assessment, medication administration, wound care, IV therapy. BLS required.",
        ),
        PROFILE,
        CONFIG,
    )
    assert scored["score"] >= 70
    assert scored["hard_reject"] is False
    assert "wound care" in scored["matched_skills"]
    assert scored["matched_certs"] == ["BLS"]


def test_missing_skill_is_not_invented():
    scored = score_job(job("Staff Nurse", "Epic charting and telemetry required.", "Canada", True), PROFILE, CONFIG)
    assert "epic" in scored["missing_skills"]
    assert "telemetry" in scored["missing_skills"]
    assert "charting" in scored["matched_skills"]


def test_senior_role_is_rejected():
    scored = score_job(job("Senior Charge Nurse", "5+ years experience."), PROFILE, CONFIG)
    assert scored["hard_reject"] is True
    assert "senior" in scored["hard_reject_reasons"]


def test_unrelated_title_is_rejected():
    scored = score_job(job("Medical Receptionist", "Charting, communication and teamwork."), PROFILE, CONFIG)
    assert scored["hard_reject"] is True
    assert "unrelated title" in scored["hard_reject_reasons"]


def test_excluded_titles_are_rejected():
    scored = score_job(job("Nursing Assistant - Casual", "Teamwork and communication."), PROFILE, CONFIG)
    assert scored["hard_reject"] is True
    assert "nursing assistant" in scored["hard_reject_reasons"]


def test_short_keywords_match_whole_words_only():
    # "rn" is a related-title keyword, but "Intern" and "Learning" don't contain it as a word.
    scored = score_job(job("Intern, Learning and Development"), PROFILE, CONFIG)
    assert scored["hard_reject"] is True
    assert "unrelated title" in scored["hard_reject_reasons"]
    assert "unrelated title" not in score_job(job("RN - Float Pool"), PROFILE, CONFIG)["hard_reject_reasons"]


def test_optional_section_does_not_penalize_core_fit():
    scored = score_job(
        job(
            "Clinical Nurse",
            "2+ years of acute care. Patient assessment, medication administration, wound care, charting. "
            "Nice To Have Epic, Meditech, and ACLS.",
            "Canada",
            True,
        ),
        PROFILE,
        CONFIG,
    )
    assert scored["hard_reject"] is False
    assert "epic" in scored["optional_missing_skills"]
    assert "epic" not in scored["missing_skills"]
    assert scored["score"] >= 65


def test_a_context_word_alone_does_not_make_a_title_related():
    scored = score_job(job("Customer Care Agent", "Charting of each call."), PROFILE, CONFIG)
    assert scored["hard_reject"] is True
    assert "unrelated title" in scored["hard_reject_reasons"]


def test_a_context_word_counts_next_to_its_context():
    scored = score_job(job("Patient Care Coordinator", "Patient assessment."), PROFILE, CONFIG)
    assert "unrelated title" not in scored["hard_reject_reasons"]
    assert "partially related title" in scored["score_reasons"]


def test_soft_skills_alone_do_not_earn_full_skill_points():
    scored = score_job(job("Registered Nurse", "Great communication and teamwork."), PROFILE, CONFIG)
    assert "few explicit skill requirements detected" in scored["score_reasons"]
    assert "communication" in scored["matched_skills"]


def test_a_missing_soft_skill_is_an_optional_gap_not_a_missing_core_skill():
    profile = {**PROFILE, "skills": [skill for skill in PROFILE["skills"] if skill != "teamwork"]}
    scored = score_job(job("Registered Nurse", "Wound care and teamwork required."), profile, CONFIG)
    assert scored["missing_skills"] == []
    assert scored["optional_missing_skills"] == ["teamwork"]


def test_reject_terms_respect_word_boundaries():
    scored = score_job(job("Registered Nurse - Leading Care Home"), PROFILE, CONFIG)
    assert "lead" not in scored["hard_reject_reasons"]


def test_location_points_come_from_the_configured_locations():
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
    assert phrase_found("Registered Nurse (RN)", ["nurse"])
    assert not phrase_found("Nursery Teacher", ["nurse"])
    assert phrase_found("Needs  Basic Life Support", ["basic life support"])
    assert phrase_found("TCP/IP and TCPIP", ["re:tcp/?ip"])
    assert phrase_found("C++ developer", ["c++"])
    assert not phrase_found("anything", ["", "re:"])


def test_a_skill_without_phrases_is_looked_for_by_name():
    skills = {"wound care": [], "IV therapy": ["iv therapy", "re:\\biv\\b"]}
    vocab = Vocabulary.from_config({"matching": {"skills": skills}})
    assert detect_skills("Wound care and IV starts.", vocab) == {"wound care", "IV therapy"}
    assert Vocabulary.from_config({}).skills == {}


ACCOUNTING = {
    "timezone": "Europe/London",
    "search": {
        "titles": ["Accountant", "Management Accountant"],
        "locations": [{"name": "London", "query": "London", "score": 5}],
    },
    "ranking": {
        "hard_reject_unrelated_titles": True,
        "hard_reject_title_terms": ["head of", "director"],
        "hard_reject_min_years": 5,
    },
    "matching": {
        "skills": {
            "xero": [],
            "sap": [],
            "month-end close": ["month-end close", "month end"],
            "financial statements": ["financial statements", "statutory accounts"],
        },
        "certifications": {"ACCA": ["acca"], "CIMA": ["cima"]},
        "related_title_keywords": ["accounting", "accounts", "finance"],
    },
}
ACCOUNTANT = {"experience_years": 3, "skills": ["xero", "month-end close", "financial statements"]}


def test_another_field_scores_from_config_alone():
    posting = job(
        "Management Accountant",
        "You'll own the month-end close and prepare financial statements in Xero. 2 to 4 years of "
        "experience. Nice to have: SAP and CIMA.",
        "London",
    )
    scored = score_job(posting, ACCOUNTANT, ACCOUNTING)
    assert scored["hard_reject"] is False and scored["score"] >= 80
    assert scored["matched_skills"] == ["financial statements", "month-end close", "xero"]
    assert scored["optional_missing_skills"] == ["sap"]
    assert "requires 2 year(s), within profile" in scored["score_reasons"]
    assert "London location" in scored["score_reasons"]

    assert score_job(job("Head of Finance", location="London"), ACCOUNTANT, ACCOUNTING)["hard_reject"]
    related = score_job(job("Accounts Payable Assistant", location="London"), ACCOUNTANT, ACCOUNTING)
    assert related["score_reasons"][0] == "partially related title"


def test_titles_match_whole_words():
    assert score_job(job("Registered Nurse II"), PROFILE, CONFIG)["score_reasons"][0] == "target-role title"
    config = {**CONFIG, "search": {**CONFIG["search"], "titles": ["Nurse"]}}
    nursery = score_job(job("Nursery Teacher"), PROFILE, config)
    assert nursery["hard_reject"] is True and "unrelated title" in nursery["hard_reject_reasons"]


def test_excluded_titles_are_rejected_however_the_job_arrived():
    config = {
        **CONFIG,
        "search": {**CONFIG["search"], "exclude_title_terms": ["float pool"]},
        "ranking": {**CONFIG["ranking"], "hard_reject_title_terms": []},
    }
    scored = score_job(job("Registered Nurse - Float Pool"), PROFILE, config)
    assert scored["hard_reject"] is True and scored["hard_reject_reasons"] == ["float pool"]


def test_a_posting_naming_few_skills_counts_them_only_partly():
    one = score_job(job("Registered Nurse", "Wound care."), PROFILE, CONFIG)
    three = score_job(job("Registered Nurse", "Wound care, IV therapy and patient assessment."), PROFILE, CONFIG)
    assert "matched 1/1 core detected skills (few named, so partly counted)" in one["score_reasons"]
    assert "matched 3/3 core detected skills" in three["score_reasons"]
    assert three["score"] - one["score"] == 35 - 24
