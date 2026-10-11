"""The Job Search board: one-time setup, and keeping cards and status labels in sync.

    python3 tools/project_sync.py setup   create (or reuse) the project and its fields, link the repo
    python3 tools/project_sync.py sync    one sync pass; the launchd agent runs this every 2 minutes

Issue labels are the source of truth; dragging a card moves the label.

GitHub throttles bursts of Project writes, so each sync reads the whole board with
one paginated GraphQL query, writes each item's fields in a single batched
mutation, caps the number of writes, and pauses after being throttled.

Standard library and gh only: the installer copies this file out of ~/Downloads,
which launchd cannot read. The status vocabulary below therefore duplicates
job_radar.labels; tests/test_project_sync.py keeps the two identical.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# owner/name of your job-radar repository: JOB_REPOSITORY (the launchd installer sets it),
# GITHUB_REPOSITORY in Actions, or else the checkout this runs in (resolved in main()).
REPO = os.environ.get("JOB_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
# Whose Projects list holds the board: JOB_PROJECT_OWNER, or the repository's owner.
OWNER = os.environ.get("JOB_PROJECT_OWNER") or REPO.partition("/")[0]
PROJECT_NUMBER = int(os.environ.get("JOB_PROJECT_NUMBER", "1"))
STATUS_FIELD = "Application Status"
# Status each item had after the last sync, used to tell which side changed since.
SYNC_STATE = Path(
    os.environ.get(
        "JOB_PROJECT_SYNC_STATE",
        str(Path.home() / "Library" / "Application Support" / "job-radar" / "project-sync-state.json"),
    )
)

# Writes per run (adding a card, filling its details, or moving it). The rest
# waits for the next run, so populating a new board takes a few runs.
MAX_WRITES_PER_RUN = 8
WRITE_PAUSE_SECONDS = 1.5
RATE_LIMIT_BACKOFF = timedelta(minutes=15)

STATUS_VALUES = {
    "new": "New",
    "saved": "Saved",
    "applied": "Applied",
    "interview": "Interview",
    "offer": "Offer",
    "rejected": "Rejected",
    "skipped": "Skipped",
}

STATUS_LABELS = {f"status:{key}" for key in STATUS_VALUES}
STATUS_LABEL_STYLES = {
    "status:new": ("5319E7", "New tracked application"),
    "status:saved": ("0E8A16", "Saved for later"),
    "status:applied": ("1D76DB", "Application submitted"),
    "status:interview": ("FBCA04", "Interview stage"),
    "status:rejected": ("D73A4A", "Application rejected"),
    "status:offer": ("0E8A16", "Offer received"),
    "status:skipped": ("CFD3D7", "Not pursuing"),
}

PROJECT_TITLE = "Job Search"
PROJECT_FIELDS = [
    (STATUS_FIELD, "SINGLE_SELECT", "New,Saved,Applied,Interview,Offer,Rejected,Skipped"),
    ("Match Score", "NUMBER", ""),
    ("Company", "TEXT", ""),
    ("Location", "TEXT", ""),
    ("Source", "SINGLE_SELECT", "LinkedIn,Indeed,Company"),
    ("Date Found", "DATE", ""),
    ("Job URL", "TEXT", ""),
]
REST_API_VERSION = "2026-03-10"

JOB_TITLE_PREFIXES = ("[LinkedIn Job]", "[LinkedIn Alert]", "[Indeed Job]")

BOARD_QUERY = """
query($owner: String!, $number: Int!, $cursor: String, $statusField: String!) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 50) {
        nodes {
          ... on ProjectV2FieldCommon { id name dataType }
          ... on ProjectV2SingleSelectField { options { id name } }
        }
      }
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content { ... on Issue { url } }
          status: fieldValueByName(name: $statusField) {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          source: fieldValueByName(name: "Source") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""

ADD_ITEM_MUTATION = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) { item { id } }
}
"""


class RateLimited(RuntimeError):
    """GitHub refused the request because of a (primary or secondary) rate limit."""


def run(args: list[str], *, check: bool = True, input_text: str | None = None) -> str:
    proc = subprocess.run(args, text=True, capture_output=True, input=input_text)
    if check and proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        lowered = message.lower()
        # gh reports a throttled owner lookup as "unknown owner type".
        if "rate limit" in lowered or "unknown owner type" in lowered:
            raise RateLimited(message)
        raise RuntimeError(message or f"Command failed: {' '.join(args)}")
    return proc.stdout.strip()


def run_json(args: list[str], *, input_text: str | None = None) -> Any:
    output = run(args, input_text=input_text)
    return json.loads(output or "{}")


def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables})
    data = run_json(["gh", "api", "graphql", "--input", "-"], input_text=payload)
    errors = data.get("errors") or []
    if errors:
        message = "; ".join(str(error.get("message", error)) for error in errors)
        if any(error.get("type") == "RATE_LIMITED" for error in errors) or "rate limit" in message.lower():
            raise RateLimited(message)
        raise RuntimeError(f"GraphQL: {message}")
    return data.get("data") or {}


def section(body: str, heading: str) -> str:
    pattern = re.compile(
        rf"^###\s+{re.escape(heading)}\s*$\s*\n+(.*?)(?=^###\s+|\Z)",
        flags=re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(body or "")
    return match.group(1).strip() if match else ""


def issue_labels(issue: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for label in issue.get("labels") or []:
        name = label.get("name", "") if isinstance(label, dict) else str(label)
        if name:
            labels.add(name)
    return labels


def label_status(issue: dict[str, Any], last_synced: str = "") -> str:
    """Status from the issue's status:* label.

    While a second status label is being added there can briefly be two; the one
    that differs from the last synced status is the new choice.
    """
    statuses: list[str] = []
    for label in sorted(issue_labels(issue)):
        if not label.startswith("status:"):
            continue
        key = label.split(":", 1)[1].strip().lower()
        if key in STATUS_VALUES:
            statuses.append(STATUS_VALUES[key])
    changed = [status for status in statuses if status != last_synced]
    if changed:
        return changed[0]
    return statuses[0] if statuses else ""


def sync_direction(board: str, label: str, last_synced: str) -> str:
    """Return "board_to_issue", "issue_to_board" or "" when both already agree.

    Issue labels are the source of truth. A board value only moves the label when
    the board alone changed since the last sync, i.e. you dragged the card; a
    label you or a workflow changed is pushed to the board instead of reverted.
    """
    if board == label:
        return ""
    if not label:
        return "board_to_issue"
    if not board:
        return "issue_to_board"
    if last_synced and label == last_synced:
        return "board_to_issue"
    return "issue_to_board"


def load_sync_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    synced = data.get("synced")
    return {
        "synced": {str(k): str(v) for k, v in synced.items()} if isinstance(synced, dict) else {},
        "retry_after": str(data.get("retry_after") or ""),
    }


def save_sync_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def relevant_issue(issue: dict[str, Any]) -> bool:
    return str(issue.get("title", "")).startswith(JOB_TITLE_PREFIXES)


def repository_issues() -> list[dict[str, Any]]:
    data = run_json(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            REPO,
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "id,number,title,url,body,labels,state,createdAt",
        ]
    )
    return data if isinstance(data, list) else []


def load_board() -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    """Return (project id, fields by name, items by issue URL) in one paginated query."""
    project_id = ""
    fields: dict[str, dict[str, Any]] = {}
    items: dict[str, dict[str, str]] = {}
    cursor: str | None = None
    while True:
        data = graphql(
            BOARD_QUERY,
            {
                "owner": OWNER,
                "number": PROJECT_NUMBER,
                "cursor": cursor,
                "statusField": STATUS_FIELD,
            },
        )
        project = (data.get("user") or {}).get("projectV2")
        if not project:
            raise RuntimeError(f"Project #{PROJECT_NUMBER} of {OWNER} was not found.")
        project_id = project["id"]
        fields = {node["name"]: node for node in project["fields"]["nodes"] if node and node.get("name")}
        for node in project["items"]["nodes"]:
            url = str((node.get("content") or {}).get("url") or "")
            if url:
                items[url] = {
                    "id": node["id"],
                    "status": str((node.get("status") or {}).get("name") or ""),
                    "source": str((node.get("source") or {}).get("name") or ""),
                }
        page = project["items"]["pageInfo"]
        if not page["hasNextPage"]:
            return project_id, fields, items
        cursor = page["endCursor"]


def field_value(field: dict[str, Any], value: str) -> dict[str, Any] | None:
    """Translate a display value into the ProjectV2FieldValue input for the field's type."""
    data_type = field.get("dataType")
    if data_type == "SINGLE_SELECT":
        for option in field.get("options") or []:
            if option["name"].lower() == value.lower():
                return {"singleSelectOptionId": option["id"]}
        return None
    if data_type == "NUMBER":
        return {"number": float(value)}
    if data_type == "DATE":
        return {"date": value}
    return {"text": value}


