"""`radar doctor`: is this copy set up for you? Lists what to fill in, file by file.

Problems stop the scheduled scan (daily-jobs.yml skips it until they are fixed);
warnings don't. An unfinished master résumé is a warning: jobs are still found
and scored, but no résumé is generated (resume_ready() gates that).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from ..settings import DEFAULT_CONFIG, DEFAULT_MASTER_RESUME, DEFAULT_PROFILE


@dataclass
class Checkup:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def resume_problems(master: dict[str, Any]) -> list[str]:
    """What the master résumé still needs before résumés can be generated from it."""
    identity = master.get("identity") or {}
    summary = master.get("summary") or {}
    missing = [
        label
        for label, value in (
            ("identity.name", identity.get("name")),
            ("identity.email", identity.get("email")),
            ("summary.experience", summary.get("experience")),
        )
        if not str(value or "").strip()
    ]
    problems = [f"{label} is empty" for label in missing]
    if not master.get("experience") and not master.get("education"):
        problems.append("add at least one experience or education entry")
    return problems


def resume_ready(master: dict[str, Any]) -> bool:
    return not resume_problems(master)


def _load(path: Path, loader: Any, checkup: Checkup) -> dict[str, Any] | None:
    if not path.exists():
        checkup.problems.append(f"{path}: file not found")
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            data = loader(handle)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        checkup.problems.append(f"{path}: can't be read ({exc})")
        return None
    if not isinstance(data, dict):
        checkup.problems.append(f"{path}: is empty or isn't a mapping")
        return None
    return data


def check_config(config: dict[str, Any], path: Path, checkup: Checkup) -> None:
    def problem(message: str) -> None:
        checkup.problems.append(f"{path}: {message}")

    def warn(message: str) -> None:
        checkup.warnings.append(f"{path}: {message}")

    timezone = str(config.get("timezone") or "").strip()
    if not timezone:
        warn("timezone is not set, so dates use UTC (set it to e.g. Europe/London, Asia/Kolkata or America/Chicago)")
    else:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            problem(f"timezone '{timezone}' is not an IANA timezone name such as Europe/London or Asia/Kolkata")

    search = config.get("search") or {}
    sites = [str(site).strip().lower() for site in search.get("sites") or []]
    if not sites:
        problem("search.sites is empty: use [indeed], or a job board for your region (docs/configure.md)")
    check_sites(sites, str(search.get("country_indeed") or "").strip(), problem, warn)
    if not search.get("titles"):
        problem("search.titles is empty: list the job titles you want, e.g. Accountant or Registered Nurse")
    locations = search.get("locations") or []
    if not locations:
        problem("search.locations is empty: add where you want to work (and a remote entry if you want remote)")
    for index, place in enumerate(locations):
        if not isinstance(place, dict) or not str(place.get("name") or "").strip():
            problem(f"search.locations[{index}] needs a name")
        elif not str(place.get("query") or "").strip():
            problem(
                f"search.locations[{index}] ({place['name']}) needs a query: "
                "what you'd type in the job board's location box"
            )

    matching = config.get("matching") or {}
    if not matching.get("skills"):
        warn(
            "matching.skills is empty, so postings' skill requirements aren't detected and every job gets the "
            "same skill points"
        )


def check_sites(sites: list[str], country: str, problem: Any, warn: Any) -> None:
    """The job boards JobSpy knows, and the country Indeed and Glassdoor need."""
    try:
        from jobspy.model import Country, Site
    except ImportError:  # radar doctor before `pip install`: skip what needs JobSpy.
        known, check_country = None, None
    else:
        known, check_country = {site.value for site in Site}, Country.from_string
    for site in sites:
        if known is not None and site not in known:
            problem(f"search.sites: '{site}' isn't a job board JobSpy knows ({', '.join(sorted(known))})")
    if {"indeed", "glassdoor"} & set(sites):
        if not country:
            problem("search.country_indeed is empty: the country Indeed searches, e.g. Germany, India, UK or USA")
        elif check_country is not None:
            try:
                found = check_country(country)
            except ValueError:
                problem(
                    f"search.country_indeed: Indeed doesn't support '{country}' (docs/configure.md lists the countries)"
                )
            else:
                if "glassdoor" in sites and len(found.value) < 3:
                    warn(f"search.sites: Glassdoor doesn't cover {country}, so only the other boards are searched")
    if "linkedin" in sites:
        warn(
            "search.sites: LinkedIn blocks searches from GitHub's servers and its terms forbid scraping; use its "
            "alert emails or radar linkedin-search instead (docs/linkedin.md)"
        )
    if "zip_recruiter" in sites:
        warn("search.sites: ZipRecruiter (USA and Canada only) usually blocks GitHub's servers")


def check_profile(profile: dict[str, Any], config: dict[str, Any], path: Path, checkup: Checkup) -> None:
    if not isinstance(profile.get("experience_years"), int):
        checkup.problems.append(f"{path}: experience_years must be a whole number of years in your field")
    skills = [str(skill) for skill in profile.get("skills") or []]
    if not skills:
        checkup.warnings.append(f"{path}: skills is empty, so no posting's skills will match yours")
    known = {str(name).lower() for name in ((config.get("matching") or {}).get("skills") or {})}
    unknown = sorted(skill for skill in skills if skill.lower() not in known)
    if known and unknown:
        checkup.warnings.append(
            f"{path}: these skills aren't in matching.skills, so they can never match a posting: {', '.join(unknown)}"
        )


def setup_problems(config: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    """What stops scoring, for loaded settings: empty until config/ is filled in."""
    result = Checkup()
    check_config(config, Path(DEFAULT_CONFIG), result)
    check_profile(profile, config, Path(DEFAULT_PROFILE), result)
    return result.problems


def checkup(
    config_path: str | Path = DEFAULT_CONFIG,
    profile_path: str | Path = DEFAULT_PROFILE,
    master_path: str | Path = DEFAULT_MASTER_RESUME,
) -> Checkup:
    result = Checkup()
    config_path, profile_path, master_path = Path(config_path), Path(profile_path), Path(master_path)

    config = _load(config_path, yaml.safe_load, result)
    if config is not None:
        check_config(config, config_path, result)
    profile = _load(profile_path, json.load, result)
    if profile is not None:
        check_profile(profile, config or {}, profile_path, result)
    master = _load(master_path, json.load, result)
    if master is not None:
        for problem in resume_problems(master):
            result.warnings.append(f"{master_path}: {problem} (no résumés until it's filled in)")
    return result


def render(result: Checkup) -> str:
    if result.ok and not result.warnings:
        return "radar doctor: everything is set up."
    lines = [f"radar doctor: {len(result.problems)} problem(s), {len(result.warnings)} warning(s)."]
    if result.problems:
        lines += ["", "Problems (the scheduled scan is skipped until these are fixed):"]
        lines += [f"  ✗ {item}" for item in result.problems]
    if result.warnings:
        lines += ["", "Warnings:"]
        lines += [f"  ! {item}" for item in result.warnings]
    lines += ["", "See docs/configure.md for what each setting means."]
    return "\n".join(lines)
