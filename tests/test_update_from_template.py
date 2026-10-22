"""tools/update_from_template.py: which files an update brings in, and what it leaves as you have it."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/update-from-template.yml"


def _load_tool():
    spec = importlib.util.spec_from_file_location("update_from_template", ROOT / "tools/update_from_template.py")
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses look their module up while it loads.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict[str, str | None], message: str) -> str:
    """Write (or with None, delete) the files and commit them: the commit."""
    for path, text in files.items():
        target = repo / path
        if text is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        if path.endswith(".sh"):
            target.chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def show(rev: str, path: str) -> str:
    return git(Path.cwd(), "show", f"{rev}:{path}") + "\n"


DAILY = """name: Daily Job Radar
on:
  schedule:
    - cron: '13 7 * * *'
      timezone: 'UTC'
jobs:
  scan:
    runs-on: ubuntu-24.04
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Scan
        run: radar scan
"""
README = "".join(f"line {n}\n" for n in range(1, 13))
TEMPLATE_V1 = {
    "src/job_radar/cli.py": "print('v1')\n",
    "README.md": README,
    "pyproject.toml": "[project]\nname = 'job-radar'\nversion = '1'\n",
    "config/search_config.yaml": "timezone: UTC\n",
    "resumes/master_resume.json": "{}\n",
    ".github/workflows/daily-jobs.yml": DAILY,
    "docs/old.md": "old\n",
    "docs/gone.md": "gone v1\n",
    "tools/run.sh": "echo v1\n",
}
# What you did in your copy: your setup and data, and a few edits to the template's files.
YOUR_EDITS = {
    "README.md": README.replace("line 10\n", "line 10, mine\n"),
    "pyproject.toml": "[project]\nname = 'job-radar'\nversion = 'mine'\n",
    "config/search_config.yaml": "timezone: Europe/London\n",
    "resumes/master_resume.json": '{"identity": {"name": "Ada"}}\n',
    ".github/workflows/daily-jobs.yml": DAILY.replace("'UTC'", "'Europe/London'"),
    "data/seen_jobs.json": "{}\n",
    "src/job_radar/mine.py": "print('mine')\n",
    "docs/gone.md": None,
}
TEMPLATE_V2 = {
    "src/job_radar/cli.py": "print('v2')\n",
    "README.md": README.replace("line 1\n", "line 1, v2\n"),
    "pyproject.toml": "[project]\nname = 'job-radar'\nversion = '2'\n",
    "config/search_config.yaml": "timezone: UTC\nnew_setting: true\n",
    ".github/workflows/daily-jobs.yml": DAILY.replace("checkout@v4", "checkout@v7"),
    "docs/old.md": None,
    "docs/new.md": "new\n",
    "docs/gone.md": "gone v2\n",
    "tools/run.sh": "echo v2\n",
}


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    """git that ignores your own configuration (such as commit signing)."""
    (tmp_path / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")


@pytest.fixture
def repos(tmp_path, git_env, monkeypatch):
    """A template at v2, and a copy made from it at v1 with "Use this template", then edited. Runs in the copy."""
    template, copy = tmp_path / "template", tmp_path / "copy"
    for repo in (template, copy):
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
    v1 = commit(template, TEMPLATE_V1, "v1")
    # The copy's first commit has the template's files, but no history in common with it.
    commit(copy, TEMPLATE_V1, "Initial commit")
    commit(copy, YOUR_EDITS, "My setup")
    v2 = commit(template, TEMPLATE_V2, "v2")
    monkeypatch.chdir(copy)
    return SimpleNamespace(template=template, v1=v1, v2=v2)


def update_from(repos) -> "tool.Update":
    return tool.build_update("o/job-radar", tool.fetch_template(str(repos.template), "main"))


def kinds(update) -> dict[str, str]:
    return {change.path: change.kind for change in update.files + update.workflows}


@pytest.mark.parametrize(
    ("path", "owner"),
    [
        ("src/job_radar/cli.py", "template"),
        ("tests/fixtures/blank/search_config.yaml", "template"),
        (".github/workflows/daily-jobs.yml", "template"),
        (".github/actions/setup/action.yml", "template"),
        ("README.zh-CN.md", "template"),
        ("resumes/README.md", "template"),
        ("config/search_config.yaml", "yours"),
        ("resumes/master_resume.json", "yours"),
        ("resumes/jobs/abc/resume.docx", "yours"),
        ("resumes/index.csv", "yours"),
        ("data/seen_jobs.json", "yours"),
        ("reports/latest.md", "yours"),
        (".github/template-version", "yours"),
        ("notes.md", ""),
        ("src", ""),
    ],
)
def test_owner(path, owner):
    assert tool.owner(path) == owner


def _in_the_template() -> bool:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo is None:
        origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
        repo = origin.stdout.strip().removesuffix(".git")
    return repo.lower().endswith(tool.DEFAULT_TEMPLATE)


@pytest.mark.skipif(not _in_the_template(), reason="your copy may hold files of its own")
def test_every_file_of_the_template_is_yours_or_the_templates():
    """A new file must go in TEMPLATE_FILES or YOUR_FILES; otherwise updates never bring it to copies."""
    tracked = git(ROOT, "ls-files").splitlines()
    assert [path for path in tracked if not tool.owner(path)] == []


def entry(sha: str | None, mode: str = "100644"):
    return tool.Entry(mode, sha) if sha else None


@pytest.mark.parametrize(
    ("base", "yours", "template", "step"),
    [
        ("1", "1", "1", None),
        ("1", "2", "1", None),  # only you changed it: yours stays
        ("1", "1", "2", "take"),
        ("1", "2", "2", None),  # you already have the template's version
        ("1", "2", "3", "merge"),
        (None, None, "1", "take"),  # a new template file
        ("1", "1", None, "delete"),
        ("1", None, "2", "keep-deleted"),
        ("1", "2", None, "delete-edited"),
        ("1", None, None, None),
        (None, "1", None, None),  # your own file
        (None, "1", "2", "merge"),  # you both added it
    ],
)
def test_plan(base, yours, template, step):
    trees = [{"src/job_radar/x.py": entry(sha)} if sha else {} for sha in (base, yours, template)]
    assert tool.plan(*trees) == ({"src/job_radar/x.py": step} if step else {})


def test_plan_takes_a_new_file_mode():
    assert tool.plan(*[{"tools/run.sh": entry("1")}] * 2, {"tools/run.sh": entry("1", "100755")}) == {
        "tools/run.sh": "take"
    }


def test_plan_never_touches_your_files_or_unknown_ones():
    paths = ("config/search_config.yaml", "resumes/master_resume.json", "data/seen_jobs.json", "notes.md")
    assert tool.plan(*[{path: entry(sha) for path in paths} for sha in ("1", "2", "3")]) == {}


def test_record_round_trips():
    assert tool.read_record(tool.render_record("o/job-radar", "abc", "")) == {
        "template": "o/job-radar",
        "files": "abc",
        "workflows": "",
    }


def test_update_a_copy_made_with_use_this_template(repos):
    update = update_from(repos)

    assert (update.files_base, update.workflows_base, update.compare_from) == (repos.v1, repos.v1, repos.v1)
    assert kinds(update) == {
        "README.md": "merged",
        "docs/gone.md": "kept-deleted",
        "docs/new.md": "added",
        "docs/old.md": "deleted",
        "pyproject.toml": "replaced",
        "src/job_radar/cli.py": "updated",
        "tools/run.sh": "updated",
        ".github/workflows/daily-jobs.yml": "merged",
    }
    assert update.examples == ["config/search_config.yaml"]
    [replaced] = [change for change in update.files if change.kind == "replaced"]
    assert "-version = '1'\n+version = 'mine'\n" in replaced.your_changes

    head = git(Path.cwd(), "rev-parse", "HEAD")
    new = tool.commit_update(update, include_workflows=False)
    assert git(Path.cwd(), "rev-parse", f"{new}^") == head
    assert show(new, "src/job_radar/cli.py") == "print('v2')\n"
    assert show(new, "README.md") == README.replace("line 1\n", "line 1, v2\n").replace("line 10\n", "line 10, mine\n")
    assert show(new, "pyproject.toml") == TEMPLATE_V2["pyproject.toml"]
    assert show(new, "docs/new.md") == "new\n"
    assert git(Path.cwd(), "ls-tree", new, "tools/run.sh").startswith("100755 ")
    files = git(Path.cwd(), "ls-tree", "-r", "--name-only", new).splitlines()
    assert "docs/old.md" not in files and "docs/gone.md" not in files
    # Your setup, data and own files are untouched, and so is the workflow file GITHUB_TOKEN can't push.
    for path in ("config/search_config.yaml", "resumes/master_resume.json", ".github/workflows/daily-jobs.yml"):
        assert show(new, path) == YOUR_EDITS[path]
    assert show(new, "data/seen_jobs.json") == "{}\n"
    assert show(new, "src/job_radar/mine.py") == "print('mine')\n"
    record = tool.read_record(show(new, tool.RECORD))
    assert record == {"template": "o/job-radar", "files": repos.v2, "workflows": repos.v1}
    # The checkout itself is left alone.
    assert git(Path.cwd(), "rev-parse", "HEAD") == head
    assert git(Path.cwd(), "status", "--porcelain") == ""


def test_the_next_update_remembers_what_was_merged(repos):
    git(Path.cwd(), "merge", "-q", "--ff-only", tool.commit_update(update_from(repos), include_workflows=False))

    # Only the workflow file you haven't updated yet is left, and it still keeps your timezone.
    update = update_from(repos)
    assert kinds(update) == {".github/workflows/daily-jobs.yml": "merged"}
    assert tool.commit_update(update, include_workflows=False) is None
    new = tool.commit_update(update, include_workflows=True)
    assert show(new, ".github/workflows/daily-jobs.yml") == TEMPLATE_V2[".github/workflows/daily-jobs.yml"].replace(
        "'UTC'", "'Europe/London'"
    )
    assert tool.read_record(show(new, tool.RECORD))["workflows"] == repos.v2

    git(Path.cwd(), "merge", "-q", "--ff-only", new)
    update = update_from(repos)
    assert kinds(update) == {}
    assert tool.commit_update(update, include_workflows=True) is None

    # A later template change is merged against the version you were last updated to.
    v3 = commit(repos.template, {"README.md": TEMPLATE_V2["README.md"].replace("line 5\n", "line 5, v3\n")}, "v3")
    update = update_from(repos)
    assert (update.commit, update.files_base, kinds(update)) == (v3, repos.v2, {"README.md": "merged"})
    readme = show(tool.commit_update(update, include_workflows=True), "README.md")
    assert "line 5, v3\n" in readme and "line 10, mine\n" in readme


def test_a_fork_starts_from_the_history_it_shares(tmp_path, git_env, monkeypatch):
    template = tmp_path / "template"
    template.mkdir()
    git(template, "init", "-q", "-b", "main")
    v1 = commit(template, TEMPLATE_V1, "v1")
    git(tmp_path, "clone", "-q", str(template), "fork")
    commit(template, TEMPLATE_V2, "v2")
    monkeypatch.chdir(tmp_path / "fork")
    assert tool.starting_point(tool.fetch_template(str(template), "main")) == v1


def test_the_pull_request_explains_the_update(repos):
    update = update_from(repos)
    links = tool.Links("me/my-radar", "main", "https://github.com/me/my-radar/actions/runs/1")

    body = tool.render_body(update, links, include_workflows=False)
    assert body.index("Your changes were replaced (1)") < body.index("Workflow files to update yourself (1)")
    assert "**`pyproject.toml`**" in body and "+version = 'mine'" in body
    # The new version of the workflow file to paste keeps your timezone.
    assert "https://github.com/me/my-radar/edit/main/.github/workflows/daily-jobs.yml" in body
    assert "timezone: 'Europe/London'" in body and "checkout@v7" in body
    assert "Merged with your changes (1)\n\nYou had changed these files too." in body
    assert "- `docs/new.md` (new)\n- `docs/old.md` (deleted)\n- `src/job_radar/cli.py`" in body
    assert f"https://github.com/o/job-radar/blob/{repos.v2}/docs/gone.md" in body
    assert f"https://github.com/o/job-radar/compare/{repos.v1}...{repos.v2}#diff-" in body
    assert "`config/search_config.yaml` (" in body and "Reopen pull request" in body

    compact = tool.render_body(update, links, include_workflows=False, contents=False)
    assert "checkout@v7" not in compact and "+version = 'mine'" not in compact
    assert "[the workflow run's summary](https://github.com/me/my-radar/actions/runs/1)" in compact

    with_token = tool.render_body(update, links, include_workflows=True)
    assert "Merged with your changes (2)" in with_token
    assert "update yourself" not in with_token and "Reopen pull request" not in with_token


def test_the_workflow_runs_only_by_hand_and_never_in_the_template():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 reads a bare `on` key as true.
    triggers = workflow.get("on", workflow.get(True))
    # Every copy has this workflow, so it must not cost anything until someone runs it.
    assert list(triggers) == ["workflow_dispatch"]
    assert triggers["workflow_dispatch"]["inputs"]["template"]["default"] == tool.DEFAULT_TEMPLATE
    [job] = workflow["jobs"].values()
    assert job["if"] == f"github.repository != '{tool.DEFAULT_TEMPLATE}'"
    assert "FETCH_HEAD:tools/update_from_template.py" in WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture
def github(repos, tmp_path, monkeypatch):
    """The copy's origin and the template as local repositories, gh calls recorded, and the run's summary."""
    server = tmp_path / "server"
    git(tmp_path, "clone", "-q", "--bare", str(repos.template), str(server / "o/job-radar.git"))
    git(tmp_path, "clone", "-q", "--bare", str(Path.cwd()), str(tmp_path / "origin.git"))
    git(Path.cwd(), "remote", "add", "origin", str(tmp_path / "origin.git"))
    monkeypatch.setattr(tool, "SERVER", str(server))
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/my-radar")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    # fail_create: the stderr `gh pr create` fails with, or "" for success.
    state = SimpleNamespace(calls=[], open_pr="", fail_create="", origin=tmp_path / "origin.git")

    def gh(*args, data=None):
        state.calls.append((args[:2], data))
        if args[:2] == ("pr", "list"):
            return state.open_pr
        if args[:2] == ("pr", "create"):
            if state.fail_create:
                raise subprocess.CalledProcessError(1, "gh", stderr=state.fail_create)
            state.open_pr = "https://github.com/me/my-radar/pull/7"
            return state.open_pr
        return ""

    monkeypatch.setattr(tool, "gh", gh)
    state.summary = lambda: (tmp_path / "summary.md").read_text(encoding="utf-8")
    return state


def test_run_opens_the_pull_request_then_updates_it(github):
    assert tool.main(["--template", "o/job-radar"]) == 0
    branch = git(github.origin, "rev-parse", f"refs/heads/{tool.BRANCH}")
    assert git(github.origin, "show", f"{branch}:src/job_radar/cli.py") == "print('v2')"
    [(_, _), (create, body)] = github.calls
    assert create == ("pr", "create") and "Workflow files to update yourself (1)" in body
    assert "[Review and merge the update](https://github.com/me/my-radar/pull/7)" in github.summary()

    github.calls.clear()
    assert tool.main(["--template", "o/job-radar"]) == 0
    assert [call for call, _ in github.calls] == [("pr", "list"), ("pr", "edit")]


def test_run_in_the_template_itself_does_nothing(github, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "O/Job-Radar")
    assert tool.main(["--template", "o/job-radar"]) == 0
    assert github.calls == []
    assert git(github.origin, "branch", "--list", tool.BRANCH) == ""


def test_run_explains_how_to_open_the_pull_request_when_actions_cannot(github, capsys):
    # What GitHub answers in a new repository, where workflows can't open pull requests yet.
    github.fail_create = (
        "pull request create failed: GraphQL: GitHub Actions is not permitted to create or approve pull "
        "requests (createPullRequest)"
    )
    # Expected on a first update, so the run warns instead of failing (and emailing a failure).
    assert tool.main(["--template", "o/job-radar"]) == 0
    assert "::warning::The update is ready" in capsys.readouterr().out
    summary = github.summary()
    assert f"/me/my-radar/compare/main...{tool.BRANCH}?expand=1" in summary
    assert "Allow GitHub Actions to create and approve pull requests" in summary


def test_run_fails_when_the_pull_request_cant_be_opened_for_another_reason(github, capsys):
    github.fail_create = "HTTP 502: Bad Gateway"
    assert tool.main(["--template", "o/job-radar"]) == 1
    assert "::error::Couldn't open the pull request" in capsys.readouterr().out
    summary = github.summary()
    assert f"/me/my-radar/compare/main...{tool.BRANCH}?expand=1" in summary
    assert "Allow GitHub Actions" not in summary


def test_run_when_up_to_date_closes_the_stale_pull_request(repos, github):
    git(Path.cwd(), "merge", "-q", "--ff-only", tool.commit_update(update_from(repos), include_workflows=True))
    github.open_pr = "https://github.com/me/my-radar/pull/7"
    assert tool.main(["--template", "o/job-radar", "--include-workflows"]) == 0
    assert [call for call, _ in github.calls] == [("pr", "list"), ("pr", "close")]
    assert "Your copy is up to date with o/job-radar" in github.summary()


def test_run_with_a_token_that_cannot_change_workflows_lists_them_instead(github):
    # Like GitHub, the origin refuses pushes that change workflow files.
    hook = github.origin / "hooks/pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do\n"
        '  git diff --name-only "$new^" "$new" | grep -q \'^.github/workflows/\' && exit 1\n'
        "done\nexit 0\n"
    )
    hook.chmod(0o755)
    assert tool.main(["--template", "o/job-radar", "--include-workflows"]) == 0
    branch = git(github.origin, "rev-parse", f"refs/heads/{tool.BRANCH}")
    assert "Europe/London" in git(github.origin, "show", f"{branch}:.github/workflows/daily-jobs.yml")
    assert "checkout@v4" in git(github.origin, "show", f"{branch}:.github/workflows/daily-jobs.yml")
    [(_, _), (_, body)] = github.calls
    assert "`TEMPLATE_UPDATE_TOKEN` secret couldn't change workflow files" in body
    assert "Reopen pull request" not in body


def test_long_diffs_are_cut_but_new_versions_to_paste_never_are():
    text = "".join(f"line {n}\n" for n in range(tool.MAX_DIFF_LINES + 50))
    assert "line 249" in tool._details("New version", text, "yaml")
    cut = tool._details("Your changes", text, "diff")
    assert f"line {tool.MAX_DIFF_LINES - 1}\n" in cut and "line 249" not in cut and "… 50 more lines" in cut
