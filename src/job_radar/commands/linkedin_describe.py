"""`radar linkedin-describe`: fill in the description of LinkedIn Issues that are waiting for one.

LinkedIn alert emails and search cards carry no description, so their Issues wait, labelled
needs:description, for you to paste it. This reads each waiting job's public posting page (the
one shown to people who aren't signed in) and writes the description into the Issue, which
issue-events.yml then scores as if you had pasted it.

It is opt-in: no workflow runs it. Run it by hand, or install the Mac agent
(tools/mac/install-linkedin-describe-agent.sh) to run it every couple of hours. No LinkedIn
account is used, but LinkedIn's terms forbid automated access, so it stays small and slow: a
few postings per run, a pause between them, one retry and then a stop when LinkedIn refuses, and never from
CI (LinkedIn blocks GitHub's servers anyway).
"""

from __future__ import annotations

import os
import random
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..github import GitHub, label_names
from ..ids import linkedin_job_id
from ..issue_body import MAX_DESCRIPTION_CHARS, PLACEHOLDER_MARKER, job_url
from ..linkedin_email_ingest import UNKNOWN
from ..linkedin_guest import GuestBlocked, GuestError, PostingGone, fetch_posting

LABEL = "needs:description"
LINKEDIN_PREFIXES = ("[LinkedIn Job]", "[LinkedIn Alert]")
MAX_JOBS_CAP = 40
BLOCKED_EXIT = 4
RETRY_PAUSE = (90.0, 150.0)
GONE_MARKER = "<!-- job-radar:description-unavailable -->"
GONE_COMMENT = (
    f"{GONE_MARKER}\n"
    "LinkedIn no longer shows this posting publicly, so `radar linkedin-describe` couldn't read its "
    "description. If the job is still open for you, paste the description into the Issue by hand."
)
_PLACEHOLDER_LINE = re.compile(rf"^.*{re.escape(PLACEHOLDER_MARKER)}.*$", re.MULTILINE)


@dataclass
class Outcome:
    filled: list[int] = field(default_factory=list)
    gone: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    waiting: int = 0
    blocked: bool = False


def refusal(env: Mapping[str, str] | None = None) -> str:
    """Why this run must not go ahead, or "" when it may."""
    env = os.environ if env is None else env
    if env.get("CI") or env.get("GITHUB_ACTIONS"):
        return "radar linkedin-describe runs only on your own computer, never in CI: LinkedIn blocks GitHub's servers."
    return ""


def pending(issues: list[dict[str, Any]]) -> list[tuple[int, str, str, str]]:
    """(number, LinkedIn job ID, body, title) of the open LinkedIn Issues still waiting for a description."""
    waiting = []
    for issue in issues:
        body = str(issue.get("body") or "")
        if (
            str(issue.get("state", "OPEN")).upper() != "OPEN"
            or not str(issue.get("title", "")).startswith(LINKEDIN_PREFIXES)
            or LABEL not in label_names(issue)
            or PLACEHOLDER_MARKER not in body
        ):
            continue
        job_id = linkedin_job_id(job_url(body))
        if job_id:
            waiting.append((int(issue["number"]), job_id, body, str(issue.get("title", ""))))
    return waiting


def _set_field(body: str, heading: str, value: str, *, only_if: str = r"[^\n]*") -> str:
    """Replace the one-line value under a "### heading" (only when it matches only_if)."""
    return re.sub(
        rf"(^###[ \t]+{re.escape(heading)}[ \t]*\n+){only_if}[ \t]*$",
        lambda match: match.group(1) + value,
        body,
        count=1,
        flags=re.MULTILINE,
    )


def card_was_misread(body: str, posting: Mapping[str, str]) -> bool:
    """True when the card gave no company, so its title line holds the company and place too
    ("Threat Analyst 1 Sophos · Canada (Remote)"), and the page can supply both."""
    no_company = re.search(rf"^###[ \t]+Company[ \t]*\n+{re.escape(UNKNOWN)}[ \t]*$", body, flags=re.MULTILINE)
    return bool(no_company and str(posting.get("title") or "").strip() and str(posting.get("company") or "").strip())


