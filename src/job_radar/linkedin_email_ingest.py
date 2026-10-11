from __future__ import annotations

import email
import imaplib
import json
import os
import re
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .github import GitHub
from .ids import linkedin_job_id, linkedin_job_url
from .issue_body import job_url, render_linkedin_alert
from .matcher import Vocabulary, title_score
from .normalize import split_company_location, title_matches_exclusion
from .report import write_report
from .settings import load_yaml

GENERIC_LINK_TEXT = {
    "view job",
    "view jobs",
    "see job",
    "see jobs",
    "apply",
    "apply now",
    "view",
    "learn more",
    "show more",
}

UNKNOWN = "Unknown — edit before scoring"

# Section headers in alert digests link to a job but are not job cards,
# e.g. "Jobs similar to Staff Nurse at Example Health".
DIGEST_HEADER = re.compile(
    r"^(?:new\s+)?jobs?\s+similar\s+to\b|^(?:see|view|show)\s+(?:all|more)\b|^your\s+job\s+alerts?\b",
    flags=re.IGNORECASE,
)


def _is_digest_header(value: str) -> bool:
    return bool(DIGEST_HEADER.search(_clean(value)))


def canonical_linkedin_job_url(href: str) -> tuple[str, str] | None:
    job_id = linkedin_job_id(href)
    return (job_id, linkedin_job_url(job_id)) if job_id else None


def _clean(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _header(msg: Message, name: str) -> str:
    """A header with RFC 2047 words decoded: LinkedIn subjects use curly quotes, so arrive as =?utf-8?b?...?=."""
    value = str(msg.get(name, ""))
    try:
        value = str(make_header(decode_header(value)))
    except Exception:
        pass
    return _clean(value)


def _message_bodies(msg: Message) -> tuple[str, str]:
    html_parts: list[str] = []
    text_parts: list[str] = []

    if msg.is_multipart():
        parts = msg.walk()
    else:
        parts = [msg]

    for part in parts:
        content_type = part.get_content_type()
        if content_type not in {"text/html", "text/plain"}:
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
        except Exception:
            continue
        if content_type == "text/html":
            html_parts.append(decoded)
        else:
            text_parts.append(decoded)

    return "\n".join(html_parts), "\n".join(text_parts)


def _anchor_context(anchor: Any) -> list[str]:
    node = anchor
    best: list[str] = []
    for _ in range(5):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = node.get_text("\n", strip=True)
        lines = []
        seen: set[str] = set()
        for raw in text.splitlines():
            line = _clean(raw)
            key = line.lower()
            if not line or key in seen:
                continue
            seen.add(key)
            lines.append(line)
        if 2 <= len(lines) <= 14:
            best = lines
            if len(lines) >= 3:
                break
    return best


def _looks_like_title(value: str) -> bool:
    value = _clean(value)
    if not value or value.lower() in GENERIC_LINK_TEXT or _is_digest_header(value):
        return False
    if len(value) < 3 or len(value) > 160:
        return False
    return True


def extract_candidates_from_html(html_body: str) -> list[dict[str, str]]:
    if not html_body:
        return []

    soup = BeautifulSoup(html_body, "html.parser")
    found: dict[str, dict[str, str]] = {}

    for anchor in soup.find_all("a", href=True):
        canonical = canonical_linkedin_job_url(str(anchor.get("href", "")))
        if not canonical:
            continue

        job_id, url = canonical
        anchor_text = _clean(anchor.get_text(" ", strip=True))
        if _is_digest_header(anchor_text):
            continue
        context = _anchor_context(anchor)

        title = anchor_text if _looks_like_title(anchor_text) else ""
        if not title and not any(_is_digest_header(line) for line in context):
            for line in context:
                if _looks_like_title(line):
                    title = line
                    break

        if not title:
            continue

        company = ""
        location = ""

        try:
            title_idx = next(i for i, line in enumerate(context) if line.lower() == title.lower())
        except StopIteration:
            title_idx = -1

        if title_idx >= 0:
            trailing = [
                line
                for line in context[title_idx + 1 :]
                if line.lower() not in GENERIC_LINK_TEXT and "linkedin" not in line.lower()
            ]
            if trailing:
                # Alert cards put "Company · Location" on one line.
                company, location = split_company_location(trailing[0][:160])
            if not location and len(trailing) > 1:
                location = trailing[1][:160]

        found[job_id] = {
            "job_id": job_id,
            "job_url": url,
            "title": title,
            "company": company or UNKNOWN,
            "location": location or UNKNOWN,
            "card_excerpt": "\n".join(context)[:1500],
        }

    return list(found.values())


def _load_state(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"last_uid": 0, "processed_job_ids": []}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {}
    state.setdefault("last_uid", 0)
    state.setdefault("processed_job_ids", [])
    return state


def _save_state(path: str | Path, state: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    processed = list(dict.fromkeys(state.get("processed_job_ids", [])))[-5000:]
    state["processed_job_ids"] = processed
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sender_domain(sender: str) -> str:
    match = re.search(r"@([\w.-]+)", sender)
    return match.group(1).lower() if match else "unknown sender"


def _alert_messages(
    mailbox: Any, last_uid: int, since_days: int | None = None
) -> Iterator[tuple[int, Message | None, str]]:
    """Yield (uid, message, note) for new mail; message is None when it is not from LinkedIn.

    since_days re-reads that many days of mail instead of continuing from last_uid.
    """
    if last_uid > 0 and not since_days:
        status, data = mailbox.uid("search", None, f"UID {last_uid + 1}:*")
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=since_days or 3)).strftime("%d-%b-%Y")
        status, data = mailbox.uid("search", None, "SINCE", since)

    if status != "OK":
        raise RuntimeError("IMAP search failed")

    for uid in [int(x) for x in (data[0] or b"").split() if x.isdigit()]:
        # "UID n:*" always matches the newest message, even when it is older than n.
        if not since_days and uid <= last_uid:
            continue
        status, msg_data = mailbox.uid("fetch", str(uid), "(RFC822)")
        raw = None
        if status == "OK":
            for item in msg_data or []:
                if isinstance(item, tuple) and len(item) > 1:
                    raw = item[1]
                    break
        if not raw:
            yield uid, None, "could not be fetched"
            continue

        msg = email.message_from_bytes(raw)
        domain = _sender_domain(_header(msg, "From"))
        # Any LinkedIn mail is read: alert subjects vary ("“registered nurse”: Acme - Registered Nurse and more"),
        # and only job links whose titles match the search titles become Issues.
        if domain != "linkedin.com" and not domain.endswith(".linkedin.com"):
            yield uid, None, f"not from LinkedIn ({domain})"
            continue
        yield uid, msg, ""


