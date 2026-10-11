"""`radar linkedin-search`: search LinkedIn in your own signed-in Chrome and import the job cards.

Run it by hand on a Mac. It searches each of `search.queries` (or `search.titles`) in each
`search.locations` entry that has a `linkedin:` location, collects the job cards, and hands
them to the same import as `radar linkedin-import`: on-target cards without an Issue become
"[LinkedIn Job]" Issues, to be scored once you paste in the description.

LinkedIn's terms forbid automated access, so the run is kept small and slow: a few searches,
4-9 second random pauses, a stop at the first security check, at most one run every 12 hours,
and never from CI or a schedule. It never applies, saves, messages or follows.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..linkedin_chrome import LINKEDIN_EXTRACT_JS, Chrome, ChromeControlError, canonical_url, search_url

POSTED_HOURS = {"24h": 24, "3d": 72, "7d": 168, "30d": 720}
MAX_QUERIES_CAP = 15
MIN_HOURS_BETWEEN_RUNS = 12
SCROLLS_PER_SEARCH = 3
LAST_RUN_STAMP = Path.home() / "Library" / "Application Support" / "job-radar" / "last_linkedin_search"


@dataclass(frozen=True)
class Search:
    keywords: str
    location: str
    remote: bool
    label: str


def plan_searches(config: Mapping[str, Any], max_queries: int) -> tuple[list[Search], int]:
    """Each keyword in each location with a `linkedin:` value; returns (searches, keywords left out)."""
    search = config.get("search") or {}
    keywords = [str(q).strip() for q in (search.get("queries") or search.get("titles") or []) if str(q).strip()]
    places = [place for place in search.get("locations") or [] if str(place.get("linkedin") or "").strip()]
    chosen = keywords[:max_queries]
    searches = [
        Search(
            keywords=keyword,
            location=str(place["linkedin"]).strip(),
            remote=bool(place.get("remote_only")),
            label=str(place.get("name") or place["linkedin"]),
        )
        for keyword in chosen
        for place in places
    ]
    return searches, len(keywords) - len(chosen)


def refusal(
    *,
    force: bool,
    setup_check: bool,
    stamp: Path,
    now: datetime,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> str:
    """Why this run must not go ahead, or "" when it may."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if env.get("CI") or env.get("GITHUB_ACTIONS"):
        return "radar linkedin-search runs only by hand on your own Mac, never in CI or on a schedule."
    if platform != "darwin":
        return "radar linkedin-search needs macOS and Google Chrome."
    if setup_check or force or not stamp.exists():
        return ""
    try:
        last = datetime.fromtimestamp(int(stamp.read_text(encoding="utf-8").strip()), timezone.utc)
    except (OSError, ValueError):
        return ""
    wait = last + timedelta(hours=MIN_HOURS_BETWEEN_RUNS) - now
    if wait > timedelta(0):
        hours = -(-int(wait.total_seconds()) // 3600)
        return (
            f"The last LinkedIn search was under {MIN_HOURS_BETWEEN_RUNS} hours ago; try again in about "
            f"{hours} hour(s), or add --force."
        )
    return ""


def check_sign_in(page: Mapping[str, Any]) -> None:
    if page.get("challenge"):
        raise ChromeControlError("LinkedIn is showing a security check. Complete it in Chrome, then run this again.")
    if page.get("loginWall") or not page.get("signedIn"):
        raise ChromeControlError(
            "LinkedIn is not signed in in Chrome's current profile. Sign in to LinkedIn in Chrome, then run this again."
        )


def collect_cards(
    chrome: Chrome,
    searches: list[Search],
    *,
    posted_hours: int,
    keep_open: bool = False,
    sleep: Callable[[float], None] | None = None,
    pause: Callable[[float, float], float] = random.uniform,
    log: Callable[[str], None] = print,
) -> tuple[list[dict[str, str]], list[str]]:
    """The job cards of every search, one per job, and any warnings; raises ChromeControlError."""
    sleep = sleep or time.sleep
    jobs: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    window = chrome.open_window()
    try:
        check_sign_in(chrome.load(window, "https://www.linkedin.com/jobs/", LINKEDIN_EXTRACT_JS))
        for index, search in enumerate(searches, 1):
            log(f"LinkedIn search {index}/{len(searches)}: {search.keywords} ({search.label})")
            url = search_url(search.keywords, search.location, remote=search.remote, posted_hours=posted_hours)
            page = chrome.load(window, url, LINKEDIN_EXTRACT_JS)
            if page.get("challenge"):
                warnings.append("LinkedIn showed a security check, so the remaining searches were stopped.")
                break
            if page.get("loginWall"):
                raise ChromeControlError("LinkedIn went back to its sign-in page during the search.")
            found = list(page.get("jobs") or [])
            for _ in range(SCROLLS_PER_SEARCH):
                chrome.scroll(window)
                sleep(pause(1.5, 3.0))
                found += chrome.execute(window, LINKEDIN_EXTRACT_JS).get("jobs") or []
            for job in found:
                url = canonical_url(job.get("url", ""))
                if url and url not in jobs:
                    jobs[url] = {**job, "job_url": url, "card_excerpt": str(job.get("cardText") or "")[:1500]}
            if index < len(searches):
                sleep(pause(4.0, 9.0))
    finally:
        if not keep_open:
            chrome.close(window)
    return list(jobs.values()), warnings


def export_cards(path: Path, jobs: list[dict[str, Any]]) -> None:
    """The radar linkedin-import file format."""
    fields = ("job_url", "title", "company", "location", "posted", "card_excerpt")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "jobs": [{key: str(job.get(key) or "") for key in fields} for job in jobs],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(
    *,
    posted: str = "7d",
    max_queries: int = 6,
    force: bool = False,
    dry_run: bool = False,
    export: str = "",
    setup_check: bool = False,
    keep_open: bool = False,
    chrome: Chrome | None = None,
    stamp: Path = LAST_RUN_STAMP,
) -> int:
    from ..settings import load_yaml
    from .linkedin_import import cards_from_jobs, publish_cards

    reason = refusal(force=force, setup_check=setup_check, stamp=stamp, now=datetime.now(timezone.utc))
    if reason:
        print(reason, file=sys.stderr)
        return 2
    chrome = chrome or Chrome()

    if setup_check:
        try:
            window = chrome.open_window()
            try:
                check_sign_in(chrome.load(window, "https://www.linkedin.com/jobs/", LINKEDIN_EXTRACT_JS))
            finally:
                chrome.close(window)
        except ChromeControlError as exc:
            print(f"Setup check failed: {exc}", file=sys.stderr)
            return 1
        print("Setup check passed: Chrome control and the LinkedIn sign-in are ready.")
        return 0

    searches, left_out = plan_searches(load_yaml("config/search_config.yaml") or {}, max_queries)
    if not searches:
        print(
            "Nothing to search: add search.titles (or search.queries) and a `linkedin:` location to at least one "
            "search.locations entry in config/search_config.yaml.",
            file=sys.stderr,
        )
        return 2

    # Stamped before searching, so a failed run still counts towards the 12-hour spacing.
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(f"{int(time.time())}\n", encoding="utf-8")
    print(f"Searching LinkedIn in Chrome: {len(searches)} search(es), posted within {posted}.")
    if left_out:
        print(f"{left_out} more keyword(s) not searched (--max-queries {max_queries}).")
    try:
        jobs, warnings = collect_cards(chrome, searches, posted_hours=POSTED_HOURS[posted], keep_open=keep_open)
    except ChromeControlError as exc:
        print(f"LinkedIn search failed: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    if export:
        export_cards(Path(export), jobs)
        print(f"Saved {len(jobs)} card(s) to {export}.")
    cards = cards_from_jobs(jobs)
    print(f"Found {len(cards)} LinkedIn job card(s).")
    return publish_cards(cards, dry_run=dry_run)
