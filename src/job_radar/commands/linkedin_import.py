"""Import LinkedIn job cards found by a search in your own signed-in Chrome.

`radar linkedin-search` feeds its cards straight into import_cards(); with
--export it also writes them to a file in this format, which
`radar linkedin-import FILE` reads:

    {"generated_at": "...", "jobs": [{"job_url", "title", "company", "location",
                                      "posted", "card_excerpt"}, ...]}

Each new on-target job becomes a "[LinkedIn Job]" Issue labelled
needs:description, exactly like an alert-email job: cards carry no description,
so the Issue is scored once you paste it in.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ..ids import linkedin_job_id, linkedin_job_url
from ..issue_body import job_url, render_linkedin_search
from ..linkedin_email_ingest import UNKNOWN, title_exclusions
from ..matcher import Vocabulary, title_score
from ..normalize import split_company_location, title_matches_exclusion


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def read_cards(path: str | Path) -> list[dict[str, str]]:
    """The LinkedIn cards in an export file, one per job ID, in file order."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return cards_from_jobs(data.get("jobs", []) if isinstance(data, dict) else data)


def cards_from_jobs(jobs: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """Clean card records, one per LinkedIn job ID, in order."""
    cards: dict[str, dict[str, str]] = {}
    for job in jobs:
        job_id = linkedin_job_id(str(job.get("job_url") or job.get("url") or ""))
        title = _clean(job.get("title"))
        if not job_id or not title or job_id in cards:
            continue
        company, location = split_company_location(_clean(job.get("company")), _clean(job.get("location")))
        cards[job_id] = {
            "job_id": job_id,
            "job_url": linkedin_job_url(job_id),
            "title": title[:160],
            "company": company[:160] or UNKNOWN,
            "location": location[:160] or UNKNOWN,
            "date_posted": _clean(job.get("posted"))[:40],
            "card_excerpt": str(job.get("card_excerpt") or job.get("cardText") or "").strip()[:1500],
        }
    return list(cards.values())


def known_linkedin_ids(issues: Iterable[dict[str, Any]]) -> frozenset[str]:
    """LinkedIn job IDs that already have an Issue, open or closed."""
    return frozenset(job_id for issue in issues if (job_id := linkedin_job_id(job_url(str(issue.get("body", ""))))))


def import_cards(
    cards: list[dict[str, str]],
    *,
    exclusions: list[str],
    target_titles: list[str],
    known_job_ids: frozenset[str],
    create_issue: Callable[[str, str], str],
    vocab: Vocabulary | None = None,
) -> tuple[list[dict[str, str]], int, int]:
    """Create review Issues for new on-target cards; returns (created, off_target, already_tracked)."""
    created: list[dict[str, str]] = []
    off_target = already = 0
    for card in cards:
        if card["job_id"] in known_job_ids:
            already += 1
            continue
        title = card["title"]
        if title_matches_exclusion(title, exclusions) or title_score(title, target_titles, vocab)[0] <= 0:
            off_target += 1
            continue
        issue_url = create_issue(f"[LinkedIn Job] {title} — {card['company']}", render_linkedin_search(card))
        created.append({**card, "issue_url": issue_url})
    return created, off_target, already


def main(path: str | Path, *, dry_run: bool = False) -> int:
    cards = read_cards(path)
    print(f"Read {len(cards)} LinkedIn job card(s) from {path}.")
    return publish_cards(cards, dry_run=dry_run)


def publish_cards(cards: list[dict[str, str]], *, dry_run: bool = False) -> int:
    """A "[LinkedIn Job]" Issue for each new on-target card (or, in a dry run, a list of them)."""
    from ..github import GitHub
    from ..settings import load_yaml

    config = load_yaml("config/search_config.yaml")
    gh = GitHub()
    if not dry_run and cards:
        gh.ensure_labels(["needs:description"])

    def create_issue(title: str, body: str) -> str:
        if dry_run:
            return "#"
        number = gh.create_issue(title, body, labels=["needs:description"], assignee=gh.owner)
        return f"https://github.com/{gh.repo}/issues/{number}"

    created, off_target, already = import_cards(
        cards,
        exclusions=title_exclusions(config),
        target_titles=config["search"].get("titles") or [],
        vocab=Vocabulary.from_config(config),
        known_job_ids=known_linkedin_ids(gh.issues()) if cards else frozenset(),
        create_issue=create_issue,
    )

    verb = "Would create" if dry_run else "Created"
    print(f"{verb} {len(created)} [LinkedIn Job] Issue(s): {already} already tracked, {off_target} off-target.")
    for item in created:
        print(f"- {item['title']} — {item['company']} · {item['location']}  {item['issue_url']}")
    if created and not dry_run:
        print("Paste each job's full description into its Issue (label needs:description) to score it.")
    return 0
