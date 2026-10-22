# Job Radar

**English** | [简体中文](README.zh-CN.md)

Finds jobs in **any field, in any country**, twice a day. It scores each one against your skills
and experience, and tracks the promising ones as GitHub Issues, with a tailored, fact-checked
résumé (CV) for every good match. You describe your field, your place and yourself in three
files; nothing in the code is specific to one kind of job or country. Job postings and résumés
are in English.

```text
Job boards, twice a day ───────┐
LinkedIn alert emails ─────────┤
LinkedIn in your Chrome (Mac) ─┼─► score 0–100 ─► job Issue ─► Job Search board
LinkedIn Job Review form ──────┘                    │
                                                    └─► tailored résumé for good matches
```

- **Discovery.** GitHub Actions search the job boards twice a day in your timezone: Indeed in
  about 70 countries, plus Glassdoor, Google Jobs and regional boards such as Naukri (India),
  Bayt (Middle East) and BDJobs (Bangladesh). LinkedIn jobs come from its own
  alert emails, from `radar linkedin-search` (run by hand on your Mac, in your own signed-in
  Chrome), or from the **LinkedIn Job Review** Issue form.
- **Scoring.** Deterministic and explainable: title, experience, skills, certifications,
  freshness and location, using the titles, skills and places you configure. See
  [docs/scoring.md](docs/scoring.md).
- **Tracking.** Every good and possible match is an Issue; good ones are assigned to you. Its
  `status:*` label is the application status: change it or drag the card on the board.
  `data/applications.csv` is exported from the Issues after each scan.
- **Résumés.** Good matches get a résumé built from `resumes/master_resume.json`. AI may reword
  it, but only when the wording passes fact checks. See [docs/resumes.md](docs/resumes.md).

It never applies for you or messages anyone. Everything runs on GitHub Actions, so it works from
any computer (Windows, Linux or Mac); only the optional Chrome search and backup scan trigger need
a Mac.

## Quick start (no coding)

Everything below happens on the GitHub website. It takes about 20 minutes.

1. **Make your own copy.** [Sign up for GitHub](https://github.com/signup) (free), then on this
   page click **Use this template → Create a new repository**. Give it a name, choose
   **Private**, and click **Create repository**. Work in your copy from now on.
2. **Describe the jobs you want.** In your copy, open `config/search_config.yaml` and click the
   pencil icon (**Edit this file**). Lines starting with `#` are notes, and the indented ones right
   under each setting are examples, like `#  - Accountant`. To use an example, delete its `#` only
   (keep the spaces), and delete the `[]` or `{}` after that setting's name. Then:
   - set `timezone`, e.g. `timezone: Europe/London` ([list of names](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones));
   - set your country, e.g. `country_indeed: "UK"`;
   - under `titles`, list the job titles you want, one per line starting with `- `;
   - under `locations`, add where you want to work, copying the example's layout;
   - under `matching` → `skills`, list the skills job ads in your field ask for.

   Click **Commit changes**, then **Commit changes** again.
3. **Describe yourself.** Edit `config/resume_profile.json` the same way. Keep the quotes and
   commas exactly as shown; skill names must match the ones you listed under `skills`:

   ```json
   {
     "profile_name": "Accountant",
     "experience_years": 3,
     "certifications": ["AAT"],
     "skills": ["xero", "excel", "month-end close"]
   }
   ```

4. **Add your résumé facts (optional).** Fill in `resumes/master_resume.json` to get a tailored
   résumé for each good match ([how](resumes/README.md)). Skip this and you still get the job
   matches.
5. **Run it.** Open the **Actions** tab, click **Daily Job Radar** on the left, then
   **Run workflow → Run workflow**. After a few minutes, open the run and read its **Summary**:
   - "Set up Job Radar first" lists what is still missing. Fix those lines and run it again.
   - Otherwise it shows the jobs it found, and the **Issues** tab has one Issue per match. Good
     matches are assigned to you, so GitHub emails you about them.
6. **Track your applications.** On each job Issue, change its `status:` label (for example to
   `status:applied`) as you go. From now on the radar scans twice a day by itself.

If GitHub emails you that **CI failed** after you edit a file, there's a typo in it (often a
missing quote, comma or space). Open the failed run to see which file.

Optional: scans run at about 7 am and 4 pm UTC. To run them at those times in your own timezone,
change the four `'UTC'` in `.github/workflows/daily-jobs.yml` to your timezone, e.g.
`'Europe/London'`. For AI-polished résumé wording, add an OpenAI key as described in
[docs/setup.md](docs/setup.md).

