from pathlib import Path

from job_radar.issue_body import parse_job
from job_radar.matcher import Vocabulary, score_job
from job_radar.resume.ai import (
    apply_ai_payload,
    enhance_resume_with_ai,
    selected_bullet_catalog,
    validate_ai_payload,
)
from job_radar.resume.tailor import tailor_content
from job_radar.settings import load_json, load_yaml

FIXTURES = Path(__file__).parent / "fixtures"

MASTER = load_json(FIXTURES / "master_resume.json")
PROFILE = load_json(FIXTURES / "resume_profile.json")
CONFIG = load_yaml(FIXTURES / "config/search_config.yaml")
VOCAB = Vocabulary.from_config(CONFIG)


def _baseline():
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

SOC monitoring using SIEM, Splunk, incident response, networking and documentation.
Python and SOAR are preferred.
"""
    job = parse_job(body)
    scored = score_job(job, PROFILE, CONFIG)
    baseline = tailor_content(MASTER, job, scored, vocab=VOCAB)
    return job, baseline


def _safe_payload(baseline):
    selected = selected_bullet_catalog(baseline)
    return {
        "summary": baseline["summary"],
        "summary_source_ids": [
            "summary.experience",
            "summary.credentials",
            *[f"summary.capability.{index}" for index, _ in enumerate(MASTER["summary"]["capabilities"])],
        ],
        "bullet_rewrites": [{"source_id": source_id, "text": text} for source_id, text in selected.items()],
        "editor_notes": "No factual changes.",
    }


def test_rule_validator_accepts_source_preserving_payload():
    _, baseline = _baseline()
    payload = _safe_payload(baseline)
    assert validate_ai_payload(payload, MASTER, baseline, vocab=VOCAB) == []


def test_rule_validator_rejects_new_python_skill():
    _, baseline = _baseline()
    payload = _safe_payload(baseline)
    payload["bullet_rewrites"][0]["text"] += " Automated analysis with Python."

    errors = validate_ai_payload(payload, MASTER, baseline, vocab=VOCAB)
    assert any("python" in error.lower() for error in errors)


def test_rule_validator_rejects_new_metric():
    _, baseline = _baseline()
    payload = _safe_payload(baseline)
    payload["bullet_rewrites"][0]["text"] += " Reviewed 100 alerts per day."

    errors = validate_ai_payload(payload, MASTER, baseline, vocab=VOCAB)
    assert any("numeric claim" in error.lower() for error in errors)


def test_apply_ai_payload_updates_only_ai_editable_text():
    _, baseline = _baseline()
    payload = _safe_payload(baseline)
    payload["summary"] = baseline["summary"]
    source_id = payload["bullet_rewrites"][0]["source_id"]
    original = payload["bullet_rewrites"][0]["text"]
    payload["bullet_rewrites"][0]["text"] = original.replace("Worked with", "Used")

    enhanced = apply_ai_payload(baseline, payload)
    assert enhanced["identity"] == baseline["identity"]
    assert any(
        bullet.get("_source_id") == source_id and bullet["text"].startswith("Used")
        for experience in enhanced["experience"]
        for bullet in experience["bullets"]
    )


def test_missing_api_key_falls_back_without_failure():
    job, baseline = _baseline()
    content, audit = enhance_resume_with_ai(
        MASTER,
        job,
        baseline,
        vocab=VOCAB,
        api_key="",
        model="gpt-6.1-sol",
        enabled=True,
    )
    assert content == baseline
    assert audit["used"] is False
    assert audit["status"] == "fallback_missing_api_key"
