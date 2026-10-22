"""Bring a copy of the Job Radar template up to date with the template's later fixes.

    python3 update_from_template.py [--template OWNER/NAME] [--ref BRANCH] [--base BRANCH] [--include-workflows]

.github/workflows/update-from-template.yml runs this in a copy made with "Use this template". Such a
copy doesn't share the template's git history, so instead of merging, this updates the template's own
files (code, tests, docs, workflows) and never touches the copy's setup and data (config/, the master
résumé, the résumés, data/ and reports/). It commits the result to the update-from-template branch and
opens a pull request for you to review and merge.

Each template file is compared in three versions: the template commit your copy was last updated from
(or made from), yours, and the template's latest.

- The template didn't change it since then: yours stays, edits and all.
- Only the template changed it: the template's version is taken.
- You both changed it: the two are merged line by line (git merge-file). Where you both changed the
  same lines, the template's version is taken, and the pull request shows your changes to add back.

GITHUB_TOKEN can't change workflow files, so without --include-workflows (a token that can), those are
listed in the pull request, with their new contents, for you to update on the GitHub website.

Standard library, git and gh only. The workflow runs this file straight from the template, with the
arguments in the copy's own (possibly older) update-from-template.yml: keep the command line compatible.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEMPLATE = "estul26/job-radar"
BRANCH = "update-from-template"
# Records the template commits the copy was last updated from, so the next update knows what you changed.
RECORD = ".github/template-version"
WORKFLOWS = ".github/workflows/"
SERVER = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

# The template's files, which updates bring in. A folder ends in a slash.
TEMPLATE_FILES = (
    ".github/actions/",
    ".github/ISSUE_TEMPLATE/",
    WORKFLOWS,
    "docs/",
    "src/",
    "tests/",
    "tools/",
    ".gitignore",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "pyproject.toml",
    "resumes/README.md",
)
# Your files: never written, even where the template has one (its blank config and résumé).
# These win over TEMPLATE_FILES. Files of neither kind are left alone too.
YOUR_FILES = (
    "config/",
    "resumes/master_resume.json",
    "resumes/jobs/",
    "resumes/index.csv",
    "data/",
    "reports/",
    RECORD,
)

# GitHub refuses pull request bodies over 65,536 characters; past this, the contents go in the run summary.
MAX_BODY = 60_000
# Diffs of your changes are cut here. New file versions never are: they're for pasting.
MAX_DIFF_LINES = 200

# What an update does to one template file. The last kind leaves the file as you have it.
ADDED, UPDATED, DELETED = "added", "updated", "deleted"  # the template changed a file you hadn't
MERGED = "merged"  # you both changed it, in different places: both changes kept
REPLACED = "replaced"  # you both changed the same lines: the template's version
DELETED_EDITED = "deleted-edited"  # the template deleted a file you had changed
KEPT_DELETED = "kept-deleted"  # you deleted a file the template has changed since: it stays deleted


def owner(path: str) -> str:
    """'yours', 'template', or '' for a file of neither kind."""

    def under(patterns: tuple[str, ...]) -> bool:
        return any(path == p or (p.endswith("/") and path.startswith(p)) for p in patterns)

    if under(YOUR_FILES):
        return "yours"
    return "template" if under(TEMPLATE_FILES) else ""


def is_workflow(path: str) -> bool:
    return path.startswith(WORKFLOWS)


@dataclass(frozen=True)
class Entry:
    """A file in a git tree: its mode (100644, 100755 or 120000) and blob."""

    mode: str
    sha: str


Tree = dict[str, Entry]


@dataclass(frozen=True)
class Change:
    """What the update does to one template file: entry is its new version, None deletes it."""

    path: str
    kind: str
    entry: Entry | None = None
    # Your edits that this change drops, as a diff.
    your_changes: str = ""

    @property
    def writes(self) -> bool:
        return self.kind != KEPT_DELETED


def plan(base: Tree, yours: Tree, template: Tree) -> dict[str, str]:
    """Each template file to change: take, delete, merge, delete-edited or keep-deleted.

    base is the template version your copy was last updated from. Files the template hasn't changed
    since are left out, so they stay as you have them.
    """
    steps = {}
    for path in sorted(base.keys() | yours.keys() | template.keys()):
        if owner(path) != "template":
            continue
        old, mine, new = base.get(path), yours.get(path), template.get(path)
        if mine == new or old == new:
            continue
        if old == mine:
            steps[path] = "take" if new else "delete"
        elif mine is None:
            steps[path] = "keep-deleted"
        elif new is None:
            steps[path] = "delete-edited"
        else:
            steps[path] = "merge"
    return steps


def _run(*args: str, data: bytes | None = None, env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(["git", *args], input=data, capture_output=True, env=env, check=check)


def git(*args: str, data: bytes | None = None, env: dict[str, str] | None = None) -> str:
    return _run(*args, data=data, env=env).stdout.decode().strip()


def gh(*args: str, data: str | None = None) -> str:
    return subprocess.run(["gh", *args], input=data, capture_output=True, text=True, check=True).stdout.strip()


def read_tree(rev: str | None) -> Tree:
    tree: Tree = {}
    if rev:
        for item in _run("ls-tree", "-r", "-z", rev).stdout.decode().split("\0"):
            if item:
                meta, path = item.split("\t", 1)
                mode, kind, sha = meta.split()
                if kind == "blob":
                    tree[path] = Entry(mode, sha)
    return tree


def blob(entry: Entry | None) -> bytes:
    return _run("cat-file", "blob", entry.sha).stdout if entry else b""


def merge(mine: Entry, old: Entry, new: Entry) -> str | None:
    """Both sides' changes merged with git merge-file: the merged blob, or None where they overlap."""
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, entry in (("yours", mine), ("base", old), ("template", new)):
            files.append(Path(tmp, name))
            files[-1].write_bytes(blob(entry))
        result = _run("merge-file", "-p", *map(str, files), check=False)
    # The exit status counts the overlaps, or is negative for an error such as a binary file.
    if result.returncode != 0:
        return None
    return git("hash-object", "-w", "--stdin", data=result.stdout)


