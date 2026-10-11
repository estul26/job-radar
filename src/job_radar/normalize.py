from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import pandas as pd

from .ids import make_fingerprint


def phrase_pattern(phrase: str) -> str:
    """The regex for one config phrase: "re:" then a raw regex, or else words matched on word boundaries."""
    phrase = str(phrase or "").strip()
    if phrase.startswith("re:"):
        return phrase[3:].strip()
    words = [re.escape(part) for part in phrase.lower().split() if part]
    if not words:
        return ""
    return r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)"


def phrase_found(text: str, phrases: list[str] | tuple[str, ...]) -> bool:
    """True when the text contains any of the config phrases (case-insensitive)."""
    text = str(text or "")
    for phrase in phrases:
        pattern = phrase_pattern(phrase)
        if pattern and re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def title_matches_exclusion(title: str, terms: list[str]) -> bool:
    """Return True when a title contains an excluded word/phrase on word boundaries."""
    return phrase_found(title, terms)


def split_company_location(company: str, location: str = "") -> tuple[str, str]:
    """Split LinkedIn's one-line "Company · Location" card text when no location is known."""
    company = str(company or "").strip()
    location = str(location or "").strip()
    if " · " in company and (not location or location.lower().startswith("unknown")):
        name, _, place = company.partition(" · ")
        if name.strip() and place.strip():
            return name.strip(), place.strip()
    return company, location


FIELDS = [
    "fingerprint",
    "source",
    "title",
    "company",
    "location",
    "is_remote",
    "date_posted",
    "job_type",
    "min_amount",
    "max_amount",
    "currency",
    "job_url",
    "description",
]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _format_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return _clean(value)
        return parsed.isoformat()
    except Exception:
        return _clean(value)


def normalize_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []

    records: list[dict[str, Any]] = []
    for raw in df.to_dict(orient="records"):
        title = _clean(raw.get("title"))
        company = _clean(raw.get("company"))
        location = _clean(raw.get("location"))
        job_url = _clean(raw.get("job_url_direct")) or _clean(raw.get("job_url"))
        record = {
            "source": _clean(raw.get("site")) or _clean(raw.get("source")),
            "title": title,
            "company": company,
            "location": location,
            "is_remote": bool(raw.get("is_remote", False)),
            "date_posted": _format_date(raw.get("date_posted")),
            "job_type": _clean(raw.get("job_type")),
            "min_amount": _clean(raw.get("min_amount")),
            "max_amount": _clean(raw.get("max_amount")),
            "currency": _clean(raw.get("currency")),
            "job_url": job_url,
            "description": _clean(raw.get("description")),
        }
        fingerprint_location = "remote" if record["is_remote"] else location
        record["fingerprint"] = make_fingerprint(title, company, fingerprint_location, job_url)
        records.append(record)

    # Deduplicate inside the current run, preferring the record with more description text.
    best: dict[str, dict[str, Any]] = {}
    for rec in records:
        fp = rec["fingerprint"]
        if fp not in best or len(rec["description"]) > len(best[fp]["description"]):
            best[fp] = rec
    return list(best.values())