def ingest(
    mailbox: Any,
    state_path: str | Path,
    *,
    exclusions: list[str],
    target_titles: list[str],
    create_issue: Callable[[str, str], str],
    vocab: Vocabulary | None = None,
    known_job_ids: frozenset[str] = frozenset(),
    since_days: int | None = None,
    dry_run: bool = False,
    notes: list[str] | None = None,
) -> tuple[list[dict[str, str]], int]:
    """Create review Issues for new alert jobs; returns (created, skipped).

    known_job_ids are LinkedIn jobs that already have an Issue (for example one
    submitted through the form); they are not imported again. A dry run never
    writes the state file. notes, when given, gets one line per email read.
    """
    state = _load_state(state_path)
    processed = {str(x) for x in state.get("processed_job_ids", [])}
    last_uid = int(state.get("last_uid", 0) or 0)
    created: list[dict[str, str]] = []
    skipped = 0
    notes = notes if notes is not None else []

    def save() -> None:
        if dry_run:
            return
        state["last_uid"] = last_uid
        state["processed_job_ids"] = sorted(processed)
        _save_state(state_path, state)

    try:
        for uid, msg, note in _alert_messages(mailbox, last_uid, since_days):
            if msg is None:
                notes.append(f"UID {uid}: {note}")
            else:
                subject = _header(msg, "Subject")
                html_body, _ = _message_bodies(msg)
                candidates = extract_candidates_from_html(html_body)
                seen = new = off_target = 0
                for candidate in candidates:
                    job_id = candidate["job_id"]
                    if job_id in processed or job_id in known_job_ids:
                        seen += 1
                        continue

                    title = candidate["title"]
                    if title_matches_exclusion(title, exclusions) or title_score(title, target_titles, vocab)[0] <= 0:
                        processed.add(job_id)
                        skipped += 1
                        off_target += 1
                        continue

                    issue_title = f"[LinkedIn Alert] {title} — {candidate['company']}"
                    issue_url = create_issue(issue_title, render_linkedin_alert(candidate, subject))
                    created.append({**candidate, "issue_url": issue_url})
                    processed.add(job_id)
                    new += 1
                    # Persist every Issue at once so a later failure cannot re-create it.
                    save()
                outcome = (
                    f"{len(candidates)} job(s): {new} new, {off_target} off-target title, {seen} already imported"
                    if candidates
                    else "no job links found"
                )
                notes.append(f"UID {uid}: LinkedIn, “{subject}” — {outcome}")
            # Only a fully processed message moves the UID cursor forward.
            last_uid = max(last_uid, uid)
    finally:
        save()

    return created, skipped


