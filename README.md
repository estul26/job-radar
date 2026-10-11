# Job Radar

**English** | [简体中文](README.zh-CN.md)

Finds jobs in **any field** twice a day, scores each one against your skills and experience, and
tracks the promising ones as GitHub Issues, with a tailored, fact-checked résumé for every good
match. You describe your field, your city and yourself in three files; nothing in the code is
specific to one kind of job.

```text
Indeed, twice a day ───────────┐
LinkedIn alert emails ─────────┤
LinkedIn in your Chrome (Mac) ─┼─► score 0–100 ─► job Issue ─► Job Search board
LinkedIn Job Review form ──────┘                    │
                                                    └─► tailored résumé for good matches
```

- **Discovery.** GitHub Actions search Indeed twice a day in your timezone. LinkedIn jobs come
  from its own alert emails, from `radar linkedin-search` (run by hand on your Mac, in your own
  signed-in Chrome), or from the **LinkedIn Job Review** Issue form.
- **Scoring.** Deterministic and explainable: title, experience, skills, certifications,
  freshness and location, using the titles, skills and places you configure. See
  [docs/scoring.md](docs/scoring.md).
- **Tracking.** Every good and possible match is an Issue; good ones are assigned to you. Its
  `status:*` label is the application status: change it or drag the card on the board.
  `data/applications.csv` is exported from the Issues after each scan.
- **Résumés.** Good matches get a résumé built from `resumes/master_resume.json`. AI may reword
  it, but only when the wording passes fact checks. See [docs/resumes.md](docs/resumes.md).

It never applies for you or messages anyone.

## Get started

1. **Use this template → Create a new repository**, and make it **Private**. Your copy will hold
   your résumés and job search. Don't fork: a fork of a public repository has to stay public.
2. Fill in your setup ([docs/configure.md](docs/configure.md)):
   - `config/search_config.yaml`: your timezone, job titles, places and the skills of your field
   - `config/resume_profile.json`: your years of experience, skills and certifications
   - `resumes/master_resume.json`: the facts your résumés are built from ([how](resumes/README.md))
   - the `timezone:` lines in `.github/workflows/daily-jobs.yml` and `linkedin-email-alerts.yml`
3. Check it:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   radar doctor
   ```

   Until `radar doctor` reports no problems, the scheduled scans skip themselves with a
   warning.
4. Optionally add the secrets in [docs/setup.md](docs/setup.md): an OpenAI key for AI résumé
   wording, a mailbox for LinkedIn alerts.
5. **Actions → Daily Job Radar → Run workflow** to scan once, then read `reports/latest.md`.
6. Optional: [LinkedIn alerts and the Chrome search](docs/linkedin.md), the [board sync and
   the Mac scan trigger](docs/setup.md#2-the-job-search-board).

## Commands

| Command | Does |
|---|---|
| `radar doctor` | Check that `config/` and the master résumé are filled in |
| `radar scan [--fixture FILE]` | Search, score and record new jobs; résumés for good Indeed matches |
| `radar publish-scan` | An Issue for each good and possible Indeed match |
| `radar export` | Rebuild `data/applications.csv` and `resumes/index.csv` from the Issues |
| `radar issue N --event E [--label L] [--publish]` | Handle an Issue being opened, edited or labelled |
| `radar email-ingest` | Import LinkedIn alert emails |
| `radar linkedin-search [...]` | Search LinkedIn in your signed-in Chrome (Mac, by hand) and import the cards |
| `radar linkedin-import FILE` | Import cards saved by `linkedin-search --export` |
| `radar scan-slot …`, `radar record-claim …` | Morning/evening deduplication for `daily-jobs.yml` |

Try a scan offline (this changes `data/` and `reports/`, so don't commit the result):

```bash
radar scan --fixture tests/fixtures/sample_jobs.json
pytest && ruff check .
```

## Configure

| What | Where |
|---|---|
| Timezone, searches, places, title filters, thresholds | `config/search_config.yaml` |
| The skills, certifications and title words of your field | `matching` in `config/search_config.yaml` |
| Skills and certifications you really have | `config/resume_profile.json` |
| Facts every résumé is built from | `resumes/master_resume.json` |
| Good-match threshold | repository variable `GOOD_MATCH_THRESHOLD` |
| Scan times | `.github/workflows/daily-jobs.yml` |

Change the profile and master résumé only when something is truly new. Adding a skill to
raise scores just leads to résumés you can't stand behind.

## Docs

- [Configure](docs/configure.md): every setting, with a worked example
- [Setup](docs/setup.md): secrets, variables, the board and its sync, the Mac scan trigger
- [LinkedIn](docs/linkedin.md): alert import, the Chrome search, the Issue form, what scoring does
- [Résumés](docs/resumes.md): generation, AI guardrails, audit, privacy
- [Scoring](docs/scoring.md): points, verdicts, hard rejects
- [Architecture](docs/architecture.md): pipeline, code layout, state files

## Before you use it

- **You're responsible for following each job site's terms.** Indeed is searched through
  [JobSpy](https://pypi.org/project/python-jobspy/). `radar linkedin-search` drives your own
  LinkedIn account, which LinkedIn's terms forbid; it is kept small and slow and runs only by
  hand, but use it at your own risk.
- **Read every résumé before you send it.** AI wording is fact-checked against your master
  résumé, but you're the one applying.
- **Keep your copy private.** It holds your contact details and your job search.

## Limitations

- Job boards change markup and rate-limit; one failing search doesn't stop the scan.
- Scoring is keyword-based, so it's explainable but not semantic. It only knows the skills you
  list in `matching`.
- Indeed is the only automated source. ZipRecruiter blocks GitHub's runners, and LinkedIn is
  covered by its alerts and the Chrome search.

## License

[MIT](LICENSE)
