from __future__ import annotations

import time
from typing import Any

import pandas as pd
from jobspy import scrape_jobs

from .normalize import normalize_dataframe, title_matches_exclusion


def filter_excluded_titles(jobs: list[dict[str, Any]], terms: list[str]) -> list[dict[str, Any]]:
    return [job for job in jobs if not title_matches_exclusion(str(job.get("title", "")), terms)]


def collect_jobs(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    search = config.get("search") or {}
    sites = search.get("sites") or []
    errors: list[str] = []
    frames: list[pd.DataFrame] = []

    queries = search.get("queries") or search.get("titles") or []

    for location in search.get("locations") or []:
        for query in queries:
            kwargs = dict(
                site_name=sites,
                search_term=query,
                location=location["query"],
                results_wanted=search.get("results_wanted_per_query", 20),
                hours_old=search.get("hours_old", 72),
                # The country Indeed and Glassdoor search; `radar doctor` checks it's set and supported.
                country_indeed=search.get("country_indeed") or None,
                verbose=0,
                fetch_description=search.get("fetch_description", False),
            )
            if "google" in sites:
                # Google Jobs takes one free-text search instead of separate fields.
                kwargs["google_search_term"] = f"{query} jobs near {location['query']}"
            if location.get("remote_only"):
                kwargs["is_remote"] = True
            if location.get("distance") is not None:
                # Search radius in miles; JobSpy's default of 50 reaches well past most cities.
                kwargs["distance"] = int(location["distance"])

            try:
                result = scrape_jobs(**kwargs)
                if result is not None and not result.empty:
                    frames.append(result)
            except Exception as exc:  # Network/job-board failures should not kill the whole morning run.
                errors.append(f"{query} @ {location['name']}: {type(exc).__name__}: {exc}")

            pause = float(search.get("pause_seconds_between_queries", 0))
            if pause > 0:
                time.sleep(pause)

    if not frames:
        return [], errors

    # A search can return a column that's empty in all its jobs (no salaries, say). pandas is changing how
    # concat types those, so drop them first: normalize_dataframe treats a missing column as empty anyway.
    combined = pd.concat([frame.dropna(axis=1, how="all") for frame in frames], ignore_index=True, sort=False)
    jobs = normalize_dataframe(combined)
    jobs = filter_excluded_titles(jobs, search.get("exclude_title_terms", []))
    return jobs, errors