def diff(path: str, old: Entry | None, mine: Entry | None) -> str:
    def lines(entry: Entry | None) -> list[str]:
        text = blob(entry).decode()
        return [line if line.endswith("\n") else line + "\n" for line in text.splitlines(keepends=True)]

    try:
        return "".join(difflib.unified_diff(lines(old), lines(mine), f"a/{path}", f"b/{path}"))
    except UnicodeDecodeError:
        return "(a binary file)\n"


def resolve(path: str, step: str, base: Tree, yours: Tree, template: Tree) -> Change | None:
    """The change for one planned step, merging where you both changed a file; None if nothing changes."""
    old, mine, new = base.get(path), yours.get(path), template.get(path)
    if step == "take":
        return Change(path, UPDATED if mine else ADDED, new)
    if step == "delete":
        return Change(path, DELETED)
    if step == "keep-deleted":
        return Change(path, KEPT_DELETED)
    if step == "delete-edited":
        return Change(path, DELETED_EDITED, None, diff(path, old, mine))
    merged = merge(mine, old, new) if old else None
    if merged == mine.sha:
        return None
    if merged:
        return Change(path, MERGED, Entry(new.mode, merged))
    return Change(path, REPLACED, new, diff(path, old, mine))


def changes(base: Tree, yours: Tree, template: Tree) -> list[Change]:
    resolved = (resolve(path, step, base, yours, template) for path, step in plan(base, yours, template).items())
    return [change for change in resolved if change]


def read_record(text: str) -> dict[str, str]:
    record = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith("#"):
            record[key.strip()] = value.strip()
    return record


def render_record(template: str, files: str, workflows: str) -> str:
    return (
        "# Written by the Update from template workflow (tools/update_from_template.py). Don't edit it.\n"
        "# The template commits this copy's files and its workflow files were last updated from.\n"
        f"template: {template}\nfiles: {files}\nworkflows: {workflows}\n"
    )


def _is_commit(rev: str) -> bool:
    return bool(rev) and _run("cat-file", "-e", f"{rev}^{{commit}}", check=False).returncode == 0


