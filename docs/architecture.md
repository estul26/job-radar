# Architecture

## The pipeline

```text
Job boards (twice a day) ──► radar scan ──────────┐
                                                  ├─► score 0–100 ─► job Issue ─► Job Search board
LinkedIn alert emails ─────► radar email-ingest ──┤                     │
Your Chrome (Mac, by hand) ► radar linkedin-search┤                     ├─► résumé for good matches
LinkedIn Job Review form ─────────────────────────┘                     └─► data/applications.csv (export)
```

- **Discovery.** `radar scan` searches the job boards in `search.sites` (Indeed, Glassdoor,
  Google, Naukri, Bayt, BDJobs) through JobSpy. The workflows never touch
  LinkedIn: its own alert emails become `[LinkedIn Alert]` Issues, `radar linkedin-search`
  (run by hand on your Mac) reads search results in your signed-in Chrome, and anything else
  can be submitted with the **LinkedIn Job Review** Issue form. LinkedIn jobs wait for you to
  paste their description before they are scored.
- **Scoring.** `matcher.py` scores every posting 0–100 against `config/resume_profile.json`,
  with the field vocabulary from `config/search_config.yaml` (see [scoring.md](scoring.md)), and
  `models.classify()` turns the score into a verdict: good, possible, low or rejected.
- **Tracking.** Every good and possible match is a GitHub Issue. Its `status:*` label *is*
  the application status. The board mirrors the labels, and `data/applications.csv` is
  exported from them after each scan.
- **Résumés.** Good matches get a tailored résumé generated from `resumes/master_resume.json`.
  AI may reword it only inside fact checks (see [resumes.md](resumes.md)).

## Code

```text
src/job_radar/
  cli.py            radar: one subcommand per workflow step
  commands/
    doctor.py       is config/ filled in? (and resume_ready() for the master résumé)
    scan.py         scan, résumés for good matches, Issues for good + possible matches
    slot.py         which morning/evening slot a daily-jobs.yml run is for
    issue.py        what happens when a job Issue is opened, edited or labelled
    export.py       data/applications.csv and resumes/index.csv from the Issues
    linkedin_search.py   LinkedIn searches in your Chrome, with the account-safety limits
    linkedin_import.py   LinkedIn job cards to [LinkedIn Job] Issues
  settings.py       config + profile + GOOD_MATCH_THRESHOLD + timezone + all paths
  models.py         Job / ScoredJob shapes, Verdict and classify()
  ids.py            fingerprints and LinkedIn job IDs
  issue_body.py     the job Issue body: parse and render (the contract between channels)
  labels.py         statuses and the label catalog
  github.py         the only access to GitHub (gh CLI)
  collector.py      job-board search (JobSpy)
  normalize.py      job-board rows to Job records
  matcher.py        0–100 scoring, and the Vocabulary of your field from config
  report.py         reports/latest.md
  state.py          data/seen_jobs.json
  linkedin_email_ingest.py   LinkedIn alert emails over IMAP
  linkedin_chrome.py         drives a temporary Chrome window through AppleScript
  resume/           tailor (selection), ai (guarded rewording), render (Markdown/DOCX), pipeline
tools/
  project_sync.py   Project board setup and label <-> board sync (runs on your Mac)
  update_from_template.py   a pull request with the template's later changes, for copies of it
  mac/              launchd installers: Project sync agent and the scan backup trigger
```

Each workflow is the same three steps: set up, run one `radar` command, commit with
`.github/actions/commit-state`, which rebases and retries when another workflow pushed first.

| Workflow | Runs | Does |
|---|---|---|
| `daily-jobs.yml` | 07:13 and 16:13 in your timezone (+30 min fallbacks), Mac trigger, manual | `radar doctor`, then `radar scan`, `publish-scan`, `export` |
| `issue-events.yml` | Issue opened, edited or labelled | `radar issue` |
| `linkedin-email-alerts.yml` | every 4 hours | `radar email-ingest` |
| `sync-project-dashboard.yml` | manual (needs `PROJECTS_TOKEN`) | cloud fallback for the board sync |
| `ci.yml` | pushes and pull requests | `pytest`, `ruff` |
| `update-from-template.yml` | manual, in copies of the template | the copy's own `tools/update_from_template.py` (the template's latest only when asked) |

## State

| File | Written by | Notes |
|---|---|---|
| `data/seen_jobs.json` | scan | Postings already reported. Append-only, pruned after 90 days. Committed only once the scan's Issues exist, so a failed run doesn't lose its matches. |
| `data/latest_jobs.csv`, `reports/latest.md` | scan | The latest scan's jobs and report. |
| `data/applications.csv`, `resumes/index.csv` | scan (`radar export`) | Exported from the Issues. Don't edit them. |
| `data/radar_*_claim.txt` | scan | The date each slot last scanned, so duplicate triggers skip. |
| `resumes/jobs/<key>/` | scan, Issue events | One folder per job. Nothing else writes it. |
| `data/linkedin_email_state.json` | email import | IMAP position and already-imported LinkedIn job IDs. |
| `.github/template-version` | Update from template (in its pull request) | The template commits your copy was last updated from. |

Only the scan writes shared files. Issue events commit only their own résumé folder and the
email import only its own state, so concurrent workflows never conflict when they rebase.

### Job identity

- The **fingerprint** (`ids.make_fingerprint`) hashes title, company and location. It
  deduplicates one posting across searches and job boards.
- The **job key** (`ids.job_key`) names a job's résumé folder: the LinkedIn job ID for
  LinkedIn jobs, the fingerprint otherwise.
- Job-board Issues (`[Indeed Job]`, `[Glassdoor Job]`, `[Naukri Job]`, …, labelled
  `source:<board>`) carry their fingerprint in a hidden `<!-- job-fingerprint:… -->` marker.
  `labels.BOARDS` names the boards.
