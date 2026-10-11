"""GitHub access for the workflows: one thin wrapper over the gh CLI.

Everything the workflows used to do with gh and jq in bash goes through here, so
the decisions around it are plain Python and can be tested with a fake
(tests/fake_github.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable
from typing import Any

from .labels import LABELS

# gh paginates up to this many Issues; far more than this repository will hold.
ISSUE_LIMIT = "5000"
ISSUE_FIELDS = "number,title,body,labels,state,url"


class GitHubError(RuntimeError):
    pass


def _gh(args: list[str], *, input_text: str | None = None) -> str:
    proc = subprocess.run(["gh", *args], text=True, capture_output=True, input=input_text)
    if proc.returncode != 0:
        raise GitHubError((proc.stderr or proc.stdout or "").strip() or f"gh {' '.join(args)} failed")
    return proc.stdout.strip()


def label_names(issue: dict[str, Any]) -> set[str]:
    return {label["name"] if isinstance(label, dict) else str(label) for label in issue.get("labels") or []}


class GitHub:
    def __init__(self, repo: str = "") -> None:
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
        if not self.repo:
            raise GitHubError("GITHUB_REPOSITORY is not set.")

    @property
    def owner(self) -> str:
        return self.repo.split("/", 1)[0]

    def issue(self, number: int) -> dict[str, Any]:
        return json.loads(_gh(["issue", "view", str(number), "--repo", self.repo, "--json", ISSUE_FIELDS]))

    def issues(self, fields: str = ISSUE_FIELDS) -> list[dict[str, Any]]:
        args = ["issue", "list", "--repo", self.repo, "--state", "all", "--limit", ISSUE_LIMIT, "--json", fields]
        return json.loads(_gh(args) or "[]")

    def create_issue(self, title: str, body: str, *, labels: Iterable[str] = (), assignee: str = "") -> int:
        args = ["issue", "create", "--repo", self.repo, "--title", title, "--body-file", "-"]
        for label in labels:
            args += ["--label", label]
        if assignee:
            args += ["--assignee", assignee]
        url = _gh(args, input_text=body)
        match = re.search(r"/issues/(\d+)", url)
        if not match:
            raise GitHubError(f"Could not read the new Issue number from: {url}")
        return int(match.group(1))

    def edit_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        add_labels: Iterable[str] = (),
        remove_labels: Iterable[str] = (),
    ) -> None:
        args = ["issue", "edit", str(number), "--repo", self.repo]
        if title is not None:
            args += ["--title", title]
        if body is not None:
            args += ["--body-file", "-"]
        for label in add_labels:
            args += ["--add-label", label]
        for label in remove_labels:
            args += ["--remove-label", label]
        if len(args) > 5:
            _gh(args, input_text=body)

    def close(self, number: int, comment: str = "") -> None:
        args = ["issue", "close", str(number), "--repo", self.repo]
        if comment:
            args += ["--comment", comment]
        _gh(args)

    def reopen(self, number: int) -> None:
        _gh(["issue", "reopen", str(number), "--repo", self.repo])

    def comment(self, number: int, body: str) -> None:
        _gh(["issue", "comment", str(number), "--repo", self.repo, "--body-file", "-"], input_text=body)

    def upsert_comment(self, number: int, marker: str, body: str) -> None:
        """Keep exactly one comment carrying marker: create it, or edit it when the text changed."""
        text = body if marker in body else f"{marker}\n{body}"
        pages = json.loads(
            _gh(["api", "--paginate", "--slurp", f"repos/{self.repo}/issues/{number}/comments?per_page=100"]) or "[]"
        )
        existing = next((c for page in pages for c in page if marker in (c.get("body") or "")), None)
        if existing is None:
            self.comment(number, text)
        elif existing.get("body") != text:
            _gh(
                ["api", "--method", "PATCH", f"repos/{self.repo}/issues/comments/{existing['id']}", "--input", "-"],
                input_text=json.dumps({"body": text}),
            )

    def ensure_labels(self, names: Iterable[str]) -> None:
        """Create any of the named labels (from labels.LABELS) the repository lacks."""
        listed = json.loads(_gh(["label", "list", "--repo", self.repo, "--limit", "500", "--json", "name"]) or "[]")
        existing = {label["name"] for label in listed}
        for name in names:
            if name not in existing:
                color, description = LABELS[name]
                _gh(["label", "create", name, "--repo", self.repo, "--color", color, "--description", description])
