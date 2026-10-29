from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .normalize import phrase_found, title_matches_exclusion

# Skill points: 35 when the posting names enough of your field's skills to judge by, and the
# neutral 18 when it names none. Fewer than SKILL_EVIDENCE core skills count only partly, so
# "matched 1/1" isn't worth as much as "matched 4/4".
SKILL_POINTS = 35
NEUTRAL_SKILL_POINTS = 18
SKILL_EVIDENCE = 3

# Job postings are read in English: these headings start the nice-to-have part of a posting.
OPTIONAL_SECTION_PATTERNS = [
    r"\bnice\s+to\s+have\b",
    r"\bnice-to-have\b",
    r"\bpreferred\s+qualifications?\b",
    r"\bpreferred\s+skills?\b",
    r"\bbonus\s+qualifications?\b",
    r"\bdesired\s+qualifications?\b",
]


def _phrases(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    return tuple(str(item) for item in (value or []) if str(item).strip())


@dataclass(frozen=True)
class Vocabulary:
    """The field-specific words scoring looks for, from the `matching` section of search_config.yaml.

    Every phrase matches on word boundaries, ignoring case; a phrase starting with "re:" is a regex.
    """

    # Skill or certification name -> phrases that mean a posting asks for it.
    skills: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Skills found in almost every posting: reported, but never core requirements.
    soft_skills: frozenset[str] = frozenset()
    certifications: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Words that make a title related to the target roles when it isn't one of them.
    related_title_keywords: tuple[str, ...] = ()
    # Words that count as related only when the title also has one of the context_words
    # (with "care" needing "patient", "Customer Care Agent" isn't a nursing job).
    context_title_keywords: tuple[str, ...] = ()
    context_words: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> Vocabulary:
        matching = config.get("matching") or {}

        def named(section: Any) -> dict[str, tuple[str, ...]]:
            # A name with no phrases is looked for as itself.
            return {str(name): _phrases(phrases) or (str(name),) for name, phrases in (section or {}).items()}

        return cls(
            skills=named(matching.get("skills")),
            soft_skills=frozenset(s.lower() for s in _phrases(matching.get("soft_skills"))),
            certifications=named(matching.get("certifications")),
            related_title_keywords=_phrases(matching.get("related_title_keywords")),
            context_title_keywords=_phrases(matching.get("context_title_keywords")),
            context_words=_phrases(matching.get("context_words")),
        )

    def title_hits(self, title: str) -> int:
        hits = sum(1 for keyword in self.related_title_keywords if phrase_found(title, [keyword]))
        if phrase_found(title, self.context_words):
            hits += sum(1 for keyword in self.context_title_keywords if phrase_found(title, [keyword]))
        return hits


def _text(job: dict[str, Any]) -> str:
    return f"{job.get('title', '')}\n{job.get('description', '')}".lower()


def split_required_optional_text(job: dict[str, Any]) -> tuple[str, str]:
    """Split optional sections so nice-to-have gaps do not lower core fit."""
    title = str(job.get("title", ""))
    description = str(job.get("description", ""))
    positions: list[int] = []
    for pattern in OPTIONAL_SECTION_PATTERNS:
        match = re.search(pattern, description, flags=re.IGNORECASE)
        if match:
            positions.append(match.start())

    if not positions:
        return f"{title}\n{description}".lower(), ""

    split_at = min(positions)
    return (
        f"{title}\n{description[:split_at]}".lower(),
        description[split_at:].lower(),
    )


def detect_skills(text: str, vocab: Vocabulary) -> set[str]:
    return {skill for skill, phrases in vocab.skills.items() if phrase_found(text, phrases)}


def detect_certs(text: str, vocab: Vocabulary) -> set[str]:
    return {cert for cert, phrases in vocab.certifications.items() if phrase_found(text, phrases)}


# "3 years", "3+ years", "3-5 years", "2 to 4 yrs", "1.5 years"; group 1 is the (lower) number.
_YEARS = re.compile(
    r"(?<![\w.,])(\d{1,2}(?:\.\d)?)\s*(?:(?:-|–|—|to)\s*\d{1,2}(?:\.\d)?\s*)?\+?\s*(?:years?|yrs?)\b", re.I
)
# More years than a posting you could apply for plausibly asks for: "over 40 years" is the company's age,
# and "18 years" or "21 years" is usually an age limit.
MAX_REQUIRED_YEARS = 15
# The words right around a number of years that make it something other than an experience requirement.
_AGE_BEFORE = re.compile(r"\b(?:aged?|age of|be(?: at least| over)?)\s*$", re.I)
_AGE_AFTER = re.compile(r"^\W*(?:old|of age|or older|or over|and over|and above)\b", re.I)
_COMPANY_BEFORE = re.compile(
    r"\b(?:we have|we've|we bring|our \w+ (?:has|have)|with a (?:history|heritage) of)\s+(?:over\s+|more than\s+)?$",
    re.I,
)
_OTHER_BEFORE = re.compile(
    r"\b(?:for|since|(?:over|in|during) the (?:last|past)|the (?:last|past)|last|past|established|founded|"
    r"celebrating|within|every|after|under|up to)\s+(?:(?:over|more than|almost|nearly|around|about|some)\s+)?$",
    re.I,
)
_OTHER_AFTER = re.compile(
    r"^\W*(?:of (?:trading|history|heritage|service|operation|growth)|in business|anniversary|ago|"
    r"fixed[- ]term|contract|ftc|maternity|secondment|warranty|guarantee)\b",
    re.I,
)
_EXPERIENCE_AFTER = re.compile(
    r"^[^.;\n]{0,40}?\b(?:experience|experienced|exp|pqe|post[- ]?qualifi\w*|"
    r"in (?:a|an|the) (?:similar|related|relevant))\b",
    re.I,
)


def _requirement_years(text: str, match: re.Match[str]) -> int | None:
    """The years an experience requirement asks for, or None when the number means something else."""
    years = math.ceil(float(match.group(1)))
    before = re.split(r"[.;:!?\n]", text[max(0, match.start() - 40) : match.start()])[-1]
    after = re.split(r"[.;!?\n]", text[match.end() : match.end() + 60])[0]
    if years > MAX_REQUIRED_YEARS or _AGE_BEFORE.search(before) or _AGE_AFTER.match(after):
        return None
    if _COMPANY_BEFORE.search(before):
        return None
    if _EXPERIENCE_AFTER.match(after):
        return years
    if _OTHER_BEFORE.search(before) or _OTHER_AFTER.match(after):
        return None
    return years


def extract_min_years(text: str) -> int | None:
    """The fewest years of experience the text asks for: "3+ years", "3-5 years", "2 to 4 yrs".

    Ages ("18 years or older"), the company's own history ("for 25 years", "over 40 years of
    experience"), contract lengths ("2 years fixed term") and other durations are left out.
    """
    found = [years for match in _YEARS.finditer(text) if (years := _requirement_years(text, match)) is not None]
    return min(found) if found else None


def title_score(title: str, target_titles: list[str], vocab: Vocabulary | None = None) -> tuple[int, str]:
    # Whole words, like every other phrase: "Nurse" doesn't match "Nursery Teacher".
    if phrase_found(title, target_titles):
        return 30, "target-role title"
    hits = vocab.title_hits(title) if vocab else 0
    if hits >= 2:
        return 24, "closely related title"
    if hits == 1:
        return 15, "partially related title"
    return 0, "title is outside target role family"


def experience_score(text: str, profile_years: int, hard_reject_min_years: int) -> tuple[int, str, bool]:
    years = extract_min_years(text)
    if years is None:
        return 10, "experience requirement not clearly stated", False
    if years >= hard_reject_min_years:
        return 0, f"requires at least {years} years", True
    if years <= profile_years:
        return 15, f"requires {years} year(s), within profile", False
    if years == profile_years + 1:
        return 10, f"asks for {years} years; slightly above profile", False
    if years == profile_years + 2:
        return 5, f"asks for {years} years; stretch", False
    return 0, f"asks for {years} years", False


def freshness_score(date_posted: str, fresh_hours: int) -> tuple[int, str]:
    if not date_posted:
        return 2, "posting date unavailable"
    try:
        dt = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600)
        if age_h <= fresh_hours:
            return 5, f"fresh: about {age_h:.0f}h old"
        if age_h <= 48:
            return 3, f"about {age_h:.0f}h old"
        if age_h <= 72:
            return 1, f"about {age_h:.0f}h old"
        return 0, f"older posting: about {age_h:.0f}h"
    except ValueError:
        return 2, "posting date could not be parsed"


