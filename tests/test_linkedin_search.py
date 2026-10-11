"""radar linkedin-search: the searches it plans, its guardrails, and reading cards through a fake Chrome."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from job_radar.commands import linkedin_import, linkedin_search
from job_radar.commands.linkedin_import import cards_from_jobs, import_cards
from job_radar.commands.linkedin_search import Search, collect_cards, plan_searches, refusal
from job_radar.linkedin_chrome import (
    CLOSE_WINDOW,
    CREATE_WINDOW,
    EXECUTE_IN_TAB,
    LINKEDIN_EXTRACT_JS,
    RUN_IN_TAB,
    Chrome,
    ChromeControlError,
    search_url,
)
from job_radar.matcher import Vocabulary
from job_radar.settings import load_yaml

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
SIGNED_IN = {"signedIn": True, "jobs": []}


def card(job_id: str, title: str, company: str = "Acme", location: str = "Toronto, ON") -> dict:
    return {
        "title": title,
        "company": company,
        "location": location,
        "posted": "1 day ago",
        "url": f"https://www.linkedin.com/jobs/view/{job_id}/?trk=search",
        "cardText": f"{title}\n{company}\n{location}",
    }


class FakeChromeRunner:
    """Answers the AppleScript calls Chrome makes: pages by URL, then what scrolling reveals."""

    def __init__(self, pages: dict[str, dict], scrolled: dict | None = None) -> None:
        self.pages = pages
        self.scrolled = scrolled or {"jobs": []}
        self.loaded: list[str] = []
        self.closed = False

    def __call__(self, source: str, *args, timeout: float = 75) -> str:
        if source == CREATE_WINDOW:
            return "42"
        if source == CLOSE_WINDOW:
            self.closed = True
            return ""
        if source == RUN_IN_TAB:
            url = args[1]
            self.loaded.append(url)
            key = "start" if url == "https://www.linkedin.com/jobs/" else parse_qs(urlparse(url).query)["keywords"][0]
            return json.dumps(self.pages[key])
        if source == EXECUTE_IN_TAB:
            return json.dumps(self.scrolled) if args[1] == LINKEDIN_EXTRACT_JS else "ok"
        raise AssertionError(f"unexpected AppleScript: {source[:40]}")


def collect(runner: FakeChromeRunner, searches: list[Search]):
    return collect_cards(
        Chrome(runner), searches, posted_hours=24, sleep=lambda _: None, pause=lambda a, b: a, log=lambda _: None
    )


def test_search_url_asks_for_newest_first_within_the_posting_age():
    remote = parse_qs(urlparse(search_url("Registered Nurse", "Canada", remote=True, posted_hours=24)).query)
    assert remote == {
        "keywords": ["Registered Nurse"],
        "location": ["Canada"],
        "f_WT": ["2"],
        "f_TPR": ["r86400"],
        "sortBy": ["DD"],
    }
    local = parse_qs(urlparse(search_url("RN", "Toronto, Ontario, Canada", remote=False, posted_hours=168)).query)
    assert "f_WT" not in local and local["f_TPR"] == ["r604800"]


def test_searches_cover_each_keyword_in_each_linkedin_location():
    config = {
        "search": {
            "titles": ["Nurse", "RN", "Charge Nurse"],
            "locations": [
                {"name": "Toronto", "query": "Toronto, ON", "linkedin": "Toronto, Ontario, Canada"},
                {"name": "Ottawa", "query": "Ottawa, ON"},  # no linkedin: not searched on LinkedIn
                {"name": "Remote", "query": "Canada", "remote_only": True, "linkedin": "Canada"},
            ],
        }
    }
    searches, left_out = plan_searches(config, max_queries=2)
    assert [(s.keywords, s.location, s.remote) for s in searches] == [
        ("Nurse", "Toronto, Ontario, Canada", False),
        ("Nurse", "Canada", True),
        ("RN", "Toronto, Ontario, Canada", False),
        ("RN", "Canada", True),
    ]
    assert left_out == 1
    # search.queries, when set, are searched instead of the titles.
    config["search"]["queries"] = ["nursing"]
    assert [s.keywords for s in plan_searches(config, max_queries=6)[0]] == ["nursing", "nursing"]


def test_it_never_runs_in_ci_or_off_a_mac(tmp_path):
    stamp = tmp_path / "stamp"
    assert "never in CI" in refusal(force=True, setup_check=True, stamp=stamp, now=NOW, env={"CI": "true"})
    assert "never in CI" in refusal(force=True, setup_check=False, stamp=stamp, now=NOW, env={"GITHUB_ACTIONS": "1"})
    assert "macOS" in refusal(force=True, setup_check=False, stamp=stamp, now=NOW, env={}, platform="linux")
    assert refusal(force=False, setup_check=False, stamp=stamp, now=NOW, env={}, platform="darwin") == ""


def test_runs_are_at_least_twelve_hours_apart_unless_forced(tmp_path):
    stamp = tmp_path / "stamp"
    stamp.write_text(str(int((NOW - timedelta(hours=3)).timestamp())), encoding="utf-8")
    kwargs = {"stamp": stamp, "now": NOW, "env": {}, "platform": "darwin"}
    assert "about 9 hour(s)" in refusal(force=False, setup_check=False, **kwargs)
    assert refusal(force=True, setup_check=False, **kwargs) == ""
    assert refusal(force=False, setup_check=True, **kwargs) == ""
    stamp.write_text(str(int((NOW - timedelta(hours=13)).timestamp())), encoding="utf-8")
    assert refusal(force=False, setup_check=False, **kwargs) == ""


def test_cards_from_every_search_become_issues_once(tmp_path):
    runner = FakeChromeRunner(
        {
            "start": SIGNED_IN,
            "SOC Analyst": {"jobs": [card("1", "SOC Analyst"), card("2", "Senior SOC Analyst")]},
            "Security Operations Analyst": {"jobs": [card("1", "SOC Analyst"), card("3", "Line Cook", "Diner")]},
        },
        scrolled={"jobs": [card("4", "Security Operations Analyst", "Beta", "Canada (Remote)")]},
    )
    searches = [
        Search("SOC Analyst", "Toronto, Ontario, Canada", False, "Toronto"),
        Search("Security Operations Analyst", "Canada", True, "Remote"),
    ]
    jobs, warnings = collect(runner, searches)

    assert warnings == [] and runner.closed
    assert len(runner.loaded) == 3  # the sign-in check, then one page per search
    cards = cards_from_jobs(jobs)
    assert [c["job_id"] for c in cards] == ["1", "2", "4", "3"]

    config = load_yaml(FIXTURES / "config/search_config.yaml")
    made = []
    created, off_target, already = import_cards(
        cards,
        exclusions=linkedin_import.title_exclusions(config),
        target_titles=config["search"]["titles"],
        vocab=Vocabulary.from_config(config),
        known_job_ids=frozenset({"4"}),
        create_issue=lambda title, body: made.append(title) or "#",
    )
    assert made == ["[LinkedIn Job] SOC Analyst — Acme"]
    assert (off_target, already) == (2, 1)


def test_a_security_check_stops_the_remaining_searches():
    runner = FakeChromeRunner(
        {"start": SIGNED_IN, "one": {"challenge": True, "jobs": []}, "two": {"jobs": [card("9", "Nurse")]}}
    )
    jobs, warnings = collect(runner, [Search("one", "Canada", False, "x"), Search("two", "Canada", False, "x")])
    assert jobs == [] and "security check" in warnings[0]
    assert runner.closed and len(runner.loaded) == 2


@pytest.mark.parametrize("start", [{"signedIn": False}, {"loginWall": True}, {"signedIn": True, "challenge": True}])
def test_no_search_runs_unless_signed_in_and_unchallenged(start):
    runner = FakeChromeRunner({"start": start})
    with pytest.raises(ChromeControlError):
        collect(runner, [Search("Nurse", "Canada", False, "x")])
    assert runner.closed and len(runner.loaded) == 1


def test_main_searches_exports_and_hands_cards_to_the_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(linkedin_search.time, "sleep", lambda _: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/search_config.yaml").write_text(
        "search:\n  titles: [Registered Nurse]\n  locations:\n"
        "    - {name: Toronto, query: 'Toronto, ON', linkedin: 'Toronto, Ontario, Canada'}\n",
        encoding="utf-8",
    )
    published = []
    monkeypatch.setattr(
        linkedin_import, "publish_cards", lambda cards, dry_run: published.append((cards, dry_run)) or 0
    )
    runner = FakeChromeRunner({"start": SIGNED_IN, "Registered Nurse": {"jobs": [card("7", "Registered Nurse")]}})
    stamp = tmp_path / "state/stamp"

    code = linkedin_search.main(dry_run=True, export="cards.json", chrome=Chrome(runner), stamp=stamp)

    assert code == 0 and stamp.exists()
    [(cards, dry_run)] = published
    assert dry_run is True and [c["job_id"] for c in cards] == ["7"]
    saved = json.loads((tmp_path / "cards.json").read_text(encoding="utf-8"))
    assert saved["jobs"][0]["job_url"] == "https://www.linkedin.com/jobs/view/7/"
    assert [c["job_id"] for c in linkedin_import.read_cards(tmp_path / "cards.json")] == ["7"]
    # A second run straight away is refused.
    assert linkedin_search.main(chrome=Chrome(runner), stamp=stamp) == 2
