from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _fmt_list(values: list[str]) -> str:
    return ", ".join(values) if values else "—"


def _salary(job: dict[str, Any]) -> str:
    lo = job.get("min_amount")
    hi = job.get("max_amount")
    cur = job.get("currency") or ""
    if lo and hi:
        return f"{cur} {lo}–{hi}".strip()
    if lo:
        return f"{cur} {lo}+".strip()
    return "Not listed"


def build_report(
    good: list[dict[str, Any]],
    possible: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    errors: list[str],
    total_collected: int,
    unseen_count: int,
    good_threshold: int,
    possible_threshold: int,
    tz: ZoneInfo | None = None,
) -> str:
    # Runners use UTC, so an evening scan west of UTC would otherwise be dated tomorrow.
    today = datetime.now(tz or ZoneInfo("UTC")).strftime("%Y-%m-%d")
    lines = [
        f"# Job Radar — {today}",
        "",
        f"Collected **{total_collected}** unique jobs; **{unseen_count}** were new to the tracker.",
        f"Shortlist: **{len(good)} good matches** and **{len(possible)} possible matches**.",
        "",
    ]

    if good:
        lines += ["## Apply first / good matches", ""]
        for job in good:
            lines += _job_block(job, good_threshold=good_threshold)
    else:
        lines += [
            "## Apply first / good matches",
            "",
            "No new jobs reached the configured good-match threshold today.",
            "",
        ]

    if possible:
        lines += ["## Possible matches", ""]
        for job in possible:
            lines += _job_block(job, good_threshold=good_threshold)

    if rejected:
        lines += [
            "## Automatically excluded",
            "",
            "These were excluded by title rules or experience requirements (reason in brackets):",
            "",
        ]
        for job in rejected[:10]:
            reasons = "; ".join(job.get("hard_reject_reasons", []))
            lines.append(f"- **{job.get('title', '')}** — {job.get('company', '')} ({reasons})")
        lines.append("")

    if errors:
        lines += ["## Collector warnings", ""]
        for error in errors[:20]:
            lines.append(f"- {error}")
        lines.append("")

    lines += [
        "---",
        "Good and possible matches each have a job Issue. Track your progress with its `status:*` "
        "label or by dragging its card on the Job Search board.",
        "",
    ]
    return "\n".join(lines)


def _job_block(job: dict[str, Any], good_threshold: int) -> list[str]:
    score = job.get("score", 0)
    label = "🔥 APPLY FIRST" if score >= 85 else ("✅ GOOD MATCH" if score >= good_threshold else "🟡 POSSIBLE")
    url = job.get("job_url") or ""
    title = job.get("title", "Untitled")
    title_text = f"[{title}]({url})" if url else title
    return [
        f"### {score}% — {title_text}",
        "",
        f"**{job.get('company', 'Unknown company')}** · {job.get('location', 'Location not listed')} · "
        f"{job.get('source', '')} · **{label}**",
        "",
        f"- Posted: {job.get('date_posted') or 'Unknown'}",
        f"- Salary: {_salary(job)}",
        f"- Matched skills: {_fmt_list(job.get('matched_skills', []))}",
        f"- Missing core skills / not shown on résumé: {_fmt_list(job.get('missing_skills', []))}",
        f"- Optional / nice-to-have gaps: {_fmt_list(job.get('optional_missing_skills', []))}",
        f"- Matched certifications: {_fmt_list(job.get('matched_certs', []))}",
        f"- Other requested certifications: {_fmt_list(job.get('missing_certs', []))}",
        f"- Score notes: {'; '.join(job.get('score_reasons', []))}",
        "",
    ]


def write_report(path: str | Path, content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