def location_score(job: dict[str, Any], locations: list[dict[str, Any]], remote_score: int = 5) -> tuple[int, str]:
    """Points for the best-scoring `search.locations` entry whose `match` phrases are in the job's location.

    A `remote_only` entry is a search for remote jobs, so it never scores a job that isn't remote:
    with `match: [uk]`, it would otherwise reward every on-site job in the country.
    """
    if job.get("is_remote"):
        return remote_score, "remote role"
    loc = str(job.get("location", ""))
    best: tuple[int, str] | None = None
    for place in locations:
        if place.get("remote_only"):
            continue
        name = str(place.get("name", "")).strip()
        phrases = _phrases(place.get("match")) or _phrases(name)
        if phrases and phrase_found(loc, phrases):
            points = int(place.get("score", 5))
            if best is None or points > best[0]:
                best = (points, f"{name} location")
    return best or (1, "location needs review")


def score_job(job: dict[str, Any], profile: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    ranking = config["ranking"]
    vocab = Vocabulary.from_config(config)
    title = job.get("title", "")
    text = _text(job)

    # search.exclude_title_terms also drops jobs at collection; rejecting them here covers jobs from
    # LinkedIn and fixtures too.
    reject_terms = [
        *(ranking.get("hard_reject_title_terms") or []),
        *(config["search"].get("exclude_title_terms") or []),
    ]
    hard_reject_reasons = list(dict.fromkeys(term for term in reject_terms if title_matches_exclusion(title, [term])))

    role_pts, role_reason = title_score(title, config["search"].get("titles") or [], vocab)
    if role_pts == 0 and ranking.get("hard_reject_unrelated_titles", False):
        hard_reject_reasons.append("unrelated title")

    exp_pts, exp_reason, exp_reject = experience_score(
        text,
        int(profile.get("experience_years", 0)),
        int(ranking.get("hard_reject_min_years", 5)),
    )
    if exp_reject:
        hard_reject_reasons.append(exp_reason)

    required_text, optional_text = split_required_optional_text(job)
    required_skills = detect_skills(required_text, vocab)
    optional_skills = detect_skills(optional_text, vocab) - required_skills
    profile_skills = {s.lower() for s in profile.get("skills", [])}

    matched_required_skills = sorted(skill for skill in required_skills if skill.lower() in profile_skills)
    missing = {skill for skill in required_skills if skill.lower() not in profile_skills}
    # A soft skill isn't a core requirement, so a missing one is reported with the optional gaps.
    soft_missing = {skill for skill in missing if skill.lower() in vocab.soft_skills}
    missing_skills = sorted(missing - soft_missing)
    matched_optional_skills = sorted(skill for skill in optional_skills if skill.lower() in profile_skills)
    optional_missing_skills = sorted(
        {skill for skill in optional_skills if skill.lower() not in profile_skills} | soft_missing
    )
    matched_skills = sorted(set(matched_required_skills) | set(matched_optional_skills))

    core_required = {s for s in required_skills if s.lower() not in vocab.soft_skills}
    if core_required:
        # Nice-to-have skills are reported separately and do not reduce
        # the core fit score.
        matched_core = [s for s in matched_required_skills if s.lower() not in vocab.soft_skills]
        share = len(matched_core) / len(core_required)
        evidence = min(1.0, len(core_required) / SKILL_EVIDENCE)
        skill_pts = round(NEUTRAL_SKILL_POINTS + (SKILL_POINTS * share - NEUTRAL_SKILL_POINTS) * evidence)
        skill_reason = f"matched {len(matched_core)}/{len(core_required)} core detected skills"
        if evidence < 1:
            skill_reason += " (few named, so partly counted)"
    elif any(s.lower() not in vocab.soft_skills for s in optional_skills):
        skill_pts = NEUTRAL_SKILL_POINTS
        skill_reason = "only optional skill requirements detected"
    else:
        skill_pts = NEUTRAL_SKILL_POINTS
        skill_reason = "few explicit skill requirements detected"

    detected_certs = detect_certs(text, vocab)
    profile_certs = {c.lower() for c in profile.get("certifications", [])}
    matched_certs = sorted(c for c in detected_certs if c.lower() in profile_certs)
    missing_certs = sorted(c for c in detected_certs if c.lower() not in profile_certs)
    if detected_certs:
        cert_pts = round(10 * len(matched_certs) / len(detected_certs))
        cert_reason = f"matched {len(matched_certs)}/{len(detected_certs)} mentioned certifications"
    else:
        cert_pts = 5
        cert_reason = "no specific certification requirement detected"

    fresh_pts, fresh_reason = freshness_score(job.get("date_posted", ""), int(ranking.get("fresh_hours", 24)))
    loc_pts, loc_reason = location_score(
        job, config["search"].get("locations") or [], int(ranking.get("remote_score", 5))
    )

    score = max(0, min(100, role_pts + exp_pts + skill_pts + cert_pts + fresh_pts + loc_pts))
    hard_reject = bool(hard_reject_reasons)

    reasons = [role_reason, exp_reason, skill_reason, cert_reason, fresh_reason, loc_reason]
    # The neutral points alone put a target title in your city over the good-match line, so a good
    # match also needs one of your skills to show up in the posting (when your field's skills are set).
    good_capped = bool(
        ranking.get("good_requires_matched_skill", True)
        and vocab.skills
        and not any(skill.lower() not in vocab.soft_skills for skill in matched_skills)
    )
    if good_capped:
        reasons.append("none of your skills found in the posting, so at most a possible match")
    return {
        **job,
        "score": score,
        "hard_reject": hard_reject,
        "hard_reject_reasons": hard_reject_reasons,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "matched_optional_skills": matched_optional_skills,
        "optional_missing_skills": optional_missing_skills,
        "matched_certs": matched_certs,
        "missing_certs": missing_certs,
        "score_reasons": reasons,
        "good_capped": good_capped,
    }