def set_item_fields(
    project_id: str,
    item_id: str,
    fields: dict[str, dict[str, Any]],
    values: dict[str, str],
) -> None:
    """Set several fields of one item with a single batched mutation."""
    definitions = ["$project: ID!", "$item: ID!"]
    updates: list[str] = []
    variables: dict[str, Any] = {"project": project_id, "item": item_id}
    for name, raw in values.items():
        field = fields.get(name)
        value = field_value(field, raw) if field and raw else None
        if value is None:
            continue
        index = len(updates)
        definitions += [f"$field{index}: ID!", f"$value{index}: ProjectV2FieldValue!"]
        variables[f"field{index}"] = field["id"]
        variables[f"value{index}"] = value
        updates.append(
            f"update{index}: updateProjectV2ItemFieldValue(input: "
            f"{{projectId: $project, itemId: $item, fieldId: $field{index}, value: $value{index}}}) "
            "{ clientMutationId }"
        )
    if updates:
        graphql(f"mutation({', '.join(definitions)}) {{ {' '.join(updates)} }}", variables)


def latest_score(issue_number: int) -> str:
    try:
        data = run_json(["gh", "issue", "view", str(issue_number), "--repo", REPO, "--json", "comments"])
    except RateLimited:
        raise
    except RuntimeError:
        return ""
    scores = re.findall(
        r"^##\s+(\d+)%\s+—",
        "\n".join(str(comment.get("body", "")) for comment in data.get("comments", [])),
        flags=re.MULTILINE,
    )
    return scores[-1] if scores else ""