def starting_point(template_ref: str) -> str | None:
    """The commit a copy that was never updated started from."""
    shared = _run("merge-base", "HEAD", template_ref, check=False)
    if shared.returncode == 0:
        # A fork or clone shares the template's history.
        return shared.stdout.decode().strip()
    # "Use this template" makes a first commit with exactly the template's files at the time.
    template_commits: dict[str, str] = {}
    for line in git("log", "--format=%T %H", template_ref).splitlines():
        tree, commit = line.split()
        template_commits.setdefault(tree, commit)
    roots = git("rev-list", "--max-parents=0", "HEAD").split()
    for root in roots:
        commit = template_commits.get(git("rev-parse", f"{root}^{{tree}}"))
        if commit:
            return commit
    return roots[-1] if roots else None


@dataclass(frozen=True)
class Update:
    template: str
    commit: str
    files: list[Change]
    workflows: list[Change]
    # Your files whose example in the template changed, such as config/search_config.yaml.
    examples: list[str]
    # The template commits your files and your workflow files were at (a commit of your copy if unknown).
    files_base: str | None
    workflows_base: str | None
    # files_base, when it is a template commit: then the template's changes can be linked.
    compare_from: str | None

    def record(self, include_workflows: bool) -> str:
        """The new RECORD. Workflow files left for you to update keep their old base until they're done."""
        pending = not include_workflows and any(change.writes for change in self.workflows)
        workflows = (self.workflows_base or "") if pending else self.commit
        return render_record(self.template, self.commit, workflows)


def fetch_template(url: str, ref: str) -> str:
    """Fetch the template's branch: the local ref it is now at."""
    local = f"refs/remotes/template/{ref}"
    git("fetch", "--no-tags", url, f"+refs/heads/{ref}:{local}")
    return local


def build_update(template: str, template_ref: str) -> Update:
    """What updating HEAD to the template at template_ref changes."""
    commit = git("rev-parse", template_ref)
    shown = _run("show", f"HEAD:{RECORD}", check=False)
    record = read_record(shown.stdout.decode()) if shown.returncode == 0 else {}
    if record.get("template", "").lower() != template.lower():
        record = {}
    files_base = record.get("files") if _is_commit(record.get("files", "")) else None
    workflows_base = record.get("workflows") if _is_commit(record.get("workflows", "")) else None
    if not (files_base and workflows_base):
        start = starting_point(template_ref)
        files_base, workflows_base = files_base or start, workflows_base or start

    yours, new = read_tree("HEAD"), read_tree(commit)
    files_tree, workflows_tree = read_tree(files_base), read_tree(workflows_base)

    def only(tree: Tree, workflows: bool) -> Tree:
        return {path: entry for path, entry in tree.items() if is_workflow(path) == workflows}

    is_template_commit = (
        files_base is not None
        and _run("merge-base", "--is-ancestor", files_base, template_ref, check=False).returncode == 0
    )
    return Update(
        template=template,
        commit=commit,
        files=changes(only(files_tree, False), only(yours, False), only(new, False)),
        workflows=changes(only(workflows_tree, True), only(yours, True), only(new, True)),
        examples=sorted(
            path
            for path in files_tree.keys() | new.keys()
            if owner(path) == "yours" and path != RECORD and files_tree.get(path) != new.get(path)
        ),
        files_base=files_base,
        workflows_base=workflows_base,
        compare_from=files_base if is_template_commit else None,
    )


def commit_update(update: Update, include_workflows: bool) -> str | None:
    """Commit the update on top of HEAD, without touching the checkout: the commit, or None if nothing changes."""
    chosen = [c for c in update.files + (update.workflows if include_workflows else []) if c.writes]
    if not chosen:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp, "index"))}
        git("read-tree", "HEAD", env=env)
        record = git("hash-object", "-w", "--stdin", data=update.record(include_workflows).encode())
        entries = [(c.entry.mode, c.entry.sha, c.path) for c in chosen if c.entry] + [("100644", record, RECORD)]
        git(
            "update-index",
            "-z",
            "--index-info",
            data=b"".join(f"{m} {s}\t{p}\0".encode() for m, s, p in entries),
            env=env,
        )
        removed = [c.path for c in chosen if not c.entry]
        if removed:
            git("update-index", "--force-remove", "--", *removed, env=env)
        tree = git("write-tree", env=env)
    if tree == git("rev-parse", "HEAD^{tree}"):
        return None
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": BOT_NAME,
        "GIT_AUTHOR_EMAIL": BOT_EMAIL,
        "GIT_COMMITTER_NAME": BOT_NAME,
        "GIT_COMMITTER_EMAIL": BOT_EMAIL,
    }
    message = (
        f"Update from template {update.template}@{update.commit[:7]}\n\n"
        "Made by the Update from template workflow; its pull request lists what changed.\n"
    )
    return git("commit-tree", tree, "-p", "HEAD", "-m", message, env=env)


