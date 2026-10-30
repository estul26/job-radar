"""`radar doctor`: is this copy set up for you? Lists what to fill in, file by file.

Problems stop the scheduled scan (daily-jobs.yml skips it until they are fixed);
warnings don't. An unfinished master résumé is a warning: jobs are still found
and scored, but no résumé is generated (resume_ready() gates that).

Problems exit with NOT_SET_UP rather than 1, which is also what a crash exits with,
so daily-jobs.yml can skip the scan for an unfinished setup but fail the run for a bug.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from ..settings import (
    DEFAULT_CONFIG,
    DEFAULT_MASTER_RESUME,
    DEFAULT_PROFILE,
    LIST_SETTINGS,
    NAMED_SETTINGS,
    normalize_config,
    normalize_profile,
)

NOT_SET_UP = 3


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

    config = normalize_config(config)
    for section, keys in LIST_SETTINGS.items():
        for key in keys:
            if not isinstance(config[section].get(key, []), list):
                problem(f"{section}.{key} must be a list: one entry per line, each starting with '- '")
    for key in NAMED_SETTINGS:
        if not isinstance(config["matching"].get(key, {}), dict):
            problem(
                f"matching.{key} must list names with their phrases, one per line, e.g. `excel: [excel, spreadsheets]`"
            )

    timezone = str(config.get("timezone") or "").strip()
    if not timezone:
        warn("timezone is not set, so dates use UTC (set it to e.g. Europe/London, Asia/Kolkata or America/Chicago)")
    else:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            problem(f"timezone '{timezone}' is not an IANA timezone name such as Europe/London or Asia/Kolkata")

    search = config["search"]
    listed_sites = search.get("sites") if isinstance(search.get("sites"), list) else []
    sites = [str(site).strip().lower() for site in listed_sites]
    if not sites:
        problem("search.sites is empty: use [indeed], or a job board for your region (docs/configure.md)")
    check_sites(sites, str(search.get("country_indeed") or "").strip(), problem, warn)
    if not search.get("titles"):
        problem("search.titles is empty: list the job titles you want, e.g. Accountant or Registered Nurse")
    locations = search.get("locations") or []
    if not isinstance(locations, list):
        problem("search.locations must be a list of places, each starting with '- name:'")
        locations = []
    elif not locations:
        problem("search.locations is empty: add where you want to work (and a remote entry if you want remote)")
    for index, place in enumerate(locations):
        if not isinstance(place, dict) or not str(place.get("name") or "").strip():
            problem(f"search.locations[{index}] needs a name")
        elif not str(place.get("query") or "").strip():
            problem(
                f"search.locations[{index}] ({place['name']}) needs a query: "
                "what you'd type in the job board's location box"
            )
        elif place.get("distance") is not None and (
            isinstance(place["distance"], bool) or not isinstance(place["distance"], int) or place["distance"] < 1
        ):
            problem(f"search.locations[{index}] ({place['name']}): distance must be a whole number of miles, e.g. 15")

    matching = config["matching"]
    if not matching.get("skills"):
        warn(
            "matching.skills is empty, so postings' skill requirements aren't detected and every job gets the "
            "same skill points"
        )


def check_sites(sites: list[str], country: str, problem: Any, warn: Any) -> None:
    """The job boards JobSpy knows, and the country Indeed and Glassdoor need."""
    try:
        from jobspy.glassdoor.constant import domains
        from jobspy.model import Country, Site
    except ImportError:  # radar doctor before `pip install`: skip what needs JobSpy.
        known, check_country, glassdoor = None, None, set()
    else:
        # Country() takes a name or an alias (United Kingdom, US, UAE) in any case, and raises ValueError for a
        # country Indeed doesn't cover; Glassdoor covers the countries it has a domain for.
        known, check_country, glassdoor = {site.value for site in Site}, Country, set(domains)
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
                if "glassdoor" in sites and found not in glassdoor:
                    warn(f"search.sites: Glassdoor doesn't cover {country}, so only the other boards are searched")
    if "linkedin" in sites:
        warn(
            "search.sites: LinkedIn blocks searches from GitHub's servers and its terms forbid scraping; use its "
            "alert emails or radar linkedin-search instead (docs/linkedin.md)"
        )
    if "zip_recruiter" in sites:
        warn("search.sites: ZipRecruiter (USA and Canada only) usually blocks GitHub's servers")


def check_profile(profile: dict[str, Any], config: dict[str, Any], path: Path, checkup: Checkup) -> None:
    profile, config = normalize_profile(profile), normalize_config(config)
    if not isinstance(profile.get("experience_years"), int) or isinstance(profile.get("experience_years"), bool):
        checkup.problems.append(f"{path}: experience_years must be a whole number of years in your field")
    for key in ("skills", "certifications"):
        if not isinstance(profile.get(key, []), list):
            checkup.problems.append(f'{path}: {key} must be a list in square brackets, e.g. ["excel", "xero"]')
            profile[key] = []
    skills = [str(skill) for skill in profile.get("skills") or []]
    if not skills:
        checkup.warnings.append(f"{path}: skills is empty, so no posting's skills will match yours")
    named_skills = config["matching"].get("skills")
    known = {str(name).lower() for name in named_skills} if isinstance(named_skills, dict) else set()
    unknown = sorted(skill for skill in skills if skill.lower() not in known)
    if known and unknown:
        checkup.warnings.append(
            f"{path}: these skills aren't in matching.skills, so they can never match a posting: {', '.join(unknown)}"
        )


def resume_tags(master: dict[str, Any]) -> set[str]:
    """The tags on the résumé lines that show a skill: summary, skills, experience and education bullets."""
    tags: set[str] = set()

    def add(items: Any) -> None:
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("tags"), list):
                tags.update(str(tag).strip().lower() for tag in item["tags"])

    summary = master.get("summary")
    add(summary.get("capabilities") if isinstance(summary, dict) else None)
    add(master.get("technical_skills"))
    for section in ("experience", "education"):
        for entry in master.get(section) if isinstance(master.get(section), list) else []:
            if isinstance(entry, dict):
                add(entry.get("bullets"))
    return tags


def check_resume_matches_profile(
    master: dict[str, Any],
    profile: dict[str, Any],
    config: dict[str, Any],
    master_path: Path,
    profile_path: Path,
    checkup: Checkup,
) -> None:
    """The skills your résumé shows and the skills scoring counts as yours should be the same list.

    A skill tagged on the résumé but missing from resume_profile.json is reported as missing on every
    posting that asks for it; one listed there but tagged nowhere scores as matched with nothing on the
    résumé to show it. Only names from matching.skills count, and soft skills only the first way round.
    """
    config, profile = normalize_config(config), normalize_profile(profile)
    named = config["matching"].get("skills")
    if not isinstance(named, dict) or not named or not isinstance(profile.get("skills"), list):
        return
    if not resume_ready(master):
        return
    known = {str(name).strip().lower() for name in named}
    soft = {str(skill).strip().lower() for skill in config["matching"].get("soft_skills") or []}
    listed = {str(skill).strip().lower() for skill in profile["skills"]}
    tagged = resume_tags(master) & known

    unlisted = sorted(tagged - listed)
    if unlisted:
        checkup.warnings.append(
            f"{profile_path}: your résumé is tagged with these skills but skills doesn't list them, so postings "
            f"that ask for them count them as missing: {', '.join(unlisted)}"
        )
    untagged = sorted((listed & known) - tagged - soft)
    if untagged:
        checkup.warnings.append(
            f"{master_path}: no line is tagged with these skills from {profile_path.name}, so a posting can "
            f"score them as matched while your résumé doesn't show them: {', '.join(untagged)} (tag a line "
            "that shows each one, or remove it from skills)"
        )


def check_workflow_timezones(config: dict[str, Any], config_path: Path, checkup: Checkup) -> None:
    """Every schedule's `timezone:` should be the timezone in search_config.yaml, which dates use."""
    timezone = str(normalize_config(config).get("timezone") or "").strip()
    workflows = config_path.resolve().parent.parent / ".github" / "workflows"
    if not timezone or not workflows.is_dir():
        return
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if not isinstance(workflow, dict):
            continue
        # YAML 1.1 reads the key `on` as true.
        triggers = workflow.get("on", workflow.get(True))
        schedules = triggers.get("schedule") if isinstance(triggers, dict) else None
        if not isinstance(schedules, list):
            continue
        zones = {
            str(entry["timezone"]).strip() for entry in schedules if isinstance(entry, dict) and entry.get("timezone")
        }
        others = sorted(zones - {timezone})
        if others:
            checkup.warnings.append(
                f".github/workflows/{path.name}: its schedule runs on {', '.join(others)} time, but "
                f"{config_path} sets timezone to {timezone}; set every `timezone:` line in it to {timezone}"
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
        check_workflow_timezones(config, config_path, result)
    profile = _load(profile_path, json.load, result)
    if profile is not None:
        check_profile(profile, config or {}, profile_path, result)
    master = _load(master_path, json.load, result)
    if master is not None:
        for problem in resume_problems(master):
            result.warnings.append(f"{master_path}: {problem} (no résumés until it's filled in)")
        if config is not None and profile is not None:
            check_resume_matches_profile(master, profile, config, master_path, profile_path, result)
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
