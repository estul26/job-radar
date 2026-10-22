import warnings

import pandas as pd

from job_radar import collector
from job_radar.collector import collect_jobs, filter_excluded_titles, title_matches_exclusion


def test_searches_with_empty_columns_combine_without_pandas_warnings(monkeypatch):
    # Like JobSpy: one search found no salaries or dates at all, another did.
    results = iter(
        [
            pd.DataFrame(
                {"title": ["Accountant"], "job_url": ["https://a"], "min_amount": [None], "date_posted": [None]}
            ),
            pd.DataFrame(
                {
                    "title": ["Financial Accountant"],
                    "job_url": ["https://b"],
                    "min_amount": [30000.0],
                    "date_posted": [pd.Timestamp("2026-10-20").date()],
                }
            ),
        ]
    )
    monkeypatch.setattr(collector, "scrape_jobs", lambda **kwargs: next(results))
    config = {
        "search": {
            "sites": ["indeed"],
            "titles": ["Accountant", "Financial Accountant"],
            "locations": [{"name": "London", "query": "London"}],
        }
    }

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        jobs, errors = collect_jobs(config)

    assert errors == []
    assert [(job["title"], job["min_amount"], job["date_posted"]) for job in jobs] == [
        ("Accountant", "", ""),
        ("Financial Accountant", "30000.0", "2026-10-20"),
    ]


def test_excluded_titles_are_dropped_before_scoring():
    terms = ["nursing assistant", "personal support worker", "veterinary"]
    jobs = [
        {"title": "Nursing Assistant - Casual"},
        {"title": "Personal Support Worker (Nights)"},
        {"title": "Veterinary Technician"},
        {"title": "Registered Nurse"},
        {"title": "Staff Nurse"},
    ]

    filtered = filter_excluded_titles(jobs, terms)
    assert [job["title"] for job in filtered] == ["Registered Nurse", "Staff Nurse"]


def test_exclusions_match_whole_words_only():
    assert title_matches_exclusion("Nurse - Aiden Health", ["aide"]) is False
    assert title_matches_exclusion("Nurse Aide", ["aide"]) is True
