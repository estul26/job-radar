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
    indeed_manifest: Path
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
            indeed_manifest=path("indeed_manifest_path", "reports/indeed-resume-manifest.json"),
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
    paths: Paths

    @property
    def vocab(self) -> Vocabulary:
        return Vocabulary.from_config(self.config)

    @property
    def timezone(self) -> ZoneInfo:
        return config_timezone(self.config)


def config_timezone(config: Mapping[str, Any]) -> ZoneInfo:
    """The `timezone` in search_config.yaml (an IANA name such as America/Toronto); UTC when unset."""
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
    config = load_yaml(config_path) or {}
    ranking = config.get("ranking") or {}
    return Settings(
        config=config,
        profile=load_json(profile_path),
        good_threshold=good_match_threshold(config, env),
        possible_threshold=int(ranking.get("possible_match_threshold", 55)),
        max_possible=int(ranking.get("max_possible_matches", 5)),
        paths=Paths.from_config(config.get("output") or {}),
    )