**Getting the template's fixes later.** Your copy doesn't change when this template gets fixes and
improvements. To bring them in, open **Actions → Update from template → Run workflow**. It opens a
pull request with the changes: look through it and click **Merge pull request**. It never changes
your settings, résumé or job data (`config/`, `resumes/master_resume.json`, `resumes/jobs/`,
`data/`, `reports/`). Workflow files it isn't allowed to change are listed in the pull request,
with what to paste. More in [docs/setup.md](docs/setup.md#5-updates-from-the-template).

## Get started (on your computer)

For developers, or to check your setup before you push it.

1. **Use this template → Create a new repository**, and make it **Private**. Your copy will hold
   your résumés and job search. Don't fork: a fork of a public repository has to stay public.
2. Fill in your setup ([docs/configure.md](docs/configure.md)):
   - `config/search_config.yaml`: your timezone, country, job boards, job titles, places, and the
     skills of your field
   - `config/resume_profile.json`: your years of experience, skills and certifications
   - `resumes/master_resume.json`: the facts your résumés are built from ([how](resumes/README.md))
   - the `timezone:` lines in `.github/workflows/daily-jobs.yml` and `linkedin-email-alerts.yml`
3. Check it:

   ```bash
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   radar doctor
   ```

   Until `radar doctor` reports no problems, the scheduled scans skip themselves with a
   warning. No Python on your computer? Follow the [quick start](#quick-start-no-coding) instead:
   the workflow's summary shows the same `radar doctor` report.
4. Optionally add the secrets in [docs/setup.md](docs/setup.md): an OpenAI key for AI résumé
   wording, a mailbox for LinkedIn alerts.
5. **Actions → Daily Job Radar → Run workflow** to scan once, then read `reports/latest.md`.
6. Optional: [LinkedIn alerts and the Chrome search](docs/linkedin.md), the [board sync and
   the Mac scan trigger](docs/setup.md#2-the-job-search-board).
7. Later, bring in the template's fixes with **Actions → Update from template**
   ([how](docs/setup.md#5-updates-from-the-template)).

## Commands

| Command | Does |
|---|---|
| `radar doctor` | Check that `config/` and the master résumé are filled in |
| `radar scan [--fixture FILE]` | Search, score and record new jobs; résumés for good matches |
| `radar publish-scan` | An Issue for each good and possible match, named after its job board |
| `radar export` | Rebuild `data/applications.csv` and `resumes/index.csv` from the Issues |
| `radar issue N --event E [--label L] [--publish]` | Handle an Issue being opened, edited or labelled |
| `radar email-ingest` | Import LinkedIn alert emails |
| `radar linkedin-search [...]` | Search LinkedIn in your signed-in Chrome (Mac, by hand) and import the cards |
| `radar linkedin-import FILE` | Import cards saved by `linkedin-search --export` |
| `radar scan-slot …`, `radar record-claim …` | Morning/evening deduplication for `daily-jobs.yml` |

Check your scoring offline: save a few postings you'd apply for in the format of
`tests/fixtures/sample_jobs.json`, then run a scan on them (this changes `data/`, `reports/` and
`resumes/jobs/`, so don't commit the result):

```bash
radar scan --fixture my_jobs.json
pytest && ruff check .
```

## Configure

| What | Where |
|---|---|
| Timezone, country, job boards, searches, places, title filters, thresholds | `config/search_config.yaml` |
| The skills, certifications and title words of your field | `matching` in `config/search_config.yaml` |
| Skills and certifications you really have | `config/resume_profile.json` |
| Facts every résumé is built from | `resumes/master_resume.json` |
| Good-match threshold | repository variable `GOOD_MATCH_THRESHOLD` |
| Scan times | `.github/workflows/daily-jobs.yml` |

Change the profile and master résumé only when something is truly new. Adding a skill to
raise scores just leads to résumés you can't stand behind.

## Docs

- [Configure](docs/configure.md): every setting, your country, worked examples
- [Setup](docs/setup.md): secrets, variables, the board and its sync, the Mac scan trigger,
  updates from the template
- [LinkedIn](docs/linkedin.md): alert import, the Chrome search, the Issue form, what scoring does
- [Résumés](docs/resumes.md): generation, AI guardrails, audit, privacy
- [Scoring](docs/scoring.md): points, verdicts, hard rejects
- [Architecture](docs/architecture.md): pipeline, code layout, state files

## Before you use it

- **You're responsible for following each job site's terms.** Job boards are searched through
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
- Automated searches cover the boards JobSpy supports. ZipRecruiter (USA and Canada) blocks
  GitHub's runners, and LinkedIn is covered by its alerts and the Chrome search.
- English only: job postings in other languages won't score well, and résumés use English
  headings.

## License

[MIT](LICENSE)
