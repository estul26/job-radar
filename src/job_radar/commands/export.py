"""Rebuild data/applications.csv and resumes/index.csv from the job Issues (workflow: daily-jobs.yml).

The Issues are the source of truth for every tracked job: the status:* label is
its status. Both files are regenerated on each scan, so edit the Issue (or drag
its card), not the CSV.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..github import GitHub, label_names
from ..ids import job_key
from ..issue_body import parse_job
from ..labels import is_job_title, normalize_status
from ..resume.pipeline import write_index
from ..settings import Settings

EXPORT_FIELDS = "number,title,body,labels,state,url,createdAt,closedAt,comments"
APPLICATION_FIELDS = [
    "issue_number",
    "status",
    "match",
    "score",
    "title",
    "company",
    "location",
    "source",
    "date_posted",
    "job_url",
    "job_key",
    "fingerprint",
    "opened",
    "closed",
    "issue_url",
]
_SCORE_HEADING = re.compile(r"^##\s+(\d+)%\s+—", re.MULTILINE)


def latest_score(comments: Iterable[dict[str, Any]]) -> str:
    """The score in the newest match comment ("## 81% — Title")."""
    scores = _SCORE_HEADING.findall("\n".join(str(comment.get("body", "")) for comment in comments))
    return scores[-1] if scores else ""


def _label_value(labels: set[str], prefix: str) -> str:
    return next((name.split(":", 1)[1] for name in sorted(labels) if name.startswith(prefix)), "")


def application_rows(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per scored job Issue; alerts still waiting for a description are left out."""
    rows = []
    for issue in issues:
        labels = label_names(issue)
        status = _label_value(labels, "status:")
        if not is_job_title(str(issue.get("title", ""))) or not status:
            continue
        try:
            job = parse_job(str(issue.get("body", "")))
        except ValueError:
            continue
        rows.append(
            {
                "issue_number": int(issue["number"]),
                "status": normalize_status(status),
                "match": _label_value(labels, "match:"),
                "score": latest_score(issue.get("comments") or []),
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
                "source": job["source"],
                "date_posted": job["date_posted"],
                "job_url": job["job_url"],
                "job_key": job_key(job["job_url"], job["fingerprint"]),
                "fingerprint": job["fingerprint"],
                "opened": str(issue.get("createdAt") or "")[:10],
                "closed": str(issue.get("closedAt") or "")[:10],
                "issue_url": issue.get("url", ""),
            }
        )
    return sorted(rows, key=lambda row: row["issue_number"])


def resume_rows(resume_dir: Path, applications: list[dict[str, Any]]) -> list[dict[str, str]]:
    """One row per résumé folder, with the status of its job's Issue."""
    by_issue = {str(row["issue_number"]): row for row in applications}
    by_key = {row["job_key"]: row for row in applications}
    rows = []
    for metadata_path in sorted(resume_dir.glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        application = by_issue.get(str(metadata.get("issue_number") or "")) or by_key.get(metadata.get("job_key", ""))
        ai = metadata.get("ai") or {}
        rows.append(
            {
                "job_key": str(metadata.get("job_key", "")),
                "issue_number": str(metadata.get("issue_number") or (application or {}).get("issue_number", "")),
                "company": str(metadata.get("company", "")),
                "role": str(metadata.get("role", "")),
                "score": str(metadata.get("score", "")),
                "generated_at": str(metadata.get("generated_at", "")),
                "master_version": str(metadata.get("master_version", "")),
                "job_url": str(metadata.get("job_url", "")),
                "resume_markdown": str(metadata.get("resume_markdown", "")),
                "resume_docx": str(metadata.get("resume_docx", "")),
                "status": (application or {}).get("status", ""),
                "ai_used": "Yes" if ai.get("used") else "No",
                "ai_model": str(ai.get("model", "")),
            }
        )
    return rows


def export(gh: GitHub, settings: Settings) -> tuple[int, int]:
    """Write both exports; returns (applications, résumés)."""
    paths = settings.paths
    applications = application_rows(gh.issues(fields=EXPORT_FIELDS))
    paths.applications.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: Excel only reads non-English text correctly from a CSV that starts with a BOM.
    with paths.applications.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=APPLICATION_FIELDS)
        writer.writeheader()
        writer.writerows(applications)

    resumes = resume_rows(paths.resume_dir, applications)
    write_index(paths.resume_index, resumes)
    return len(applications), len(resumes)
