# LinkedIn jobs

Job Radar's workflows never log into LinkedIn, scrape it, message anyone, or apply for you.
LinkedIn jobs reach it in three ways:

1. **Alert emails.** LinkedIn's own job alerts, imported every 4 hours as `[LinkedIn Alert]` Issues.
2. **The Issue form.** **Issues → New issue → LinkedIn Job Review** for any posting you find yourself.
3. **The Chrome search (optional, Mac, by hand).** `radar linkedin-search` reads LinkedIn search
   results in your own signed-in Chrome and turns new cards into `[LinkedIn Job]` Issues.

Either way the job ends up scored, with a review comment, labels and (for good matches) a
tailored résumé.

## Alert emails

```text
LinkedIn job alert email
   ↓  every 4 hours (linkedin-email-alerts.yml)
[LinkedIn Alert] <title> — <company> Issue, labelled needs:description
   ↓  you paste the full description into the Issue and save it
scored: review comment, match:* and status:* labels, résumé for good matches
```

Alert emails only show job cards, which isn't enough to score fairly. So you paste the
description once:

1. Open the `[LinkedIn Alert]` Issue (filter by the `needs:description` label).
2. Open the LinkedIn posting from the Issue's job URL and copy the full description.
3. Edit the Issue: replace the line
   `_Paste full job description here, replacing this line, then save the issue._`
   with the description, and save.

The importer skips titles that are neither in `search.titles` nor related through
`matching.related_title_keywords`, titles in `search.exclude_title_terms` or
`ranking.hard_reject_title_terms`, digest headers such as "Jobs similar to …", jobs already
imported, and jobs that already have an Issue (for example one you submitted through the form).

### Set it up

1. Create a mailbox (or a mail rule) that receives LinkedIn's job-alert emails. A dedicated
   mailbox with an app-specific password limits what the workflow can read.
2. Add the secrets `LINKEDIN_IMAP_HOST`, `LINKEDIN_IMAP_USER` and `LINKEDIN_IMAP_PASSWORD`.
   Common hosts: `imap.gmail.com`, `imap.mail.me.com`, `outlook.office365.com`.
3. Set the variable `LINKEDIN_EMAIL_ENABLED` to `true`. Optionally set
   `LINKEDIN_IMAP_PORT` (`993`) and `LINKEDIN_IMAP_FOLDER` (`INBOX`).

Only messages from a `linkedin.com` sender are read, whatever the subject; only their job links
whose titles match the search titles become Issues.

### When nothing is imported

Each run's report (`reports/linkedin-email-latest.md`) lists every email it read and what
happened to it: not from LinkedIn, no job links, or how many jobs were new, off-target or
already imported. To check without changing anything, run **Actions → Import LinkedIn Job
Alerts → Run workflow** with **dry run** ticked and **days** set to, say, `7`; the run's log
shows what each email of the past week would import. Locally:

```bash
radar email-ingest --dry-run --days 7
```

Untick dry run (keeping **days**) to import what the cursor already moved past.

### Suggested alerts

Set each alert to **Daily** and **LinkedIn + Email**, with your experience level. You can have
up to 20 alerts. Good alerts mirror `config/search_config.yaml`:

- **One alert per main title, per place.** Your `search.titles` (or close groups of them) in
  each of your `search.locations`, plus a remote alert if you want remote work.
- **Neighbouring titles.** The roles in `matching.related_title_keywords` that you'd take.
- **Skills-based.** An alert on two or three of your strongest `matching.skills`, which finds
  postings with titles you didn't think of.

Where LinkedIn still accepts Boolean search, one alert can cover several titles and leave out
what `search.exclude_title_terms` leaves out:

```text
("Registered Nurse" OR "Staff Nurse" OR "Charge Nurse") NOT ("Nursing Assistant" OR "Veterinary")
```

## The Chrome search

`radar linkedin-search` runs a few LinkedIn job searches in **your own signed-in Google Chrome**,
on your Mac, and imports the cards it sees. It searches each of `search.queries` (or
`search.titles`) in each `search.locations` entry that has a `linkedin:` location:

```yaml
locations:
  - name: Bengaluru
    query: Bengaluru
    linkedin: Bengaluru, Karnataka, India   # what LinkedIn's location box gets
  - name: Remote
    query: India
    remote_only: true                       # LinkedIn's "Remote" filter
    linkedin: India
```

New cards whose titles pass the same filter as alert emails become `[LinkedIn Job]` Issues
labelled `needs:description`; jobs that already have an Issue are skipped. Cards carry no
description, so paste it in as for an alert.

```bash
radar linkedin-search --setup-check      # Chrome control and the LinkedIn sign-in, then stop
radar linkedin-search --dry-run          # search, and list what would be imported
radar linkedin-search --posted 24h       # search and import postings from the last day
```

| Option | Effect |
|---|---|
| `--posted 24h\|3d\|7d\|30d` | Posting age (default `7d`). |
| `--max-queries N` | Keywords to search, 1–15 (default 6). Each is one search per LinkedIn location. |
| `--dry-run` | List what would be imported; create no Issues. |
| `--export FILE` | Also save the cards; `radar linkedin-import FILE` imports them later. |
| `--force` | Run even though the last search was under 12 hours ago. |
| `--keep-browser-open` | Leave the temporary Chrome window open. |

### First run

1. Sign in to LinkedIn in Google Chrome.
2. In Chrome, turn on **View → Developer → Allow JavaScript from Apple Events**.
3. Run `radar linkedin-search --setup-check`, and allow your terminal app to control Chrome when
   macOS asks (or in **System Settings → Privacy & Security → Automation**).

**Turn Allow JavaScript from Apple Events off again after each search.** While it's on, any app
allowed to control Chrome can run code in every tab.

Use LinkedIn with its display language set to English, like the rest of Job Radar.

### Keep your account safe

This automates your real LinkedIn account, **which LinkedIn's terms forbid**, so use it at your
own risk and sparingly. It is built to stay small and slow:

- It only reads search pages. It never applies, saves, messages or follows.
- At most 6 keywords by default (15 at most), random 4–9 second pauses between searches, and
  a few scrolls per search.
- It stops at the first LinkedIn security check. Complete the check in Chrome, then wait.
- It refuses to run again within 12 hours (`--force` overrides) and refuses to run in GitHub
  Actions or any CI. Run it by hand; don't put it on a schedule.

## The Issue form

Paste the job URL, title, company, location, remote yes/no and the **full** description, then
submit. Scoring starts as soon as the Issue is saved.

## What scoring does

`issue-events.yml` runs `radar issue` whenever a LinkedIn job Issue is opened or edited:

- It posts (or updates) one **review comment** with the score, the recommendation, matched
  and missing skills, and the score notes.
- It sets `source:linkedin` and one `match:*` label: `good`, `possible`, `low` or `rejected`.
- It sets `status:new` for good and possible matches. Low and rejected matches get
  `status:skipped` and the Issue is closed.
- It generates a **tailored résumé** for good matches ([resumes.md](resumes.md)) and adds `resume:ready`.

Re-scoring (after you edit the description, say) never replaces a status you chose: only the
statuses scoring sets itself (`new`, `skipped`) are updated.

When you apply, set `status:applied` (or drag the card on the board). Each Issue keeps one
status label. Rejected, offer and skipped close the Issue; the others keep it open.