def _code(text: str, language: str = "") -> str:
    """A fenced code block that the text's own backticks can't close."""
    fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    return f"{fence}{language}\n{text.rstrip(chr(10))}\n{fence}"


def _details(summary: str, text: str, language: str) -> str:
    if language == "diff" and len(lines := text.splitlines()) > MAX_DIFF_LINES:
        text = "\n".join(lines[:MAX_DIFF_LINES] + [f"… {len(lines) - MAX_DIFF_LINES} more lines"])
    return f"<details><summary>{summary}</summary>\n\n{_code(text, language)}\n\n</details>"


def _file_list(paths: list[str]) -> str:
    items = "\n".join(paths)
    return f"<details><summary>{len(paths)} files</summary>\n\n{items}\n\n</details>" if len(paths) > 15 else items


@dataclass(frozen=True)
class Links:
    repo: str
    branch: str
    run_url: str = ""

    def template_file(self, update: Update, path: str) -> str:
        """The template's changes to a file, or its latest version when the starting point isn't known."""
        if update.compare_from:
            anchor = hashlib.sha256(path.encode()).hexdigest()
            return f"{SERVER}/{update.template}/compare/{update.compare_from}...{update.commit}#diff-{anchor}"
        return self.template_blob(update, path)

    def template_blob(self, update: Update, path: str) -> str:
        return f"{SERVER}/{update.template}/blob/{update.commit}/{path}"

    def edit(self, path: str) -> str:
        return f"{SERVER}/{self.repo}/edit/{self.branch}/{path}"

    def create(self, path: str) -> str:
        return f"{SERVER}/{self.repo}/new/{self.branch}?filename={path}"

    def view(self, path: str) -> str:
        return f"{SERVER}/{self.repo}/blob/{self.branch}/{path}"


def pending_section(update: Update, links: Links, contents: bool, token_problem: bool = False) -> list[str]:
    """Instructions for the workflow files you update yourself."""
    pending = [change for change in update.workflows if change.writes]
    if not pending:
        return []
    out = [f"### Workflow files to update yourself ({len(pending)})"]
    if token_problem:
        out.append(
            "Your `TEMPLATE_UPDATE_TOKEN` secret couldn't change workflow files, so they're listed here instead. "
            "Give the token the **Workflows: Read and write** permission to have them included next time."
        )
    else:
        out.append(
            "GitHub doesn't let a workflow change workflow files with its standard token, so these aren't in "
            "this pull request. To have them included next time, add a `TEMPLATE_UPDATE_TOKEN` secret "
            f"([how]({SERVER}/{update.template}/blob/main/docs/setup.md#5-updates-from-the-template))."
        )
    out.append("**After you merge this pull request**, update each one on the GitHub website:")
    for number, change in enumerate(pending, 1):
        name = f"**{number}. `{change.path}`**"
        if change.entry is None:
            out.append(
                f"{name}: [open it]({links.view(change.path)}), click **⋯ → Delete file**, then **Commit changes**."
            )
        else:
            if change.kind == ADDED:
                step = f"{name} (new): [create it]({links.create(change.path)}), paste the new version below"
            else:
                step = (
                    f"{name}: [open it for editing]({links.edit(change.path)}), select everything in it and "
                    "delete it, paste the new version below"
                )
            note = {
                MERGED: " It keeps your own changes to this file.",
                REPLACED: " You and the template changed the same lines, so it's the template's version.",
            }.get(change.kind, "")
            out.append(f"{step}, and click **Commit changes**.{note}")
            if contents:
                out.append(_details("New version", blob(change.entry).decode(), "yaml"))
            else:
                out.append(f"The new version is in [the workflow run's summary]({links.run_url}).")
        if change.your_changes:
            out.append(_your_changes(change, links, contents))
    return out


