"""The twice-daily job scan (workflow: daily-jobs.yml).

- scan_jobs(): collect and score new jobs, update the seen state, write the report
- generate_scan_resumes(): résumés for the good matches
- publish_scan(): after the commit, a job Issue for every good and possible match
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from ..github import GitHub
from ..issue_body import fingerprint_marker, parse_job, render_board_job
from ..labels import STATUSES, board_name, is_job_title, status_label
from ..matcher import score_job
from ..models import Verdict, classify
from ..normalize import normalize_dataframe
from ..report import build_report, write_report
from ..resume.pipeline import generate_resume
from ..settings import Settings, load_json
from ..state import load_seen, prune_seen, save_seen, update_seen
from .doctor import resume_ready

MATCH_MARKER = "<!-- job-radar:board-match -->"
MATCH_LABELS = ["match:good", "match:possible", "status:new", "resume:ready"]
# Labels you add to a job Issue by hand. GitHub's label picker only offers labels that already exist,
# so they're created along with the first Issues.
HAND_LABELS = [*(status_label(status) for status in STATUSES), "resume:tailor"]


def load_fixture(path: str | Path) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return normalize_dataframe(pd.DataFrame(raw))


def _read_list(path: Path) -> list[dict[str, Any]]:
    items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if not isinstance(items, list):
        raise ValueError(f"{path} must hold a JSON list.")
    return items


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def issue_fingerprints(issues: Iterable[dict[str, Any]]) -> frozenset[str]:
    """Fingerprints of the jobs that already have an Issue, from any source."""
    fingerprints = set()
    for issue in issues:
        body = str(issue.get("body", ""))
        if not is_job_title(str(issue.get("title", ""))):
            continue
        try:
            fingerprints.add(fingerprint_marker(body) or parse_job(body)["fingerprint"])
        except ValueError:
            continue
    return frozenset(fingerprints)


def scan_jobs(
    settings: Settings,
    fixture: str | Path | None = None,
    known_fingerprints: frozenset[str] = frozenset(),
) -> str:
    """Collect and score new jobs; known_fingerprints are jobs that already have an Issue."""
    paths = settings.paths
    if fixture:
        jobs = load_fixture(fixture)
        errors: list[str] = []
    else:
        from ..collector import collect_jobs

        jobs, errors = collect_jobs(settings.config)

    seen = load_seen(paths.seen_jobs)
    unseen = [job for job in jobs if job["fingerprint"] not in seen and job["fingerprint"] not in known_fingerprints]

    scored = [score_job(job, settings.profile, settings.config) for job in unseen]
    scored.sort(key=lambda j: (j["hard_reject"], -j["score"]))

    by_verdict: dict[Verdict, list[dict]] = {verdict: [] for verdict in Verdict}
    for job in scored:
        by_verdict[classify(job, settings.good_threshold, settings.possible_threshold)].append(job)
    # A broad search can find dozens of good matches at once. The best max_good get an Issue and a
    # résumé now; the rest stay unseen, so the next scan offers them again.
    good = by_verdict[Verdict.GOOD]
    held: list[dict] = []
    if settings.max_good > 0:
        good, held = good[: settings.max_good], good[settings.max_good :]
    possible = by_verdict[Verdict.POSSIBLE][: settings.max_possible]

    # Persist a reviewable CSV for all new scored jobs, not only the shortlist.
    paths.latest_jobs.parent.mkdir(parents=True, exist_ok=True)
    # Keep full descriptions in the short-lived JSON handoff used for resume
    # generation, but avoid committing every scraped description to Git history.
    csv_rows = [{key: value for key, value in job.items() if key != "description"} for job in scored]
    pd.DataFrame(csv_rows).to_csv(paths.latest_jobs, index=False, encoding="utf-8-sig")

    # Everything else collected becomes "seen" so the next report is genuinely new.
    held_fingerprints = {job["fingerprint"] for job in held}
    collected = [job for job in jobs if job["fingerprint"] not in held_fingerprints]
    save_seen(paths.seen_jobs, prune_seen(update_seen(seen, collected)))

    report = build_report(
        good=good,
        possible=possible,
        held=held,
        rejected=by_verdict[Verdict.REJECTED],
        errors=errors,
        total_collected=len(jobs),
        unseen_count=len(unseen),
        good_threshold=settings.good_threshold,
        possible_threshold=settings.possible_threshold,
        tz=settings.timezone,
    )
    write_report(paths.report, report)

    matches = [
        {**job, "verdict": verdict.value}
        for verdict, group in ((Verdict.GOOD, good), (Verdict.POSSIBLE, possible))
        for job in group
        # LinkedIn jobs arrive through its alerts and radar linkedin-search, never as scan Issues.
        if str(job.get("source", "")).strip().lower() != "linkedin"
    ]
    _write_json(paths.scan_matches, matches)
    return report


def generate_scan_resumes(settings: Settings, master_path: str | Path | None = None) -> list[dict[str, Any]] | None:
    """Tailored résumés for the good matches scan_jobs() handed off; None while the master isn't filled in."""
    paths = settings.paths
    master = load_json(master_path or paths.master_resume)
    if not resume_ready(master):
        _write_json(paths.resume_manifest, [])
        return None
    results = [
        generate_resume(job, master, vocab=settings.vocab, resume_dir=paths.resume_dir)
        for job in _read_list(paths.scan_matches)
        if job.get("verdict") == Verdict.GOOD
    ]
    _write_json(paths.resume_manifest, results)
    return results


