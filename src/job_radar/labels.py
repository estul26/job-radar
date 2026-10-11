"""Application statuses and the GitHub Issue labels that carry them, defined once."""

from __future__ import annotations

STATUSES = ("New", "Saved", "Applied", "Interview", "Rejected", "Offer", "Skipped")
_STATUS_BY_KEY = {status.lower(): status for status in STATUSES}

# Name -> (colour, description) for every label the workflows apply.
LABELS: dict[str, tuple[str, str]] = {
    "source:linkedin": ("0A66C2", "LinkedIn-sourced job"),
    "source:indeed": ("2164F3", "Indeed-sourced job"),
    "match:good": ("2EA44F", "At or above good-match threshold"),
    "match:possible": ("D4C5F9", "Possible / stretch match"),
    "match:low": ("CFD3D7", "Below tracking threshold"),
    "match:rejected": ("B60205", "Hard-rejected by configured rules"),
    "status:new": ("5319E7", "New tracked application"),
    "status:saved": ("0E8A16", "Saved for later"),
    "status:applied": ("1D76DB", "Application submitted"),
    "status:interview": ("FBCA04", "Interview stage"),
    "status:rejected": ("D73A4A", "Application rejected"),
    "status:offer": ("0E8A16", "Offer received"),
    "status:skipped": ("CFD3D7", "Not pursuing"),
    "resume:tailor": ("7057FF", "Generate or regenerate a tailored resume"),
    "resume:ready": ("008672", "Tailored resume is stored in the repository"),
    "needs:description": ("FEF2C0", "Paste the full job description into the Issue to score it"),
}


def normalize_status(value: str) -> str:
    """Canonical status name ("applied" -> "Applied"); raises ValueError for anything else."""
    status = _STATUS_BY_KEY.get(str(value or "").strip().lower())
    if not status:
        raise ValueError(f"Unsupported status: {value}")
    return status


def status_label(status: str) -> str:
    return f"status:{normalize_status(status).lower()}"
