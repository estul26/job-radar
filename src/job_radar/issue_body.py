"""The GitHub Issue body: the contract between every intake channel and the scorer.

- LinkedIn Issues come from the "LinkedIn Job Review" Issue Form
  (.github/ISSUE_TEMPLATE/linkedin-job.yml) or from the email-alert importer,
  which writes the same headings with a placeholder description.
- Job-board Issues ("[Indeed Job]", "[Glassdoor Job]", …) are written by the daily
  scan, with a hidden fingerprint marker so the Issue can be found again when the
  job is re-synced.
"""

from __future__ import annotations

import re
from typing import Any

from .ids import make_fingerprint
from .labels import board_name, board_site
from .models import Job
from .normalize import split_company_location

PLACEHOLDER_DESCRIPTION = "_Paste full job description here, replacing this line, then save the issue._"
# An Issue still containing this is waiting for its description and is not scored.
PLACEHOLDER_MARKER = "_Paste full job description here"
# GitHub rejects Issue bodies over 65,536 characters.
MAX_DESCRIPTION_CHARS = 42000

_HEADING = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_FINGERPRINT_MARKER = re.compile(r"<!--\s*job-fingerprint:([a-f0-9]{8,64})\s*-->", re.IGNORECASE)

# The headings the Issue Form and the radar write, lower-cased. Job descriptions are Markdown and often
# have "###" headings of their own ("### About the role"), so only these headings start a field.
FIELD_HEADINGS = frozenset(
    {
        "linkedin job url",
        "job url",
        "job title",
        "company",
        "location",
        "source",
        "remote?",
        "date posted (optional)",
        "date posted",
        "job description",
    }
)
# The headings that can follow the description: the card a LinkedIn alert or search Issue was made from.
TRAILING_HEADINGS = frozenset({"linkedin alert source", "linkedin search source"})


def parse_sections(body: str) -> dict[str, str]:
    """Issue Form output as lower-cased heading -> value ("_No response_" becomes "").

    Only the radar's own headings count, each at its first appearance. The description runs to the
    end of the body, or to a trailing source heading, whatever headings it contains itself.
    """
    body = body or ""
    headings: list[tuple[str, re.Match[str]]] = []
    in_description = False
    for match in _HEADING.finditer(body):
        name = match.group(1).strip().lower()
        allowed = TRAILING_HEADINGS if in_description else FIELD_HEADINGS | TRAILING_HEADINGS
        if name not in allowed or any(name == seen for seen, _ in headings):
            continue
        headings.append((name, match))
        in_description = in_description or name == "job description"

    sections: dict[str, str] = {}
    for index, (name, match) in enumerate(headings):
        end = headings[index + 1][1].start() if index + 1 < len(headings) else len(body)
        value = body[match.end() : end].strip()
        sections[name] = "" if value == "_No response_" else value
    return sections


def _field(sections: dict[str, str], *names: str, required: bool = True) -> str:
    """First non-empty section among the heading names (they differ between sources)."""
    for name in names:
        value = sections.get(name.lower(), "").strip()
        if value:
            return value
    if required:
        raise ValueError(f"Missing required Issue field: {names[0]}")
    return ""


def fingerprint_marker(body: str) -> str:
    match = _FINGERPRINT_MARKER.search(body or "")
    return match.group(1).lower() if match else ""


