"""Shapes of the job records that flow through the pipeline, and the match verdict."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict


class Job(TypedDict):
    """A posting after normalization (board scrape or GitHub Issue)."""

    fingerprint: str
    source: str
    title: str
    company: str
    location: str
    is_remote: bool
    date_posted: str
    job_type: str
    min_amount: str
    max_amount: str
    currency: str
    job_url: str
    description: str


class ScoredJob(Job):
    """A Job plus what matcher.score_job adds."""

    score: int
    hard_reject: bool
    hard_reject_reasons: list[str]
    matched_skills: list[str]
    missing_skills: list[str]
    matched_optional_skills: list[str]
    optional_missing_skills: list[str]
    matched_certs: list[str]
    missing_certs: list[str]
    score_reasons: list[str]


class Verdict(StrEnum):
    GOOD = "good"
    POSSIBLE = "possible"
    LOW = "low"
    REJECTED = "rejected"

    @property
    def tracked(self) -> bool:
        """Good and possible matches are tracked as applications."""
        return self in (Verdict.GOOD, Verdict.POSSIBLE)


def classify(scored: dict[str, Any], good_threshold: int, possible_threshold: int) -> Verdict:
    if scored.get("hard_reject"):
        return Verdict.REJECTED
    score = int(scored.get("score", 0))
    if score >= good_threshold:
        return Verdict.GOOD
    if score >= possible_threshold:
        return Verdict.POSSIBLE
    return Verdict.LOW
