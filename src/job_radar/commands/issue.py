"""What happens when a job Issue is opened, edited or labelled (workflow: issue-events.yml).

The Issue is the record of the application: its status:* label is the status,
and the board and data/applications.csv (exported by the scan) follow it.

Each event is handled in two stages around the workflow's commit:
- prepare: the résumé files to commit, when the event calls for a résumé
- publish: GitHub changes (comments, labels, open/closed), made once the commit
  has landed so résumé links resolve.
"""

from __future__ import annotations

import json
from typing import Any

from ..github import GitHub, label_names
from ..issue_body import PLACEHOLDER_MARKER, parse_job
from ..labels import LABELS
from ..matcher import score_job
from ..models import Verdict, classify
from ..resume.pipeline import generate_resume
from ..settings import Settings, load_json
from .doctor import resume_ready

LINKEDIN_PREFIXES = ("[LinkedIn Job]", "[LinkedIn Alert]")
JOB_PREFIXES = (*LINKEDIN_PREFIXES, "[Indeed Job]")
REVIEW_MARKER = "<!-- job-radar:match-review -->"
RESUME_MARKER = "<!-- job-radar:resume -->"
MATCH_LABELS = {f"match:{verdict.value}" for verdict in Verdict}
# The statuses scoring sets itself. Any other status was your choice and is kept.
SCORER_STATUSES = {"status:new", "status:skipped"}
CLOSING_STATUSES = {"status:rejected", "status:offer", "status:skipped"}
CLOSING_REASONS = {
    Verdict.REJECTED: "Scoring complete. This issue is closed by the configured hard-reject rules.",
    Verdict.LOW: "Scoring complete. This job is below the tracking threshold.",
}
RECOMMENDATIONS = {
    Verdict.REJECTED: "SKIP",
    Verdict.GOOD: "GOOD MATCH — APPLY",
    Verdict.POSSIBLE: "POSSIBLE MATCH — REVIEW / STRETCH APPLY",
    Verdict.LOW: "LOW MATCH — USUALLY SKIP",
}
COMMIT_MESSAGES = {
    "intake": "resume: tailor for LinkedIn job #{number}",
    "resume": "resume: tailor for issue #{number}",
    "status": "chore: update issue #{number}",
}


def route(issue: dict[str, Any], event: str, label: str = "") -> str | None:
    """Which handler an event needs: "intake", "resume", "status", or None to ignore it."""
    title = str(issue.get("title", ""))
    if event in ("opened", "edited"):
        if title.startswith(LINKEDIN_PREFIXES) and PLACEHOLDER_MARKER not in str(issue.get("body", "")):
            return "intake"
    elif event == "labeled":
        if label == "resume:tailor" and title.startswith(JOB_PREFIXES):
            return "resume"
        if label.startswith("status:") and label in LABELS:
            return "status"
    return None


def _score(settings: Settings, issue: dict[str, Any]) -> tuple[dict[str, Any], Verdict]:
    scored = score_job(parse_job(str(issue.get("body", ""))), settings.profile, settings.config)
    return scored, classify(scored, settings.good_threshold, settings.possible_threshold)


def build_review(scored: dict[str, Any], verdict: Verdict) -> str:
    def items(key: str, separator: str = ", ") -> str:
        return separator.join(scored.get(key, [])) or "—"

    return "\n".join(
        [
            "# LinkedIn Job Match Review",
            "",
            f"## {int(scored.get('score', 0))}% — {scored.get('title', 'Untitled')}",
            "",
            f"**Company:** {scored.get('company', '')}",
            f"**Location:** {scored.get('location', '')}",
            f"**Recommendation:** **{RECOMMENDATIONS[verdict]}**",
            f"**Tracked:** {'Yes — status:new' if verdict.tracked else 'No — status:skipped'}",
            "",
            f"**Job:** {scored.get('job_url', '')}",
            "",
            "### Match details",
            f"- Matched skills: {items('matched_skills')}",
            f"- Missing core skills / not shown on résumé: {items('missing_skills')}",
            f"- Optional / nice-to-have gaps: {items('optional_missing_skills')}",
            f"- Matched certifications: {items('matched_certs')}",
            f"- Other requested certifications: {items('missing_certs')}",
            f"- Score notes: {items('score_reasons', '; ')}",
            f"- Hard-reject reasons: {items('hard_reject_reasons', '; ')}",
            "",
            "When you apply, set the status:applied label (or drag the card on the Job Search board).",
            "",
        ]
    )