def parse_job(body: str, *, require_description: bool = True) -> Job:
    """The job described by a LinkedIn or job-board Issue; raises ValueError when a field is missing.

    The tracker export passes require_description=False: a tracked job stays tracked without one.
    """
    sections = parse_sections(body)
    job_url = _field(sections, "LinkedIn job URL", "Job URL")
    title = _field(sections, "Job title")
    # Older alert Issues stored LinkedIn's "Company · Location" line as the company.
    company, location = split_company_location(_field(sections, "Company"), _field(sections, "Location"))
    remote_text = _field(sections, "Remote?", required=False).lower()
    is_remote = remote_text.startswith(("yes", "remote")) or (
        not re.match(r"no\b", remote_text) and "remote" in location.lower()
    )
    fingerprint = fingerprint_marker(body) or make_fingerprint(
        title, company, "remote" if is_remote else location, job_url
    )
    return {
        "source": board_site(_field(sections, "Source", required=False)) or "linkedin",
        "title": title,
        "company": company,
        "location": location,
        "is_remote": is_remote,
        "date_posted": _field(sections, "Date posted (optional)", "Date posted", required=False),
        "job_type": "",
        "min_amount": "",
        "max_amount": "",
        "currency": "",
        "job_url": job_url,
        "description": _field(sections, "Job description", required=require_description),
        "fingerprint": fingerprint,
    }


def job_url(body: str) -> str:
    """The job URL in a job Issue, falling back to the first link in other text."""
    body = body or ""
    for heading in ("Job URL", "LinkedIn job URL"):
        section = re.search(
            rf"^###\s+{re.escape(heading)}\s*$\s*\n+([^\n]+)",
            body,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        if section:
            return section.group(1).strip()

    markdown = re.search(r"\*\*Job:\*\*\s+(https?://\S+)", body)
    if markdown:
        return markdown.group(1).rstrip(")., ")

    plain = re.search(r"https?://(?:www\.)?linkedin\.com/jobs/\S+", body, flags=re.IGNORECASE)
    if plain:
        return plain.group(0).rstrip(")., ")

    generic = re.search(r"https?://[^\s)]+", body, flags=re.IGNORECASE)
    if generic:
        return generic.group(0).rstrip(")., ")

    return ""


def render_linkedin_alert(candidate: dict[str, str], subject: str) -> str:
    """Body of an Issue created from a LinkedIn alert email, awaiting its description."""
    return _render_linkedin_card(candidate, "LinkedIn alert source", f"Email subject: {subject}\n\nAlert-card excerpt:")


def render_linkedin_search(candidate: dict[str, str]) -> str:
    """Body of an Issue created from a LinkedIn search result card, awaiting its description."""
    return _render_linkedin_card(
        candidate, "LinkedIn search source", "Found by radar linkedin-search.\n\nJob-card excerpt:"
    )


def _render_linkedin_card(candidate: dict[str, str], source_heading: str, source_intro: str) -> str:
    """A LinkedIn job known only from its card: the Issue Form headings with a placeholder description."""
    remote = "Yes" if "remote" in candidate["location"].lower() else "Not sure"
    return f"""### LinkedIn job URL

{candidate["job_url"]}

### Job title

{candidate["title"]}

### Company

{candidate["company"]}

### Location

{candidate["location"]}

### Remote?

{remote}

### Date posted (optional)

{candidate.get("date_posted", "")}

### Job description

{PLACEHOLDER_DESCRIPTION}

### {source_heading}

{source_intro}

{candidate.get("card_excerpt", "")}
"""


def render_board_job(job: dict[str, Any]) -> str:
    """Body of the Issue the daily scan creates for a job-board match."""

    def text(key: str) -> str:
        return str(job.get(key) or "").strip()

    description = text("description")
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS].rstrip() + "\n\n[Description truncated in GitHub Issue.]"

    return "\n".join(
        [
            f"<!-- job-fingerprint:{job.get('fingerprint', '')} -->",
            "",
            "### Job URL",
            "",
            text("job_url"),
            "",
            "### Job title",
            "",
            text("title"),
            "",
            "### Company",
            "",
            text("company"),
            "",
            "### Location",
            "",
            text("location"),
            "",
            "### Source",
            "",
            board_name(text("source")),
            "",
            "### Remote?",
            "",
            "Yes" if job.get("is_remote") else "No",
            "",
            "### Date posted",
            "",
            text("date_posted"),
            "",
            "### Job description",
            "",
            description,
            "",
        ]
    )