def item_details(issue: dict[str, Any]) -> dict[str, str]:
    body = str(issue.get("body", ""))
    company = section(body, "Company")
    location = section(body, "Location")
    # Older LinkedIn alert Issues hold "Company · Location" on one line.
    if " · " in company and (not location or location.lower().startswith("unknown")):
        company, _, location = (part.strip() for part in company.partition(" · "))
    return {
        "Source": "Indeed" if str(issue.get("title", "")).startswith("[Indeed Job]") else "LinkedIn",
        "Company": company,
        "Location": location,
        "Job URL": section(body, "Job URL") or section(body, "LinkedIn job URL"),
        "Date Found": str(issue.get("createdAt", ""))[:10],
        "Match Score": latest_score(int(issue["number"])),
    }


def replace_status_label(issue: dict[str, Any], desired: str) -> bool:
    desired_label = f"status:{desired.lower()}"
    current = issue_labels(issue) & STATUS_LABELS
    if current == {desired_label}:
        return False
    command = ["gh", "issue", "edit", str(issue["number"]), "--repo", REPO]
    for label in sorted(current - {desired_label}):
        command += ["--remove-label", label]
    if desired_label not in current:
        command += ["--add-label", desired_label]
    run(command)
    return True


def lock_file() -> Any:
    import fcntl

    path = Path.home() / ".job-radar-project-sync.lock"
    handle = path.open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another project sync is already running.")
        sys.exit(0)
    return handle