def _your_changes(change: Change, links: Links, contents: bool) -> str:
    if contents:
        return _details("Your changes, to add back if you still need them", change.your_changes, "diff")
    return f"Your changes are in [the workflow run's summary]({links.run_url})."


def render_body(
    update: Update, links: Links, include_workflows: bool, contents: bool = True, token_problem: bool = False
) -> str:
    """The pull request's description. token_problem: a TEMPLATE_UPDATE_TOKEN opened it but couldn't push workflows."""
    applied = update.files + (update.workflows if include_workflows else [])
    replaced = [c for c in applied if c.kind in (REPLACED, DELETED_EDITED)]
    merged = [c for c in applied if c.kind == MERGED]
    plain = [c for c in applied if c.kind in (ADDED, UPDATED, DELETED)]
    kept = [c for c in update.files + update.workflows if c.kind == KEPT_DELETED]

    template = f"{SERVER}/{update.template}"
    intro = (
        f"This brings your copy up to date with the template, [{update.template}]({template}), "
        f"at [`{update.commit[:7]}`]({template}/commit/{update.commit})."
    )
    if update.compare_from:
        intro += f" [See what changed in it]({template}/compare/{update.compare_from}...{update.commit})."
    yours = ", ".join(f"`{path}`" for path in YOUR_FILES if path != RECORD)
    out = [
        intro,
        f"**Look through Files changed, then click Merge pull request.** Your own files are never changed: {yours}.",
    ]
    if replaced:
        out.append(f"### ⚠️ Your changes were replaced ({len(replaced)})")
        out.append(
            "You and the template changed the same lines of these files, so this pull request uses the "
            "template's version. Your changes are shown so you can add back any you still need after merging."
        )
        for change in replaced:
            deleted = " (deleted by the template)" if change.kind == DELETED_EDITED else ""
            out.append(f"**`{change.path}`**{deleted}")
            out.append(_your_changes(change, links, contents))
    if not include_workflows:
        out.extend(pending_section(update, links, contents, token_problem))
    if merged:
        out.append(f"### Merged with your changes ({len(merged)})")
        out.append("You had changed these files too. Your changes are kept alongside the template's.")
        out.append(_file_list([f"- `{c.path}`" for c in merged]))
    if plain:
        out.append(f"### Updated from the template ({len(plain)})")
        suffix = {ADDED: " (new)", DELETED: " (deleted)", UPDATED: ""}
        out.append(_file_list([f"- `{c.path}`{suffix[c.kind]}" for c in plain]))
    if kept:
        out.append(f"### Left as you have them ({len(kept)})")
        out.append("You deleted these files and the template has changed them since. They stay deleted.")
        out.append(
            "\n".join(f"- `{c.path}` ([the template's version]({links.template_blob(update, c.path)}))" for c in kept)
        )
    if update.examples:
        out.append(f"### The template's example settings changed ({len(update.examples)})")
        out.append(
            "These files are yours, so they weren't changed. If the template added a setting you want, "
            "copy it into yours."
        )
        out.append(
            "\n".join(f"- `{p}` ([the template's change]({links.template_file(update, p)}))" for p in update.examples)
        )
    if not include_workflows and not token_problem:
        out.append("### Checks")
        out.append(
            "GitHub doesn't run checks on a pull request a workflow opened. To run them, click "
            "**Close pull request**, then **Reopen pull request**."
        )
    footer = "Opened by the Update from template workflow"
    if links.run_url:
        footer = f"Opened by [the Update from template workflow]({links.run_url})"
    out.append(f"---\n{footer}. Running it again updates this pull request.")
    return "\n\n".join(out) + "\n"


