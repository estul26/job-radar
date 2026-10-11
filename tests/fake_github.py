"""In-memory stand-in for job_radar.github.GitHub."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any


class FakeGitHub:
    repo = "owner/repo"
    owner = "owner"

    def __init__(self, issues: Iterable[dict[str, Any]] = (), labels: Iterable[str] = ()) -> None:
        self.labels = set(labels)
        self._issues: dict[int, dict[str, Any]] = {}
        for issue in issues:
            self._issues[issue["number"]] = {
                "title": "",
                "body": "",
                "state": "OPEN",
                "assignee": "",
                **issue,
                "labels": set(issue.get("labels", ())),
                "comments": list(issue.get("comments", ())),
            }

    def _view(self, number: int) -> dict[str, Any]:
        issue = copy.deepcopy(self._issues[number])
        issue["labels"] = [{"name": name} for name in sorted(issue["labels"])]
        issue["comments"] = [{"body": body} for body in issue["comments"]]
        issue["url"] = f"https://github.com/{self.repo}/issues/{number}"
        return issue

    def issue(self, number: int) -> dict[str, Any]:
        return self._view(number)

    def issues(self, fields: str = "") -> list[dict[str, Any]]:
        return [self._view(number) for number in sorted(self._issues, reverse=True)]

    def create_issue(self, title: str, body: str, *, labels: Iterable[str] = (), assignee: str = "") -> int:
        number = max(self._issues, default=0) + 1
        self._issues[number] = {
            "number": number,
            "title": title,
            "body": body,
            "state": "OPEN",
            "labels": set(labels),
            "comments": [],
            "assignee": assignee,
        }
        return number

    def edit_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        add_labels: Iterable[str] = (),
        remove_labels: Iterable[str] = (),
    ) -> None:
        issue = self._issues[number]
        if title is not None:
            issue["title"] = title
        if body is not None:
            issue["body"] = body
        issue["labels"] -= set(remove_labels)
        issue["labels"] |= set(add_labels)

    def close(self, number: int, comment: str = "") -> None:
        if comment:
            self.comment(number, comment)
        self._issues[number]["state"] = "CLOSED"

    def reopen(self, number: int) -> None:
        self._issues[number]["state"] = "OPEN"

    def comment(self, number: int, body: str) -> None:
        self._issues[number]["comments"].append(body)

    def upsert_comment(self, number: int, marker: str, body: str) -> None:
        text = body if marker in body else f"{marker}\n{body}"
        comments = self._issues[number]["comments"]
        for index, existing in enumerate(comments):
            if marker in existing:
                comments[index] = text
                return
        comments.append(text)

    def ensure_labels(self, names: Iterable[str]) -> None:
        self.labels |= set(names)

    # Test helpers
    def labels_of(self, number: int) -> set[str]:
        return set(self._issues[number]["labels"])

    def state_of(self, number: int) -> str:
        return self._issues[number]["state"]

    def comments_of(self, number: int) -> list[str]:
        return list(self._issues[number]["comments"])
