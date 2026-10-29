"""Configuration: config/search_config.yaml, config/resume_profile.json and environment overrides."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .matcher import Vocabulary

DEFAULT_CONFIG = "config/search_config.yaml"
DEFAULT_PROFILE = "config/resume_profile.json"
DEFAULT_MASTER_RESUME = "resumes/master_resume.json"


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Settings that are lists. Written on one line ("titles: Accountant"), YAML reads a single string,
# which would otherwise be searched and matched letter by letter.
LIST_SETTINGS = {
    "search": ("sites", "queries", "titles", "exclude_title_terms"),
    "ranking": ("hard_reject_title_terms",),
    "matching": ("soft_skills", "related_title_keywords", "context_title_keywords", "context_words"),
}
# Settings that map each name to its phrases ("excel: [excel, spreadsheets]"). Written as a list
# ("- excel"), like the settings above, each item is a name looked for as itself.
NAMED_SETTINGS = ("skills", "certifications")
SECTIONS = ("search", "ranking", "matching", "output")


def as_list(value: Any) -> Any:
    """A list setting as a list: nothing is [], one string is a list of it. Other shapes are left for doctor."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return value


def as_named(value: Any) -> Any:
    """A name -> phrases setting as a mapping, from a mapping, a list of names, or one name."""
    if value is None:
        return {}
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return value
    named: dict[str, Any] = {}
    for item in value:
        if isinstance(item, Mapping):  # "- excel: [excel, spreadsheets]"
            named.update({str(name): phrases for name, phrases in item.items()})
        elif str(item or "").strip():
            named[str(item).strip()] = []
    return named


def normalize_config(config: Any) -> dict[str, Any]:
    """search_config.yaml as the code reads it, forgiving the shapes people write by hand.

    Missing sections are empty, one-line lists become lists, skills and certifications written as a
    list become a mapping, and a single location written without its "- " becomes a list of one.
    `radar doctor` names anything still in a shape the radar can't use.
    """
    config = dict(config) if isinstance(config, Mapping) else {}
    for section in SECTIONS:
        config[section] = dict(config[section]) if isinstance(config.get(section), Mapping) else {}
    for section, keys in LIST_SETTINGS.items():
        for key in keys:
            if key in config[section]:
                config[section][key] = as_list(config[section][key])
    for key in NAMED_SETTINGS:
        if key in config["matching"]:
            config["matching"][key] = as_named(config["matching"][key])
    locations = config["search"].get("locations")
    config["search"]["locations"] = [locations] if isinstance(locations, Mapping) else as_list(locations)
    return config


def normalize_profile(profile: Any) -> dict[str, Any]:
    """resume_profile.json with its skills and certifications as lists, even when one is a plain string."""
    profile = dict(profile) if isinstance(profile, Mapping) else {}
    for key in ("skills", "certifications"):
        if key in profile:
            profile[key] = as_list(profile[key])
    return profile


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    return normalize_config(load_yaml(path))


@dataclass(frozen=True)
class Paths:
    """Where state, reports and résumés live, relative to the repository root."""

    report: Path
    latest_jobs: Path
    seen_jobs: Path
    # Exported from the job Issues by `radar export`; the Issues are the source of truth.
    applications: Path
    # Hand-offs between `radar scan` and `radar publish-scan` (not committed).
    scan_matches: Path
    resume_manifest: Path
    resume_dir: Path
    resume_index: Path
    master_resume: Path
    # Hand-off from `radar issue` (before the commit) to `radar issue --publish` (after it).
    pending_resume: Path

    @classmethod
    def from_config(cls, output: Mapping[str, str]) -> Paths:
        def path(key: str, default: str) -> Path:
            return Path(output.get(key) or default)

        return cls(
            report=path("report_path", "reports/latest.md"),
            latest_jobs=path("latest_jobs_path", "data/latest_jobs.csv"),
            seen_jobs=path("seen_jobs_path", "data/seen_jobs.json"),
            applications=path("applications_path", "data/applications.csv"),
            scan_matches=path("scan_matches_path", "reports/scan-matches.json"),
            resume_manifest=path("resume_manifest_path", "reports/scan-resume-manifest.json"),
            resume_dir=path("resume_dir", "resumes/jobs"),
            resume_index=path("resume_index_path", "resumes/index.csv"),
            master_resume=path("master_resume_path", DEFAULT_MASTER_RESUME),
            pending_resume=path("pending_resume_path", "reports/resume-generation.json"),
        )


@dataclass(frozen=True)
class Settings:
    config: dict[str, Any]
    profile: dict[str, Any]
    good_threshold: int
    possible_threshold: int
    max_possible: int
    # Good matches that get an Issue per scan; 0 means no limit.
    max_good: int
    paths: Paths

    @property
    def vocab(self) -> Vocabulary:
        return Vocabulary.from_config(self.config)

    @property
    def timezone(self) -> ZoneInfo:
        return config_timezone(self.config)


def config_timezone(config: Mapping[str, Any]) -> ZoneInfo:
    """The `timezone` in search_config.yaml (an IANA name such as Europe/London); UTC when unset."""
    return ZoneInfo(str(config.get("timezone") or "UTC").strip())


def good_match_threshold(config: Mapping[str, Any], env: Mapping[str, str] = os.environ) -> int:
    """The GOOD_MATCH_THRESHOLD repository variable overrides ranking.good_match_threshold."""
    override = str(env.get("GOOD_MATCH_THRESHOLD", "")).strip()
    if override:
        return int(override)
    return int(config.get("ranking", {}).get("good_match_threshold", 65))


def load_settings(
    config_path: str | Path = DEFAULT_CONFIG,
    profile_path: str | Path = DEFAULT_PROFILE,
    env: Mapping[str, str] = os.environ,
) -> Settings:
    config = load_config(config_path)
    ranking = config["ranking"]
    return Settings(
        config=config,
        profile=normalize_profile(load_json(profile_path)),
        good_threshold=good_match_threshold(config, env),
        possible_threshold=int(ranking.get("possible_match_threshold", 55)),
        max_possible=int(ranking.get("max_possible_matches", 5)),
        max_good=int(ranking.get("max_good_matches", 10)),
        paths=Paths.from_config(config["output"]),
    )