def push(commit: str) -> bool:
    """Push the update branch."""

    def attempt() -> bool:
        result = _run("push", "--force", "origin", f"{commit}:refs/heads/{BRANCH}", check=False)
        sys.stderr.write(result.stderr.decode())
        return result.returncode == 0

    if attempt():
        return True
    # GitHub checks the workflow files that differ between a branch's old and new commit, so a workflow's
    # token can't move the branch past workflow changes made on yours since. Start it afresh instead
    # (which closes its pull request; a new one is opened).
    if _run("ls-remote", "--exit-code", "origin", f"refs/heads/{BRANCH}", check=False).returncode != 0:
        return False
    _run("push", "origin", f":refs/heads/{BRANCH}", check=False)
    return attempt()


def _open_pull_request(repo: str) -> str:
    """The URL of the update's open pull request, or ''."""
    return gh("pr", "list", "--repo", repo, "--head", BRANCH, "--json", "url", "--jq", ".[0].url // empty")


def open_pull_request(repo: str, branch: str, title: str, body: str) -> str:
    """Open the pull request, or update the one already open: its URL."""
    fields = ("--repo", repo, "--title", title, "--body-file", "-")
    existing = _open_pull_request(repo)
    if existing:
        gh("pr", "edit", existing, *fields, data=body)
        return existing
    return gh("pr", "create", *fields, "--base", branch, "--head", BRANCH, data=body)


def close_stale_pull_request(repo: str) -> None:
    existing = _open_pull_request(repo)
    if existing:
        comment = "Your copy already has everything in this pull request, so it's no longer needed."
        gh("pr", "close", existing, "--repo", repo, "--comment", comment, "--delete-branch")


def summarize(text: str) -> None:
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help=f"the template, OWNER/NAME ({DEFAULT_TEMPLATE})")
    parser.add_argument("--ref", default="main", help="the template's branch (main)")
    parser.add_argument("--base", default="main", help="your branch to update (main)")
    parser.add_argument("--include-workflows", action="store_true", help="the token can change workflow files")
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.template):
        raise SystemExit(f"--template must look like owner/name, not {args.template!r}.")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo.lower() == args.template.lower():
        print("This is the template itself, so there's nothing to update.")
        return 0
    links = Links(repo, args.base, f"{SERVER}/{repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}")

    update = build_update(args.template, fetch_template(f"{SERVER}/{args.template}.git", args.ref))
    include, token_problem = args.include_workflows, False
    commit = commit_update(update, include)
    if commit and not push(commit):
        if not include or not any(change.writes for change in update.workflows):
            raise SystemExit("Couldn't push the update branch; see the error above.")
        print("::warning::TEMPLATE_UPDATE_TOKEN can't change workflow files; listing them in the pull request instead.")
        include, token_problem = False, True
        commit = commit_update(update, include)
        if commit and not push(commit):
            raise SystemExit("Couldn't push the update branch; see the error above.")

    if commit is None:
        close_stale_pull_request(repo)
        out = [f"## Your copy is up to date with {args.template}"]
        if not include:
            out.extend(pending_section(update, links, contents=True, token_problem=token_problem))
        summarize("\n\n".join(out))
        return 0

    title = f"Update from the template ({args.template}@{update.commit[:7]})"
    body = render_body(update, links, include, token_problem=token_problem)
    if len(body) > MAX_BODY:
        body = render_body(update, links, include, contents=False, token_problem=token_problem)
    try:
        url = open_pull_request(repo, args.base, title, body)
    except subprocess.CalledProcessError as error:
        print(error.stderr, file=sys.stderr)
        compare = f"{SERVER}/{repo}/compare/{args.base}...{BRANCH}?expand=1"
        print("::error::Couldn't open the pull request. See this run's summary.")
        summarize(
            "## The update is ready, but the pull request couldn't be opened\n\n"
            f"Your update is on the `{BRANCH}` branch. Either [open the pull request yourself]({compare}), "
            "or let workflows open it: tick **Settings → Actions → General → Allow GitHub Actions to create "
            "and approve pull requests**, click **Save**, and run Update from template again.\n\n"
            f"{render_body(update, links, include, token_problem=token_problem)}"
        )
        return 1
    summarize(
        f"## [Review and merge the update]({url})\n\n"
        + render_body(update, links, include, token_problem=token_problem)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
