"""Deterministic résumé tailoring: order and select master-résumé facts for a job."""

from __future__ import annotations

import re
from typing import Any

from ..matcher import Vocabulary, detect_certs, detect_skills
from ..normalize import phrase_found

# The summary's closing "Experience includes …" sentence names at most this many capabilities, so it
# stays one readable sentence, and at least this many when fewer of them match the job.
MAX_SUMMARY_CAPABILITIES = 4
MIN_SUMMARY_CAPABILITIES = 3


def slug(value: str, limit: int = 56) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text[:limit].rstrip("-") or "job"


def tag_relevance(tags: list[str], job_text: str, detected: set[str]) -> int:
    score = 0
    lower = job_text.lower()
    for tag in tags:
        tag_l = tag.lower()
        if tag_l in detected:
            score += 5
        elif tag_l and tag_l in lower:
            score += 3
        else:
            words = [w for w in re.split(r"[^a-z0-9+#]+", tag_l) if len(w) >= 4]
            score += sum(1 for word in words if word in lower)
    return score


def sorted_items(items: list[dict[str, Any]], job_text: str, detected: set[str]) -> list[dict[str, Any]]:
    indexed = list(enumerate(items))
    indexed.sort(
        key=lambda pair: (
            -tag_relevance(pair[1].get("tags", []), job_text, detected),
            int(pair[1].get("priority", 100 + pair[0])),
            pair[0],
        )
    )
    return [item for _, item in indexed]


def sorted_certifications(items: list[dict[str, Any]], job_text: str, vocab: Vocabulary) -> list[dict[str, Any]]:
    """The certifications the posting asks for first, then the rest in your `priority` order.

    Asked for means the posting names a certification in `matching.certifications` and the entry's
    text or tags contain one of that certification's phrases. Skill tags don't move a certification:
    one tagged "troubleshooting" would otherwise outrank the certification the posting names.
    """
    asked = [vocab.certifications[name] for name in detect_certs(job_text, vocab)]

    def is_asked(item: dict[str, Any]) -> bool:
        own = "\n".join([str(item.get("text", "")), *(str(tag) for tag in item.get("tags") or [])])
        return any(phrase_found(own, phrases) for phrases in asked)

    indexed = list(enumerate(items))
    indexed.sort(
        key=lambda pair: (
            not is_asked(pair[1]),
            int(pair[1].get("priority", 100 + pair[0])),
            pair[0],
        )
    )
    return [item for _, item in indexed]


def tailored_summary(master: dict[str, Any], job_text: str, detected: set[str]) -> str:
    summary = master.get("summary") or {}
    capabilities = sorted_items(summary.get("capabilities", []), job_text, detected)
    relevant = [item["text"] for item in capabilities if tag_relevance(item.get("tags", []), job_text, detected) > 0]
    if len(relevant) < MIN_SUMMARY_CAPABILITIES:
        # The sort put the relevant ones first; fill up with your next ones in order.
        relevant = [item["text"] for item in capabilities[:MIN_SUMMARY_CAPABILITIES]]
    else:
        relevant = relevant[:MAX_SUMMARY_CAPABILITIES]

    capability_text = ", ".join(relevant[:-1])
    if len(relevant) > 1:
        capability_text += f", and {relevant[-1]}"
    elif relevant:
        capability_text = relevant[0]

    parts = [summary.get("experience"), summary.get("credentials")]
    if capability_text:
        parts.append(f"Experience includes {capability_text}.")
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def tailor_content(
    master: dict[str, Any], job: dict[str, Any], scored: dict[str, Any], *, vocab: Vocabulary
) -> dict[str, Any]:
    job_text = f"{job.get('title', '')}\n{job.get('description', '')}"
    detected = detect_skills(job_text, vocab)

    skills = sorted_items(master.get("technical_skills", []), job_text, detected)

    experiences: list[dict[str, Any]] = []
    for exp_index, experience in enumerate(master.get("experience", [])):
        annotated_bullets = [
            {
                **bullet,
                "_source_id": f"experience.{exp_index}.bullet.{bullet_index}",
            }
            for bullet_index, bullet in enumerate(experience.get("bullets", []))
        ]
        bullets = sorted_items(annotated_bullets, job_text, detected)
        max_bullets = int(experience.get("max_bullets", 4))
        experiences.append(
            {
                **experience,
                "bullets": bullets[:max_bullets],
            }
        )

    certifications = sorted_certifications(master.get("certifications", []), job_text, vocab)

    return {
        "identity": master["identity"],
        "summary": tailored_summary(master, job_text, detected),
        "technical_skills": skills,
        "experience": experiences,
        "education": master.get("education", []),
        "certifications": certifications,
        "matched_skills": scored.get("matched_skills", []),
        "missing_core_skills": scored.get("missing_skills", []),
        "optional_missing_skills": scored.get("optional_missing_skills", []),
    }