def sync(state: dict[str, Any]) -> dict[str, int]:
    """One sync pass; records progress in state["synced"] as it goes."""
    synced: dict[str, str] = state["synced"]
    counts = {"board_to_issue": 0, "issue_to_board": 0, "added": 0, "details": 0, "deferred": 0}
    writes = 0

    def write_allowed() -> bool:
        nonlocal writes
        if writes >= MAX_WRITES_PER_RUN:
            counts["deferred"] += 1
            return False
        if writes:
            time.sleep(WRITE_PAUSE_SECONDS)
        writes += 1
        return True

    issues = {str(i.get("url", "")): i for i in repository_issues() if relevant_issue(i)}
    project_id, fields, items = load_board()

    # 1. Status changes first: they are what you are waiting to see.
    for url, item in items.items():
        issue = issues.get(url)
        if issue is None:
            continue
        last_synced = synced.get(url, "")
        board = item["status"] if item["status"] in STATUS_VALUES.values() else ""
        label = label_status(issue, last_synced)
        direction = sync_direction(board, label, last_synced)
        if not direction:
            if board:
                synced[url] = board
            continue
        if not write_allowed():
            continue
        if direction == "board_to_issue":
            if replace_status_label(issue, board):
                counts["board_to_issue"] += 1
            synced[url] = board
        else:
            set_item_fields(project_id, item["id"], fields, {STATUS_FIELD: label})
            counts["issue_to_board"] += 1
            synced[url] = label

    # 2. Add new job Issues, and fill in cards that are missing their details
    #    (for example after an interrupted run).
    for url, issue in issues.items():
        item = items.get(url)
        if item and item["source"]:
            continue
        if not write_allowed():
            continue
        values = item_details(issue)
        if item is None:
            added = graphql(ADD_ITEM_MUTATION, {"project": project_id, "content": issue["id"]})
            item = {"id": added["addProjectV2ItemById"]["item"]["id"], "status": "", "source": ""}
            items[url] = item
            counts["added"] += 1
            # Existing cards got their status in step 1; a new card takes the label's.
            status = label_status(issue)
            if status:
                values[STATUS_FIELD] = status
                synced[url] = status
        set_item_fields(project_id, item["id"], fields, values)
        counts["details"] += 1

    return counts


def _project_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    return list(data.get("projects") or []) if isinstance(data, dict) else []


