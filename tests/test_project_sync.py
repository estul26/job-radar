import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_radar.labels import LABELS, STATUSES


def _load_sync_module():
    path = Path("tools/project_sync.py")
    spec = importlib.util.spec_from_file_location("project_sync", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_sync_module()
URL = "https://github.com/o/r/issues/1"
FIELDS = {
    "Application Status": {
        "id": "F_status",
        "dataType": "SINGLE_SELECT",
        "options": [{"id": f"opt_{s}", "name": s} for s in sync.STATUS_VALUES.values()],
    },
    "Source": {
        "id": "F_source",
        "dataType": "SINGLE_SELECT",
        "options": [{"id": "opt_li", "name": "LinkedIn"}, {"id": "opt_in", "name": "Indeed"}],
    },
    "Company": {"id": "F_company", "dataType": "TEXT"},
    "Location": {"id": "F_location", "dataType": "TEXT"},
    "Job URL": {"id": "F_url", "dataType": "TEXT"},
    "Date Found": {"id": "F_date", "dataType": "DATE"},
    "Match Score": {"id": "F_score", "dataType": "NUMBER"},
}
BODY = (
    "### LinkedIn job URL\n\nhttps://www.linkedin.com/jobs/view/1/\n\n"
    "### Company\n\nAcme\n\n### Location\n\nToronto, ON\n"
)


def test_label_change_reaches_the_board_instead_of_being_reverted():
    assert sync.sync_direction(board="New", label="Applied", last_synced="New") == "issue_to_board"


def test_dragging_a_card_moves_the_label():
    assert sync.sync_direction(board="Interview", label="Applied", last_synced="Applied") == "board_to_issue"


def test_first_sync_and_conflicting_edits_keep_the_label():
    assert sync.sync_direction(board="Saved", label="Applied", last_synced="") == "issue_to_board"
    assert sync.sync_direction(board="Offer", label="Rejected", last_synced="Interview") == "issue_to_board"


def test_an_empty_side_is_filled_from_the_other():
    assert sync.sync_direction(board="", label="New", last_synced="") == "issue_to_board"
    assert sync.sync_direction(board="Saved", label="", last_synced="") == "board_to_issue"
    assert sync.sync_direction(board="New", label="New", last_synced="") == ""


def test_newly_added_status_label_wins_while_two_are_present():
    issue = {"labels": [{"name": "status:new"}, {"name": "status:applied"}]}
    assert sync.label_status(issue, last_synced="New") == "Applied"
    assert sync.label_status(issue, last_synced="Applied") == "New"


def test_sync_state_round_trip(tmp_path):
    path = tmp_path / "nested" / "state.json"
    sync.save_sync_state(path, {"synced": {URL: "Applied"}, "retry_after": ""})
    assert sync.load_sync_state(path) == {"synced": {URL: "Applied"}, "retry_after": ""}
    assert sync.load_sync_state(tmp_path / "missing.json") == {"synced": {}, "retry_after": ""}


def test_field_values_match_each_field_type():
    assert sync.field_value(FIELDS["Application Status"], "applied") == {"singleSelectOptionId": "opt_Applied"}
    assert sync.field_value(FIELDS["Application Status"], "Unknown") is None
    assert sync.field_value(FIELDS["Match Score"], "72") == {"number": 72.0}
    assert sync.field_value(FIELDS["Date Found"], "2026-10-05") == {"date": "2026-10-05"}
    assert sync.field_value(FIELDS["Company"], "Acme") == {"text": "Acme"}


def test_item_fields_are_written_in_one_mutation(monkeypatch):
    requests = []
    monkeypatch.setattr(sync, "graphql", lambda query, variables: requests.append((query, variables)) or {})
    sync.set_item_fields("P", "I", FIELDS, {"Company": "Acme", "Match Score": "72", "Location": ""})
    assert len(requests) == 1
    query, variables = requests[0]
    assert query.count("updateProjectV2ItemFieldValue") == 2
    assert variables["value0"] == {"text": "Acme"} and variables["value1"] == {"number": 72.0}


class FakeGitHub:
    """Stands in for the gh calls the sync makes."""

    def __init__(self, monkeypatch, *, issues, items):
        self.issues = issues
        self.items = items
        self.label_edits: list[list[str]] = []
        self.field_writes: list[tuple[str, dict]] = []
        self.added: list[str] = []
        monkeypatch.setattr(sync, "WRITE_PAUSE_SECONDS", 0)
        monkeypatch.setattr(sync, "repository_issues", lambda: self.issues)
        monkeypatch.setattr(sync, "load_board", lambda: ("P", FIELDS, {u: dict(i) for u, i in self.items.items()}))
        monkeypatch.setattr(sync, "graphql", self.graphql)
        monkeypatch.setattr(sync, "run", self.run)
        monkeypatch.setattr(sync, "run_json", lambda args, **kw: {"comments": [{"body": "## 72% — Registered Nurse"}]})

    def graphql(self, query, variables):
        if "addProjectV2ItemById" in query:
            self.added.append(variables["content"])
            return {"addProjectV2ItemById": {"item": {"id": f"item-{variables['content']}"}}}
        values = {k: v for k, v in variables.items() if k.startswith("value")}
        self.field_writes.append((variables["item"], values))
        return {}

    def run(self, args, check=True, input_text=None):
        self.label_edits.append(args)
        return ""


def _issue(number=1, labels=("status:applied",)):
    return {
        "id": f"I_{number}",
        "number": number,
        "title": "[LinkedIn Job] Registered Nurse — Acme",
        "url": f"https://github.com/o/r/issues/{number}",
        "body": BODY,
        "labels": [{"name": name} for name in labels],
        "createdAt": "2026-10-05T10:00:00Z",
    }


def test_label_change_is_pushed_to_the_board(monkeypatch):
    fake = FakeGitHub(
        monkeypatch, issues=[_issue()], items={URL: {"id": "item1", "status": "New", "source": "LinkedIn"}}
    )
    state = {"synced": {URL: "New"}, "retry_after": ""}
    counts = sync.sync(state)
    assert counts["issue_to_board"] == 1
    assert fake.field_writes == [("item1", {"value0": {"singleSelectOptionId": "opt_Applied"}})]
    assert state["synced"][URL] == "Applied"


def test_dragged_card_moves_the_label_and_is_not_reverted_by_the_backfill(monkeypatch):
    # The card has no details yet, so step 2 also writes to it; it must not
    # put the old label status back after step 1 moved the label.
    fake = FakeGitHub(monkeypatch, issues=[_issue()], items={URL: {"id": "item1", "status": "Interview", "source": ""}})
    state = {"synced": {URL: "Applied"}, "retry_after": ""}
    counts = sync.sync(state)
    assert counts["board_to_issue"] == 1
    assert fake.label_edits[0][-4:] == ["--remove-label", "status:applied", "--add-label", "status:interview"]
    written = [values for _, values in fake.field_writes]
    assert not any(v == {"singleSelectOptionId": "opt_Applied"} for values in written for v in values.values())
    assert state["synced"][URL] == "Interview"


def test_new_issue_is_added_with_its_details_and_status(monkeypatch):
    fake = FakeGitHub(monkeypatch, issues=[_issue(labels=("status:new",))], items={})
    state = {"synced": {}, "retry_after": ""}
    counts = sync.sync(state)
    assert fake.added == ["I_1"] and counts["details"] == 1
    _, values = fake.field_writes[0]
    assert {"text": "Acme"} in values.values() and {"number": 72.0} in values.values()
    assert {"singleSelectOptionId": "opt_New"} in values.values()
    assert state["synced"][URL] == "New"


def test_writes_beyond_the_cap_wait_for_the_next_run(monkeypatch):
    issues = [_issue(number=n, labels=("status:new",)) for n in range(1, 13)]
    fake = FakeGitHub(monkeypatch, issues=issues, items={})
    counts = sync.sync({"synced": {}, "retry_after": ""})
    assert len(fake.added) == sync.MAX_WRITES_PER_RUN
    assert counts["deferred"] == 12 - sync.MAX_WRITES_PER_RUN


def test_rate_limit_pauses_the_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(sync, "SYNC_STATE", tmp_path / "state.json")
    monkeypatch.setattr(sync, "lock_file", lambda: None)

    def throttled(state):
        state["synced"][URL] = "New"
        raise sync.RateLimited("GraphQL: API rate limit exceeded")

    monkeypatch.setattr(sync, "sync", throttled)
    assert sync.run_sync() == 0
    state = sync.load_sync_state(sync.SYNC_STATE)
    assert state["synced"] == {URL: "New"}  # progress before the limit is kept
    retry_after = datetime.fromisoformat(state["retry_after"])
    assert retry_after > datetime.now(timezone.utc) + timedelta(minutes=10)

    monkeypatch.setattr(sync, "sync", lambda state: pytest.fail("must not sync while paused"))
    assert sync.run_sync() == 0


def test_throttled_owner_lookup_counts_as_rate_limit(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "unknown owner type"

    monkeypatch.setattr(sync.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(sync.RateLimited):
        sync.run(["gh", "project", "item-list"])


def test_status_vocabulary_matches_the_package():
    # The tool runs outside the repo, so it carries its own copy; keep it identical.
    assert sync.STATUS_VALUES == {status.lower(): status for status in STATUSES}
    assert sync.STATUS_LABEL_STYLES == {name: style for name, style in LABELS.items() if name.startswith("status:")}
    [options] = [opts for name, _, opts in sync.PROJECT_FIELDS if name == sync.STATUS_FIELD]
    assert set(options.split(",")) == set(STATUSES)


def test_graphql_errors_are_raised_even_when_gh_succeeds(monkeypatch):
    monkeypatch.setattr(
        sync, "run_json", lambda args, **kw: {"errors": [{"type": "RATE_LIMITED", "message": "slow down"}]}
    )
    with pytest.raises(sync.RateLimited):
        sync.graphql("query { viewer { login } }", {})
    monkeypatch.setattr(sync, "run_json", lambda args, **kw: {"errors": [{"message": "Field 'x' doesn't exist"}]})
    with pytest.raises(RuntimeError, match="doesn't exist"):
        sync.graphql("query { viewer { x } }", {})
