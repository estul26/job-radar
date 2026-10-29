import json
from pathlib import Path

from job_radar.issue_body import parse_job
from job_radar.matcher import Vocabulary, score_job
from job_radar.resume import ai
from job_radar.resume.ai import (
    apply_ai_payload,
    describe_ai,
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

Registered Nurse I

### Company

Example Health

### Location

Remote Canada

### Remote?

Yes

### Date posted (optional)



### Job description

Patient assessment, medication administration, wound care and charting on a telehealth line.
Epic and telemetry experience are preferred.
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


def test_rule_validator_rejects_a_skill_the_master_does_not_have():
    _, baseline = _baseline()
    payload = _safe_payload(baseline)
    payload["bullet_rewrites"][0]["text"] += " Charted every shift in Epic."

    errors = validate_ai_payload(payload, MASTER, baseline, vocab=VOCAB)
    assert any("epic" in error.lower() for error in errors)


def test_rule_validator_rejects_new_metric():
    _, baseline = _baseline()
    payload = _safe_payload(baseline)
    payload["bullet_rewrites"][0]["text"] += " Cared for 100 patients per week."

    errors = validate_ai_payload(payload, MASTER, baseline, vocab=VOCAB)
    assert any("numeric claim" in error.lower() for error in errors)


def test_apply_ai_payload_updates_only_ai_editable_text():
    _, baseline = _baseline()
    payload = _safe_payload(baseline)
    payload["summary"] = baseline["summary"]
    source_id = payload["bullet_rewrites"][0]["source_id"]
    original = payload["bullet_rewrites"][0]["text"]
    payload["bullet_rewrites"][0]["text"] = "Used " + original

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
    # What the Issue comment says: plain words and where to set it up, not the model it would have used.
    said = describe_ai(audit["status"], audit["model"])
    assert said.startswith("off") and "docs/setup.md" in said and "gpt" not in said


def _response(payload: dict, status: str = "completed") -> dict:
    return {"id": "resp_1", "status": status, "output_text": json.dumps(payload)}


def _fake_openai(monkeypatch, replies):
    """Replace the HTTP call: each request gets the next reply (a dict, or an exception to raise)."""
    sent = []

    def post(api_key, body):
        sent.append(json.loads(json.dumps(body)))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(ai, "_post_response", post)
    return sent


def test_both_calls_ask_for_structured_output_and_low_reasoning_effort(monkeypatch):
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    job, baseline = _baseline()
    verdict = {"pass": True, "unsupported_claims": [], "notes": "ok"}
    sent = _fake_openai(monkeypatch, [_response(_safe_payload(baseline)), _response(verdict)])

    _, audit = enhance_resume_with_ai(MASTER, job, baseline, vocab=VOCAB, api_key="k", model="m", enabled=True)

    assert audit["status"] == "ai_validated" and audit["reasoning_effort"] == "low"
    editor, validator = sent
    assert editor["text"]["format"]["name"] == "resume_rewrite" and editor["text"]["format"]["strict"] is True
    assert validator["text"]["format"]["schema"] == ai.VALIDATOR_SCHEMA
    assert editor["reasoning"] == validator["reasoning"] == {"effort": "low"}
    assert editor["max_output_tokens"] >= 8000 and validator["max_output_tokens"] >= 4000


def test_a_model_without_reasoning_settings_is_asked_again_without_them(monkeypatch):
    job, baseline = _baseline()
    rejected = ai.OpenAIHTTPError(400, '{"error": {"message": "Unsupported parameter: reasoning.effort"}}')
    verdict = {"pass": True, "unsupported_claims": [], "notes": "ok"}
    sent = _fake_openai(monkeypatch, [rejected, _response(_safe_payload(baseline)), _response(verdict)])

    _, audit = enhance_resume_with_ai(MASTER, job, baseline, vocab=VOCAB, api_key="k", model="m", enabled=True)

    assert audit["status"] == "ai_validated"
    assert "reasoning" in sent[0] and "reasoning" not in sent[1]


def test_a_response_cut_short_falls_back_and_says_why(monkeypatch):
    job, baseline = _baseline()
    cut = {"id": "r", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
    _fake_openai(monkeypatch, [cut])

    content, audit = enhance_resume_with_ai(MASTER, job, baseline, vocab=VOCAB, api_key="k", model="m", enabled=True)

    assert content == baseline and audit["status"] == "fallback_ai_error"
    assert "max_output_tokens" in audit["error"]


def test_reasoning_effort_default_leaves_it_to_the_model(monkeypatch):
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "default")
    job, baseline = _baseline()
    sent = _fake_openai(monkeypatch, [_response({"summary": ""})])
    enhance_resume_with_ai(MASTER, job, baseline, vocab=VOCAB, api_key="k", model="m", enabled=True)
    assert "reasoning" not in sent[0]
