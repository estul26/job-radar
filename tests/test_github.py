"""The gh wrapper itself, against a stand-in for the gh command."""

import json

import pytest

from job_radar import github
from job_radar.commands.scan import HAND_LABELS, MATCH_LABELS
from job_radar.github import GitHub, GitHubError


class FakeGhCommand:
    """Labels as the gh CLI sees them: `label create` fails for a name that exists, in any case."""

    def __init__(self, labels=(), created_elsewhere=()):
        self.labels = list(labels)
        # Labels another workflow creates between our `label list` and our `label create`.
        self.created_elsewhere = set(created_elsewhere)
        self.created = []

    def __call__(self, args, *, input_text=None):
        if args[:2] == ["label", "list"]:
            listed = [{"name": name} for name in self.labels]
            self.labels += sorted(self.created_elsewhere)
            return json.dumps(listed)
        if args[:2] == ["label", "create"]:
            name = args[2]
            if name.lower() in {label.lower() for label in self.labels}:
                raise GitHubError(f'label with name "{name}" already exists; use `--force` to update its color')
            self.labels.append(name)
            self.created.append(name)
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


def test_a_new_repository_gets_each_label_once(monkeypatch):
    # The first scan in a new copy names status:new twice (a match label and a hand label).
    gh = FakeGhCommand(labels=["bug", "documentation"])
    monkeypatch.setattr(github, "_gh", gh)
    names = ["source:indeed", *MATCH_LABELS, *HAND_LABELS]
    assert names.count("status:new") == 2

    GitHub("me/repo").ensure_labels(names)

    assert sorted(gh.created) == sorted(set(names))


def test_labels_that_exist_in_any_case_or_appear_meanwhile_are_left_alone(monkeypatch):
    gh = FakeGhCommand(labels=["Status:New"], created_elsewhere=["resume:ready"])
    monkeypatch.setattr(github, "_gh", gh)

    GitHub("me/repo").ensure_labels(["status:new", "resume:ready", "match:good"])

    assert gh.created == ["match:good"]


def test_other_label_errors_still_fail(monkeypatch):
    def broken(args, *, input_text=None):
        if args[:2] == ["label", "list"]:
            return "[]"
        raise GitHubError("HTTP 403: Resource not accessible by integration")

    monkeypatch.setattr(github, "_gh", broken)
    with pytest.raises(GitHubError, match="403"):
        GitHub("me/repo").ensure_labels(["match:good"])