def _generate_resume(settings: Settings, scored: dict[str, Any], issue: dict[str, Any]) -> None:
    master = load_json(settings.paths.master_resume)
    if not resume_ready(master):
        print("Skipped the résumé: resumes/master_resume.json isn't filled in yet (see radar doctor).")
        return
    result = generate_resume(
        scored,
        master,
        vocab=settings.vocab,
        issue_number=str(issue["number"]),
        issue_url=str(issue.get("url", "")),
        resume_dir=settings.paths.resume_dir,
    )
    pending = settings.paths.pending_resume
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare(settings: Settings, issue: dict[str, Any], kind: str, label: str = "") -> None:
    """The résumé files for the event, if it needs one, to be committed before publish().

    Status changes need no files: the label is the status.
    """
    settings.paths.pending_resume.unlink(missing_ok=True)
    if kind == "intake":
        scored, verdict = _score(settings, issue)
        if verdict is Verdict.GOOD:
            _generate_resume(settings, scored, issue)
    elif kind == "resume":
        scored, _ = _score(settings, issue)
        _generate_resume(settings, scored, issue)


def publish(gh: GitHub, settings: Settings, issue: dict[str, Any], kind: str, label: str = "") -> None:
    """GitHub changes for the event, made after prepare()'s changes are committed."""
    number = int(issue["number"])
    if kind == "intake":
        scored, verdict = _score(settings, issue)
        gh.upsert_comment(number, REVIEW_MARKER, f"{REVIEW_MARKER}\n{build_review(scored, verdict)}")
        gh.ensure_labels(LABELS)
        publish_resume(gh, settings, issue)
        _apply_verdict(gh, issue, verdict)
    elif kind == "resume":
        publish_resume(gh, settings, issue)
    elif kind == "status":
        _apply_status(gh, issue, label)


def publish_resume(gh: GitHub, settings: Settings, issue: dict[str, Any]) -> None:
    """Link the résumé prepare() generated, if it generated one."""
    pending = settings.paths.pending_resume
    if not pending.exists():
        return
    result = json.loads(pending.read_text(encoding="utf-8"))
    number = int(issue["number"])
    gh.ensure_labels(["resume:ready"])
    remove = ["resume:tailor"] if "resume:tailor" in label_names(issue) else []
    gh.edit_issue(number, add_labels=["resume:ready"], remove_labels=remove)
    gh.upsert_comment(number, RESUME_MARKER, resume_comment(gh.repo, result))


def resume_comment(repo: str, result: dict[str, Any]) -> str:
    def link(path_key: str) -> str:
        return f"https://github.com/{repo}/blob/main/{result.get(path_key, '')}"

    return "\n".join(
        [
            RESUME_MARKER,
            "",
            "### Tailored resume",
            "",
            f"- [Resume source (Markdown)]({link('resume_markdown')})",
            f"- [Application resume (DOCX)]({link('resume_docx')})",
            f"- Master version: {result.get('master_version', '')}",
            f"- AI used: {str(bool(result.get('ai_used'))).lower()}",
            f"- AI model: {result.get('ai_model', '')}",
            f"- AI validation status: {result.get('ai_status', '')}",
            "",
            "AI wording is accepted only after deterministic checks and a separate factual-verification pass. "
            "If validation fails, the deterministic resume is used.",
        ]
    )


def _apply_verdict(gh: GitHub, issue: dict[str, Any], verdict: Verdict) -> None:
    number = int(issue["number"])
    labels = label_names(issue)
    match_label = f"match:{verdict.value}"
    gh.edit_issue(
        number,
        add_labels=["source:linkedin", match_label],
        remove_labels=sorted(((labels & MATCH_LABELS) - {match_label}) | (labels & {"needs:description"})),
    )

    current = {label for label in labels if label.startswith("status:")}
    if current - SCORER_STATUSES:
        return  # Re-scoring must not undo progress you made on the application.

    desired = "status:new" if verdict.tracked else "status:skipped"
    gh.edit_issue(number, add_labels=[desired], remove_labels=sorted(current - {desired}))
    if desired == "status:skipped":
        if issue.get("state") != "CLOSED":
            gh.close(number, comment=CLOSING_REASONS[verdict])
        return
    if issue.get("state") == "CLOSED":
        gh.reopen(number)
    if verdict is Verdict.POSSIBLE and "status:new" not in current:
        gh.comment(number, "Tracked as status:new. Change the status label as your application progresses.")


def _apply_status(gh: GitHub, issue: dict[str, Any], label: str) -> None:
    number = int(issue["number"])
    labels = label_names(issue)
    if label not in labels:
        return  # Replaced again before this event was handled; that event will follow.
    others = sorted({name for name in labels if name.startswith("status:")} - {label})
    if others:
        gh.edit_issue(number, remove_labels=others)
    if label in CLOSING_STATUSES:
        if issue.get("state") != "CLOSED":
            gh.close(number)
    elif issue.get("state") == "CLOSED":
        gh.reopen(number)
