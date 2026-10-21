"""radar: the command behind every workflow step.

radar doctor                      check that config/ and your master résumé are filled in
radar scan [--fixture FILE]       collect, score and record jobs; résumés for good matches
radar scan-slot ...               should this daily-jobs.yml run scan, and for which slot?
radar record-claim SLOT DATE      mark a slot's scan as done
radar publish-scan                a job Issue for each good and possible match
radar export                      rebuild data/applications.csv and resumes/index.csv from the Issues
radar issue N --event E [--label L] [--publish]
                                  handle an Issue event (prepare before the commit, publish after)
radar email-ingest                import LinkedIn alert emails as review Issues
radar linkedin-search [...]       search LinkedIn in your signed-in Chrome (Mac, by hand); import the cards
radar linkedin-import FILE        import job cards saved by linkedin-search --export
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("data")


def _set_outputs(**values: str) -> None:
    """Print key=value lines, and expose them as step outputs when running in GitHub Actions."""
    lines = [f"{key}={value}" for key, value in values.items()]
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def _scan(args: argparse.Namespace) -> int:
    from .commands.scan import generate_scan_resumes, issue_fingerprints, scan_jobs
    from .github import GitHub
    from .settings import load_settings

    settings = load_settings()
    # A fixture run is a local demo; a live scan skips jobs that already have an Issue.
    known = frozenset() if args.fixture else issue_fingerprints(GitHub().issues())
    print(scan_jobs(settings, args.fixture, known))
    results = generate_scan_resumes(settings)
    if results is None:
        print("Skipped résumés: resumes/master_resume.json isn't filled in yet (see radar doctor).")
    else:
        used = sum(1 for item in results if item.get("ai_used"))
        print(f"Generated {len(results)} tailored resume(s); AI used for {used}.")
    return 0


def _scan_slot(args: argparse.Namespace) -> int:
    from .commands.slot import check_claim, config_timezone, decide_slot

    decision = decide_slot(
        args.event,
        args.schedule,
        args.ref,
        args.skip_if_done.lower() == "true",
        datetime.now(timezone.utc),
        config_timezone(Path("config/search_config.yaml")),
    )
    if decision.check_claim and args.refresh_main:
        # A delayed earlier run may have finished after this run's checkout was
        # taken, so read the claim (and all daily state) from the latest main.
        subprocess.run(["git", "fetch", "--depth=1", "origin", "main"], check=True)
        subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
    decision = check_claim(decision, DATA_DIR)
    print(decision.reason)
    _set_outputs(skip=str(decision.skip).lower(), slot=decision.slot, date=decision.date)
    return 0


def _record_claim(args: argparse.Namespace) -> int:
    from .commands.slot import record_claim

    print(f"Recorded the {args.slot} scan for {args.date} in {record_claim(DATA_DIR, args.slot, args.date)}.")
    return 0


def _publish_scan(args: argparse.Namespace) -> int:
    from .commands.scan import publish_scan
    from .github import GitHub
    from .settings import load_settings

    numbers = publish_scan(GitHub(), load_settings())
    print(f"Synced {len(numbers)} job-board Issue(s): {numbers}")
    return 0


def _export(args: argparse.Namespace) -> int:
    from .commands.export import export
    from .github import GitHub
    from .settings import load_settings

    applications, resumes = export(GitHub(), load_settings())
    print(f"Exported {applications} tracked job(s) and {resumes} résumé(s).")
    return 0


def _issue(args: argparse.Namespace) -> int:
    from .commands.issue import COMMIT_MESSAGES, prepare, publish, route
    from .github import GitHub
    from .settings import load_settings

    gh = GitHub()
    issue = gh.issue(args.number)
    kind = route(issue, args.event, args.label)
    if kind is None:
        print(f"Nothing to do for '{args.event}' on #{args.number}.")
        _set_outputs(kind="")
        return 0

    settings = load_settings()
    if args.publish:
        publish(gh, settings, issue, kind, args.label)
    else:
        prepare(settings, issue, kind, args.label)
    _set_outputs(kind=kind, commit_message=COMMIT_MESSAGES[kind].format(number=args.number))
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from .commands.doctor import NOT_SET_UP, checkup, render

    result = checkup(args.config, args.profile, args.master)
    print(render(result))
    return 0 if result.ok else NOT_SET_UP


def _email_ingest(args: argparse.Namespace) -> int:
    from .linkedin_email_ingest import main as ingest_main

    return ingest_main(dry_run=args.dry_run, since_days=args.days or None)


def _use_checkout_repository() -> None:
    """Run by hand on the Mac, outside GitHub Actions: take the repository from this checkout."""
    if not os.environ.get("GITHUB_REPOSITORY"):
        os.environ["GITHUB_REPOSITORY"] = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()


def _linkedin_import(args: argparse.Namespace) -> int:
    from .commands.linkedin_import import main as import_main

    _use_checkout_repository()
    return import_main(args.file, dry_run=args.dry_run)


def _linkedin_search(args: argparse.Namespace) -> int:
    from .commands.linkedin_search import MAX_QUERIES_CAP
    from .commands.linkedin_search import main as search_main

    if not 1 <= args.max_queries <= MAX_QUERIES_CAP:
        raise SystemExit(f"--max-queries must be between 1 and {MAX_QUERIES_CAP}.")
    if not args.setup_check:
        _use_checkout_repository()
    return search_main(
        posted=args.posted,
        max_queries=args.max_queries,
        force=args.force,
        dry_run=args.dry_run,
        export=args.export,
        setup_check=args.setup_check,
        keep_open=args.keep_browser_open,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radar", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="check that config/ and your master résumé are filled in")
    doctor.add_argument("--config", default="config/search_config.yaml")
    doctor.add_argument("--profile", default="config/resume_profile.json")
    doctor.add_argument("--master", default="resumes/master_resume.json")
    doctor.set_defaults(handler=_doctor)

    scan = commands.add_parser("scan", help="collect, score and record new jobs")
    scan.add_argument("--fixture", help="read jobs from a JSON file instead of the job boards")
    scan.set_defaults(handler=_scan)

    slot = commands.add_parser("scan-slot", help="decide whether this daily-jobs.yml run scans")
    slot.add_argument("--event", required=True, help="github.event_name")
    slot.add_argument("--schedule", default="", help="github.event.schedule")
    slot.add_argument("--ref", default="", help="github.ref")
    slot.add_argument("--skip-if-done", default="false", help="the workflow_dispatch input")
    slot.add_argument("--refresh-main", action="store_true", help="hard-reset to origin/main before reading claims")
    slot.set_defaults(handler=_scan_slot)

    claim = commands.add_parser("record-claim", help="mark a slot's scan as done")
    claim.add_argument("slot", choices=["morning", "evening"])
    claim.add_argument("date")
    claim.set_defaults(handler=_record_claim)

    publish_scan = commands.add_parser("publish-scan", help="open Issues for the scan's matches")
    publish_scan.set_defaults(handler=_publish_scan)

    export = commands.add_parser("export", help="rebuild the tracker CSVs from the Issues")
    export.set_defaults(handler=_export)

    issue = commands.add_parser("issue", help="handle an Issue event")
    issue.add_argument("number", type=int)
    issue.add_argument("--event", required=True, help="github.event.action")
    issue.add_argument("--label", default="", help="github.event.label.name for 'labeled'")
    issue.add_argument("--publish", action="store_true", help="the GitHub side, after the commit")
    issue.set_defaults(handler=_issue)

    email = commands.add_parser("email-ingest", help="import LinkedIn alert emails")
    email.add_argument("--dry-run", action="store_true", help="report what would be imported; change nothing")
    email.add_argument("--days", type=int, default=0, help="re-read this many days of mail instead of only new mail")
    email.set_defaults(handler=_email_ingest)

    search = commands.add_parser(
        "linkedin-search", help="search LinkedIn in your signed-in Chrome (Mac, by hand) and import the cards"
    )
    search.add_argument("--posted", choices=["24h", "3d", "7d", "30d"], default="7d", help="posting age (7d)")
    search.add_argument("--max-queries", type=int, default=6, help="keywords to search, 1-15 (6)")
    search.add_argument("--force", action="store_true", help="run even if the last search was under 12 hours ago")
    search.add_argument("--dry-run", action="store_true", help="list what would be imported; create no Issues")
    search.add_argument("--export", default="", metavar="FILE", help="also save the cards for linkedin-import")
    search.add_argument("--setup-check", action="store_true", help="check Chrome control and the sign-in, then stop")
    search.add_argument("--keep-browser-open", action="store_true", help="leave the temporary Chrome window open")
    search.set_defaults(handler=_linkedin_search)

    chrome = commands.add_parser("linkedin-import", help="import LinkedIn job cards saved by linkedin-search --export")
    chrome.add_argument("file", help="the file written by radar linkedin-search --export")
    chrome.add_argument("--dry-run", action="store_true", help="report what would be imported; change nothing")
    chrome.set_defaults(handler=_linkedin_import)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
