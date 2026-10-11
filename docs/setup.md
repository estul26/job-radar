# Setup

Your copy must be **private**: the workflows commit your résumés (with your contact details)
and the Issues hold your job search. Create it with **Use this template** (not Fork: a fork of
a public repository has to stay public).

First fill in `config/` and `resumes/master_resume.json` and run `radar doctor`
([configure.md](configure.md)). Until it reports no problems, scheduled scans are skipped
with a warning.

## 1. Secrets and variables

**Settings → Secrets and variables → Actions**

| Secret | Needed for |
|---|---|
| `OPENAI_API_KEY` | AI wording in tailored résumés. Without it, résumés are still generated, deterministically. |
| `LINKEDIN_IMAP_HOST`, `LINKEDIN_IMAP_USER`, `LINKEDIN_IMAP_PASSWORD` | Importing LinkedIn alert emails ([linkedin.md](linkedin.md)). |
| `PROJECTS_TOKEN` | Only for the optional cloud board sync (see below). |

| Variable | Default | Effect |
|---|---|---|
| `GOOD_MATCH_THRESHOLD` | `ranking.good_match_threshold` in `config/search_config.yaml` | Score for a good match: an assigned Issue plus a tailored résumé. |
| `OPENAI_MODEL` | `gpt-6.1-sol` | Model for résumé wording and its fact check. |
| `AI_RESUME_ENABLED` | `true` | Set `false` to always use deterministic résumés. |
| `LINKEDIN_EMAIL_ENABLED` | off | `true` runs the email import every 4 hours. |
| `LINKEDIN_IMAP_PORT`, `LINKEDIN_IMAP_FOLDER` | `993`, `INBOX` | Mailbox details. |

The workflows create the labels they use. Possible matches are scored at
`ranking.possible_match_threshold` (55) and above.

## 2. The Job Search board

A personal GitHub Project shows every job Issue as a card grouped by **Application Status**.
Personal Projects need your own `gh` login with the `project` scope, so setup and sync run
on your Mac.

One-time setup:

```bash
gh auth refresh -s project
python3 tools/project_sync.py setup
```

This creates the **Job Search** project with its fields and links it to the
repository. It's safe to run again. If the board view isn't created for you, add a
**Board** view grouped by **Application Status**.

### Keep the board and the labels in sync

```bash
/bin/zsh tools/mac/install-project-sync-agent.sh
```

A launchd agent then syncs every 2 minutes while the Mac is awake:

- New job Issues become cards, filled in a few at a time.
- **The Issue's `status:*` label is the source of truth.** The sync remembers each card's
  status after the previous run. If only the card moved (you dragged it), the label follows.
  Otherwise the card follows the label. Dragging and relabelling both work, and neither
  undoes the other.
- GitHub throttles bursts of Project writes, so each run makes at most 8 writes. If it is
  throttled anyway, it pauses for 15 minutes.

launchd can't read `~/Downloads`, `~/Documents` or `~/Desktop`, so the installer copies
`tools/project_sync.py` to `~/Library/Application Support/job-radar/` and runs it from
there. **Rerun the installer after pulling changes to it.**

```bash
python3 tools/project_sync.py sync                       # one sync now
tail -f ~/Library/Logs/job-radar-project-sync.log   # its output
/bin/zsh tools/mac/uninstall-project-sync-agent.sh        # remove it
```

**Cloud mode.** `.github/workflows/sync-project-dashboard.yml` can run the same sync in Actions
when your Mac is off. It needs a classic token with the `project` scope saved as
`PROJECTS_TOKEN`, and a schedule restored in the workflow. Frequent schedules use up
private-repository Actions minutes, so the Mac agent is the default.

## 3. A backup trigger for the scans

GitHub can delay or drop scheduled runs. This launchd agent asks GitHub to run
`daily-jobs.yml` at 07:20 and 16:20 local time, and at login if the Mac was off. If you change
the schedules in `daily-jobs.yml`, change `MORNING_HOUR`/`EVENING_HOUR` (and the minutes) at
the top of the installer to match.

```bash
/bin/zsh tools/mac/install-radar-trigger.sh
```

Each morning or evening slot scans once. A successful scan records
`data/radar_<slot>_claim.txt`, and later triggers for that slot skip:

| Trigger | Already scanned this slot today |
|---|---|
| GitHub schedule (07:13, 07:43, 16:13, 16:43 by default) | skips |
| Mac trigger (`skip_if_done=true`) | skips |
| **Run workflow**, or `tools/mac/trigger-radar.sh --force` | always scans, and records the slot |

A scheduled run before noon is the morning scan and any other the evening scan. A Mac trigger
between 12:00 and 15:00 skips, because there is no scan to back up. Logs are in
`~/Library/Logs/job-radar-trigger*.log`. Remove it with
`/bin/zsh tools/mac/uninstall-radar-trigger.sh`.

## 4. Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

`radar scan --fixture my_jobs.json` scores postings saved in a file (in the format of
`tests/fixtures/sample_jobs.json`, which holds nursing jobs) against your `config/`, without
contacting job boards or GitHub. It writes `data/`, `reports/` and `resumes/jobs/` like a real
scan, so don't commit what it changes. Real scans belong to GitHub Actions; use the trigger above
to start one.

The tests use a filled-in setup for a made-up person in `tests/fixtures/`, so they pass
whatever you put in `config/`.