def title_exclusions(config: dict[str, Any]) -> list[str]:
    """Titles not to import: search.exclude_title_terms, plus the terms scoring would reject anyway."""
    search, ranking = config.get("search") or {}, config.get("ranking") or {}
    terms = (search.get("exclude_title_terms") or []) + (ranking.get("hard_reject_title_terms") or [])
    return list(dict.fromkeys(terms))


def main(*, dry_run: bool = False, since_days: int | None = None) -> int:
    host = os.environ.get("LINKEDIN_IMAP_HOST", "").strip()
    user = os.environ.get("LINKEDIN_IMAP_USER", "").strip()
    password = os.environ.get("LINKEDIN_IMAP_PASSWORD", "")
    port = int(os.environ.get("LINKEDIN_IMAP_PORT", "993"))
    folder = os.environ.get("LINKEDIN_IMAP_FOLDER", "INBOX").strip() or "INBOX"
    state_path = os.environ.get("LINKEDIN_EMAIL_STATE_PATH", "data/linkedin_email_state.json")
    report_path = os.environ.get("LINKEDIN_EMAIL_REPORT_PATH", "reports/linkedin-email-latest.md")

    if not host or not user or not password:
        raise RuntimeError(
            "Missing IMAP settings. Configure LINKEDIN_IMAP_HOST, "
            "LINKEDIN_IMAP_USER, and LINKEDIN_IMAP_PASSWORD as GitHub Secrets."
        )

    config = load_yaml("config/search_config.yaml")
    gh = GitHub()
    known_job_ids = frozenset(
        job_id for issue in gh.issues() if (job_id := linkedin_job_id(job_url(str(issue.get("body", "")))))
    )

    if not dry_run:
        gh.ensure_labels(["needs:description"])

    def create_issue(title: str, body: str) -> str:
        if dry_run:
            return "#"
        number = gh.create_issue(title, body, labels=["needs:description"], assignee=gh.owner)
        return f"https://github.com/{gh.repo}/issues/{number}"

    notes: list[str] = []
    mailbox = imaplib.IMAP4_SSL(host, port)
    try:
        mailbox.login(user, password)
        status, _ = mailbox.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not select IMAP folder: {folder}")
        created, skipped = ingest(
            mailbox,
            state_path,
            exclusions=title_exclusions(config),
            target_titles=config["search"].get("titles") or [],
            vocab=Vocabulary.from_config(config),
            create_issue=create_issue,
            known_job_ids=known_job_ids,
            since_days=since_days,
            dry_run=dry_run,
            notes=notes,
        )
    finally:
        try:
            mailbox.logout()
        except Exception:
            pass

    verb = "Would create" if dry_run else "Created"
    lines = [
        f"# LinkedIn Email Intake{' (dry run)' if dry_run else ''} — {datetime.now(timezone.utc).isoformat()}",
        "",
        f"{verb} **{len(created)}** review issue(s).",
        f"Skipped **{skipped}** off-target or excluded job(s).",
        "",
    ]
    for item in created:
        lines.append(f"- [{item['title']}]({item['issue_url']}) — {item['company']} · {item['location']}")
    lines += ["", f"## Emails read ({folder})", ""]
    lines += [f"- {note}" for note in notes] or ["No new email since the last run."]
    lines.append("")
    if not dry_run:
        write_report(report_path, "\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
