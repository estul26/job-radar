"""Generate and file a tailored résumé for one scored job (from LinkedIn or a job board)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..ids import job_key
from ..matcher import Vocabulary
from .ai import enhance_resume_with_ai
from .render import docx_resume, markdown_resume, tailoring_notes
from .tailor import slug, tailor_content

INDEX_FIELDS = [
    "job_key",
    "issue_number",
    "company",
    "role",
    "score",
    "generated_at",
    "master_version",
    "job_url",
    "resume_markdown",
    "resume_docx",
    "status",
    "ai_used",
    "ai_model",
]


def write_index(index_path: Path, rows: list[dict[str, str]]) -> None:
    """resumes/index.csv: one row per résumé folder, newest first."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row.get("generated_at", ""), reverse=True))


def generate_resume(
    scored: dict[str, Any],
    master: dict[str, Any],
    *,
    vocab: Vocabulary,
    issue_number: str = "",
    issue_url: str = "",
    resume_dir: Path = Path("resumes/jobs"),
) -> dict[str, Any]:
    """Write resume.md/.docx, notes, AI audit and metadata for a scored job; return its record.

    The folder is keyed by the LinkedIn job ID for LinkedIn jobs and by the
    fingerprint otherwise, so regenerating a job overwrites its own folder. Only
    that folder is written; resumes/index.csv is rebuilt from the folders by
    `radar export`.
    """
    baseline = tailor_content(master, scored, scored, vocab=vocab)
    content, ai_audit = enhance_resume_with_ai(master, scored, baseline, vocab=vocab)

    title = str(scored.get("title", ""))
    company = str(scored.get("company", ""))
    job_url = str(scored.get("job_url", ""))
    key = job_key(job_url, str(scored.get("fingerprint", ""))) or slug(title)
    folder = resume_dir / f"{key}-{slug(company, 28)}-{slug(title, 42)}"
    folder.mkdir(parents=True, exist_ok=True)

    md_path = folder / "resume.md"
    docx_path = folder / "resume.docx"
    notes_path = folder / "tailoring_notes.md"
    metadata_path = folder / "metadata.json"
    ai_audit_path = folder / "ai_audit.json"
    master_version = str(master.get("version", ""))

    md_path.write_text(markdown_resume(content), encoding="utf-8")
    docx_resume(content, docx_path)
    notes_path.write_text(tailoring_notes(scored, scored, master_version, ai_audit), encoding="utf-8")
    ai_audit_path.write_text(json.dumps(ai_audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ai = {
        "used": bool(ai_audit.get("used")),
        "model": str(ai_audit.get("model", "")),
        "status": str(ai_audit.get("status", "")),
        "rewrite_response_id": str(ai_audit.get("rewrite_response_id", "")),
        "validator_response_id": str(ai_audit.get("validator_response_id", "")),
    }
    generated_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "job_key": key,
        "fingerprint": scored.get("fingerprint", ""),
        "issue_number": str(issue_number or ""),
        "issue_url": str(issue_url or ""),
        "job_url": job_url,
        "source": scored.get("source", ""),
        "company": company,
        "role": title,
        "location": scored.get("location", ""),
        "date_posted": scored.get("date_posted", ""),
        "score": int(scored.get("score", 0)),
        "master_version": master_version,
        "generated_at": generated_at,
        "matched_skills": scored.get("matched_skills", []),
        "missing_core_skills": scored.get("missing_skills", []),
        "optional_missing_skills": scored.get("optional_missing_skills", []),
        "ai": ai,
        "resume_markdown": md_path.as_posix(),
        "resume_docx": docx_path.as_posix(),
        "tailoring_notes": notes_path.as_posix(),
        "ai_audit": ai_audit_path.as_posix(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        **metadata,
        "title": title,
        "is_remote": bool(scored.get("is_remote", False)),
        "description": scored.get("description", ""),
        "folder": folder.as_posix(),
        "metadata": metadata_path.as_posix(),
        "ai_used": ai["used"],
        "ai_model": ai["model"],
        "ai_status": ai["status"],
    }