def match_comment(repo: str, job: dict[str, Any], resume: dict[str, Any] | None) -> str:
    def text(item: dict[str, Any], key: str) -> str:
        return str(item.get(key) or "").strip()

    lines = [
        MATCH_MARKER,
        f"## {int(job.get('score', 0))}% — {text(job, 'title')}",
        "",
        f"**Company:** {text(job, 'company')}",
        f"**Source:** {board_name(text(job, 'source'))}",
    ]
    if resume:
        lines += [
            f"**AI used:** {str(bool(resume.get('ai_used'))).lower()}",
            f"**AI model:** {text(resume, 'ai_model')}",
            f"**AI validation status:** {text(resume, 'ai_status')}",
            "",
            f"- [Resume source (Markdown)](https://github.com/{repo}/blob/main/{text(resume, 'resume_markdown')})",
            f"- [Application resume (DOCX)](https://github.com/{repo}/blob/main/{text(resume, 'resume_docx')})",
            "",
            "The resume was generated from the master-resume factual whitelist. "
            "AI wording is used only when both validation layers pass.",
        ]
    else:
        lines += ["", "No résumé was generated for this match. Add the `resume:tailor` label to generate one."]
    return "\n".join([*lines, ""])


def sync_board_issues(gh: GitHub, matches: list[dict[str, Any]], resumes: dict[str, dict[str, Any]]) -> list[int]:
    """Create (or update) one "[<board> Job]" Issue per match, found again by its fingerprint."""
    if not matches:
        return []
    sources = sorted({f"source:{str(job.get('source') or '').strip().lower()}" for job in matches})
    gh.ensure_labels([*sources, *MATCH_LABELS, *HAND_LABELS])
    existing: dict[str, int] = {}
    for issue in gh.issues():
        fingerprint = fingerprint_marker(str(issue.get("body", "")))
        if fingerprint:
            existing[fingerprint] = int(issue["number"])

    numbers = []
    for job in matches:
        fingerprint = str(job.get("fingerprint") or "").strip().lower()
        if not fingerprint:
            raise ValueError("A scan match is missing its fingerprint.")
        resume = resumes.get(fingerprint)
        good = job.get("verdict") == Verdict.GOOD
        board = board_name(str(job.get("source") or ""))
        title = f"[{board} Job] {str(job.get('title') or '').strip()} — {str(job.get('company') or '').strip()}"
        source = f"source:{str(job.get('source') or '').strip().lower()}"
        labels = [source, "match:good" if good else "match:possible", *(["resume:ready"] if resume else [])]
        number = existing.get(fingerprint)
        if number:
            gh.edit_issue(number, title=title, body=render_board_job(job), add_labels=labels)
        else:
            # Good matches are assigned to you, which is what notifies you.
            number = gh.create_issue(
                title, render_board_job(job), labels=[*labels, "status:new"], assignee=gh.owner if good else ""
            )
            existing[fingerprint] = number
        gh.upsert_comment(number, MATCH_MARKER, match_comment(gh.repo, job, resume))
        numbers.append(number)
    return numbers


def publish_scan(gh: GitHub, settings: Settings) -> list[int]:
    """After the scan's commit: a job Issue for each good and possible match."""
    resumes = {str(item.get("fingerprint", "")).lower(): item for item in _read_list(settings.paths.resume_manifest)}
    return sync_board_issues(gh, _read_list(settings.paths.scan_matches), resumes)