def run_setup() -> int:
    """Create or reuse the project, its fields, its board view and the status labels."""
    try:
        run(["gh", "auth", "status"])
        projects = _project_list(run_json(["gh", "project", "list", "--owner", OWNER, "--format", "json"]))
    except RuntimeError as exc:
        print(
            "The GitHub CLI needs to be logged in with the Projects permission. Run:\n\n"
            f"  gh auth login\n  gh auth refresh -s project\n\nGitHub said: {exc}",
            file=sys.stderr,
        )
        return 2

    existing = next((project for project in projects if project.get("title") == PROJECT_TITLE), None)
    if existing:
        number, url = int(existing["number"]), existing.get("url", "")
        print(f"Using existing project #{number}: {PROJECT_TITLE}")
    else:
        created = run_json(["gh", "project", "create", "--owner", OWNER, "--title", PROJECT_TITLE, "--format", "json"])
        number, url = int(created["number"]), created.get("url", "")
        print(f"Created project #{number}: {PROJECT_TITLE}")

    run(
        [
            "gh",
            "project",
            "edit",
            str(number),
            "--owner",
            OWNER,
            "--visibility",
            "PRIVATE",
            "--description",
            "Job applications: discovered → saved → applied → interview → offer/rejected.",
        ],
        check=False,
    )
    run(["gh", "project", "link", str(number), "--owner", OWNER, "--repo", REPO], check=False)

    field_data = run_json(["gh", "project", "field-list", str(number), "--owner", OWNER, "--format", "json"])
    fields = {field.get("name", "") for field in field_data.get("fields", [])}
    for name, data_type, options in PROJECT_FIELDS:
        if name in fields:
            continue
        args = ["gh", "project", "field-create", str(number), "--owner", OWNER]
        args += ["--name", name, "--data-type", data_type]
        if options:
            args += ["--single-select-options", options]
        run(args)
        print(f"Created field: {name}")

    if not existing:
        _create_board_view(number)

    listed = run_json(["gh", "label", "list", "--repo", REPO, "--limit", "500", "--json", "name"])
    labels = {label["name"] for label in listed}
    for name, (color, description) in STATUS_LABEL_STYLES.items():
        if name not in labels:
            run(["gh", "label", "create", name, "--repo", REPO, "--color", color, "--description", description])

    print(f"\n{PROJECT_TITLE} is ready: {url or f'https://github.com/users/{OWNER}/projects/{number}'}")
    print("Cards are added by the sync (python3 tools/project_sync.py sync, or the launchd agent).")
    print("If there is no Applications board view, add a Board view grouped by Application Status.")
    return 0


def _create_board_view(number: int) -> None:
    """An Applications board grouped by status; optional, as not every token can create views."""
    try:
        user = run_json(["gh", "api", "-H", f"X-GitHub-Api-Version: {REST_API_VERSION}", "/user"])
        rest_fields = run_json(
            [
                "gh",
                "api",
                "-H",
                f"X-GitHub-Api-Version: {REST_API_VERSION}",
                f"/users/{OWNER}/projectsV2/{number}/fields?per_page=100",
            ]
        )
        status_field = next(field for field in rest_fields if field.get("name") == STATUS_FIELD)
        payload = json.dumps(
            {
                "name": "Applications",
                "layout": "board",
                "filter": "is:issue",
                "vertical_group_by": [int(status_field["id"])],
            }
        )
        run(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "-H",
                f"X-GitHub-Api-Version: {REST_API_VERSION}",
                f"/users/{user['id']}/projectsV2/{number}/views",
                "--input",
                "-",
            ],
            input_text=payload,
        )
    except (RuntimeError, StopIteration, KeyError, ValueError):
        pass


def run_sync() -> int:
    _lock = lock_file()
    state = load_sync_state(SYNC_STATE)
    now = datetime.now(timezone.utc)
    if state["retry_after"] and datetime.fromisoformat(state["retry_after"]) > now:
        print(f"Paused after a GitHub rate limit; next attempt after {state['retry_after']}.")
        return 0

    state["retry_after"] = ""
    try:
        counts = sync(state)
    except RateLimited as exc:
        state["retry_after"] = (now + RATE_LIMIT_BACKOFF).isoformat()
        print(f"GitHub rate limit hit; pausing until {state['retry_after']}. {exc}", file=sys.stderr)
        return 0
    finally:
        save_sync_state(SYNC_STATE, state)

    print("Project sync complete: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["setup", "sync"])
    args = parser.parse_args(argv)
    _resolve_repo()
    return run_setup() if args.command == "setup" else run_sync()


def _resolve_repo() -> None:
    global OWNER, REPO
    if not REPO:
        try:
            REPO = run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
        except (OSError, RuntimeError):
            REPO = ""
    if not REPO:
        sys.exit("Set JOB_REPOSITORY (e.g. you/job-radar) or run this inside your job-radar checkout.")
    OWNER = OWNER or REPO.partition("/")[0]


if __name__ == "__main__":
    raise SystemExit(main())