def repaired_title(issue_title: str, body: str, posting: Mapping[str, str]) -> str | None:
    """The Issue title rebuilt from the page when the card was misread, else None to keep it."""
    if not card_was_misread(body, posting):
        return None
    prefix = next((p for p in LINKEDIN_PREFIXES if issue_title.startswith(p)), LINKEDIN_PREFIXES[0])
    return f"{prefix} {posting['title'].strip()[:160]} — {posting['company'].strip()[:160]}"


def fill_body(body: str, posting: Mapping[str, str]) -> str:
    """The Issue body with the placeholder replaced by the description, and unknown card fields filled in."""
    if card_was_misread(body, posting):
        body = _set_field(body, "Job title", posting["title"].strip()[:160])
    description = posting["description"].strip()
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS].rstrip() + "\n\n[Description truncated in GitHub Issue.]"
    body = _PLACEHOLDER_LINE.sub(lambda _: description, body, count=1)
    for heading, key in (("Company", "company"), ("Location", "location")):
        value = str(posting.get(key) or "").strip()
        if value:
            body = _set_field(body, heading, value, only_if=re.escape(UNKNOWN))
    return body


def describe_pending(
    gh: Any,
    *,
    max_jobs: int = 15,
    dry_run: bool = False,
    fetch: Callable[[str], dict[str, str]] = fetch_posting,
    sleep: Callable[[float], None] = time.sleep,
    pause: Callable[[float, float], float] = random.uniform,
    log: Callable[[str], None] = print,
) -> Outcome:
    """Read up to max_jobs waiting postings and write their descriptions into their Issues."""
    waiting = pending(gh.issues())
    outcome = Outcome(waiting=len(waiting))
    chosen = waiting[:max_jobs]
    retried = False
    for index, (number, job_id, body, title) in enumerate(chosen):
        if index:
            sleep(pause(3.0, 8.0))
        try:
            try:
                posting = fetch(job_id)
            except GuestBlocked as exc:
                # LinkedIn's rate limit often lifts within a minute or two: wait once per run, then give up.
                if retried:
                    raise
                retried = True
                log(f"#{number}: {exc}. Waiting before one more try.")
                sleep(pause(*RETRY_PAUSE))
                posting = fetch(job_id)
        except PostingGone:
            outcome.gone.append(number)
            log(f"#{number}: no longer on LinkedIn's public pages.")
            if not dry_run:
                # Without the label it isn't tried again; the Issue stays open for you to decide.
                gh.upsert_comment(number, GONE_MARKER, GONE_COMMENT)
                gh.edit_issue(number, remove_labels=[LABEL])
            continue
        except GuestBlocked as exc:
            outcome.blocked = True
            log(f"#{number}: {exc}. Stopped; the rest will be tried on a later run.")
            break
        except GuestError as exc:
            outcome.failed.append(number)
            log(f"#{number}: could not be read ({exc}).")
            continue
        outcome.filled.append(number)
        log(f"#{number}: {'would fill in' if dry_run else 'filled in'} {len(posting['description'])} characters.")
        if not dry_run:
            gh.edit_issue(number, title=repaired_title(title, body, posting), body=fill_body(body, posting))
    return outcome


def main(*, max_jobs: int = 15, dry_run: bool = False) -> int:
    reason = refusal()
    if reason:
        print(reason, file=sys.stderr)
        return 2
    gh = GitHub()
    outcome = describe_pending(gh, max_jobs=max_jobs, dry_run=dry_run)
    if not outcome.waiting:
        print(f"{gh.repo}: no LinkedIn Issue is waiting for a description.")
        return 0
    verb = "Would fill in" if dry_run else "Filled in"
    left = outcome.waiting - len(outcome.filled) - len(outcome.gone)
    print(
        f"{gh.repo}: {verb} {len(outcome.filled)} of {outcome.waiting} waiting Issue(s); "
        f"{len(outcome.gone)} gone from LinkedIn, {len(outcome.failed)} unreadable, {left} still waiting."
    )
    if outcome.filled and not dry_run:
        print("Scoring starts by itself (Actions → Job Issue Events).")
    return BLOCKED_EXIT if outcome.blocked else 0
