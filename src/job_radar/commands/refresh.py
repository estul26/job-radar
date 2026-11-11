"""Regenerate out-of-date résumés after the master résumé changes (workflow: refresh-resumes.yml).

A tailored résumé is a snapshot of the master at the time it was made. When you fix a fact in the
master (a new email, a renamed certification), the résumés of jobs you haven't applied to yet would
still carry the old one. This regenerates them:

- prepare_refresh(): the résumé of every open job Issue at status:new or status:saved whose résumé
  was made from an older master version, written before the commit
- publish_refresh(): after the commit, mark each Issue resume:ready and update its résumé comment

Résumés of jobs you have applied to are kept, since they are what you sent (the `resume:tailor` label
still regenerates one by hand). Jobs that never had a résumé, such as possible matches, are left alone.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..github import GitHub, label_names
from ..ids import job_key
from ..issue_body import parse_job
from ..labels import is_job_title
from ..resume.pipeline import generate_resume
from ..settings import Settings, load_json
from .doctor import resume_ready, setup_problems
from .issue import RESUME_MARKER, SENT_STATUSES, _score, resume_comment

REFRESH_STATUSES = {"status:new", "status:saved"}


def resume_versions(resume_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """The master version of each résumé folder, by Issue number and by job key."""
    by_issue: dict[str, str] = {}
    by_key: dict[str, str] = {}
    for path in sorted(resume_dir.glob("*/metadata.json")):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        version = str(metadata.get("master_version") or "")
        if metadata.get("issue_number"):
            by_issue[str(metadata["issue_number"])] = version
        if metadata.get("job_key"):
            by_key[str(metadata["job_key"])] = version
    return by_issue, by_key


def stale_issues(issues: Iterable[dict[str, Any]], resume_dir: Path, version: str) -> list[dict[str, Any]]:
    """Open job Issues not yet applied to whose résumé was made from another master version."""
    by_issue, by_key = resume_versions(resume_dir)
    stale = []
    for issue in issues:
        labels = label_names(issue)
        if (
            str(issue.get("state", "OPEN")).upper() != "OPEN"
            or not is_job_title(str(issue.get("title", "")))
            or not labels & REFRESH_STATUSES
            or labels & SENT_STATUSES
        ):
            continue
        try:
            job = parse_job(str(issue.get("body", "")))
        except ValueError:
            continue  # Unreadable; the Issue itself already says why.
        made_with = by_issue.get(str(issue["number"])) or by_key.get(job_key(job["job_url"], job["fingerprint"]))
        if made_with is not None and made_with != version:
            stale.append(issue)
    return sorted(stale, key=lambda issue: int(issue["number"]))


def prepare_refresh(settings: Settings, issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Regenerate the stale résumés; returns (and saves for publish_refresh) one record per résumé."""
    manifest = settings.paths.refresh_manifest
    manifest.unlink(missing_ok=True)
    master = load_json(settings.paths.master_resume)
    if not resume_ready(master) or setup_problems(settings.config, settings.profile):
        return []
    version = str(master.get("version") or "")
    results = []
    for issue in stale_issues(issues, settings.paths.resume_dir, version):
        scored, _ = _score(settings, issue)
        result = generate_resume(
            scored,
            master,
            vocab=settings.vocab,
            issue_number=str(issue["number"]),
            issue_url=str(issue.get("url", "")),
            resume_dir=settings.paths.resume_dir,
        )
        results.append(result)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return results


def publish_refresh(gh: GitHub, settings: Settings) -> list[int]:
    """After the commit: link each regenerated résumé from its Issue."""
    manifest = settings.paths.refresh_manifest
    results = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    if results:
        gh.ensure_labels(["resume:ready"])
    numbers = []
    for result in results:
        number = int(result["issue_number"])
        gh.edit_issue(number, add_labels=["resume:ready"])
        gh.upsert_comment(number, RESUME_MARKER, resume_comment(gh.repo, result))
        numbers.append(number)
    return numbers
