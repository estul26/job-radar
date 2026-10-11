"""Job identity: content fingerprints and LinkedIn job IDs, defined once."""

from __future__ import annotations

import hashlib
import re

# /jobs/view/<id>, /jobs/view/<slug>-<id>, /comm/jobs/view/<id>, and search or
# collection pages that select a job with ?currentJobId=<id>.
_LINKEDIN_JOB_ID_PATTERNS = [
    re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*-)?(\d+)", re.IGNORECASE),
    re.compile(r"[?&]currentJobId=(\d+)", re.IGNORECASE),
]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def make_fingerprint(title: str, company: str, location: str, job_url: str = "") -> str:
    """Stable ID for deduplicating one posting across searches and job boards."""
    # Stable enough across job-board URL tracking changes, while still distinguishing locations.
    core = "|".join([_slug(title), _slug(company), _slug(location)])
    if not title or not company:
        core += "|" + _slug(job_url)
    return hashlib.sha256(core.encode("utf-8")).hexdigest()[:20]


def linkedin_job_id(url: str) -> str:
    """The numeric LinkedIn job ID in a LinkedIn URL, or "" for any other URL."""
    value = (url or "").replace("&amp;", "&")
    for pattern in _LINKEDIN_JOB_ID_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return ""


def linkedin_job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def job_key(job_url: str, fingerprint: str) -> str:
    """Key of a tracked job's résumé folder: the LinkedIn job ID, else the fingerprint."""
    return linkedin_job_id(job_url) or fingerprint


def canonical_job_key(url: str) -> str:
    """Compare job URLs: LinkedIn URLs by job ID, other URLs case- and slash-insensitively."""
    job_id = linkedin_job_id(url)
    if job_id:
        return f"linkedin:{job_id}"
    return (url or "").strip().rstrip("/").lower()
