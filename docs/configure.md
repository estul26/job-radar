# Configure it for your job search

Three files describe you and the jobs you want. They ship empty; fill them in, then run
`radar doctor` until it reports no problems.

| File | What it says |
|---|---|
| `config/search_config.yaml` | Where and what to search, how to score, and the words of your field |
| `config/resume_profile.json` | Your years of experience, skills and certifications |
| `resumes/master_resume.json` | The facts your tailored résumés are built from ([resumes/README.md](../resumes/README.md)) |

Then match the workflows to your timezone: set the `timezone:` lines in
`.github/workflows/daily-jobs.yml` and `linkedin-email-alerts.yml` to the same value as
`timezone` in `search_config.yaml`.

## How phrases match

Titles, skills, keywords and location `match` entries are **phrases**, in any language. A phrase
matches whole words, ignoring case and extra spaces: `nurse` matches "Registered Nurse" but not
"Nursery", and `c++` matches "C++ developer". A phrase starting with `re:` is a Python regular
expression instead; put it in single quotes so YAML leaves backslashes alone:
`'re:buchhalter(in)?'`, `'re:tcp/?ip'`, `'re:escalat'` (escalate, escalation, escalating).

## `search_config.yaml`

### `timezone`

An [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) such as
`Europe/Berlin`, `Asia/Kolkata`, `America/Chicago`, `Africa/Lagos` or `Australia/Sydney`. Report
dates and the morning/evening scan slots use it.

### `search`

| Key | Meaning |
|---|---|
| `sites` | Job boards for JobSpy: `indeed`, and any in [your country and language](#your-country-and-language). |
| `country_indeed` | The country Indeed and Glassdoor search: `Germany`, `India`, `UK`, `USA`, `Brazil`, … |
| `queries` | What to type into the job board's search box. Broad is fine. Empty: search the `titles`. |
| `titles` | The job titles you want. A posting whose title contains one gets full title points. |
| `exclude_title_terms` | Titles dropped before scoring: jobs that share a word with yours but aren't yours. |
| `locations` | Where to search, and how much each place is worth (below). |
| `results_wanted_per_query`, `hours_old`, `fetch_description`, `pause_seconds_between_queries` | How much to fetch per search. The defaults are fine. |

Each `locations` entry:

| Key | Meaning |
|---|---|
| `name` | Shown in reports ("Toronto location"). |
| `query` | What the job board's location box gets. |
| `remote_only` | `true` asks the job board for remote jobs only. |
| `score` | Location points (out of 5) when a job's location matches. Default 5. |
| `match` | Phrases that mean a job is in this place. Default: the `name`. |
| `linkedin` | The location text for `radar linkedin-search` ([linkedin.md](linkedin.md)). Optional. |

A job gets the best `score` among the entries it matches, `ranking.remote_score` if it's remote,
and 1 point if it matches none.

### `ranking`

| Key | Default | Meaning |
|---|---|---|
| `good_match_threshold` | 65 | A good match: an Issue assigned to you and a tailored résumé. The `GOOD_MATCH_THRESHOLD` variable overrides it. |
| `possible_match_threshold` | 55 | A possible match: an Issue, but no résumé. |
| `max_possible_matches` | 5 | Possible matches per scan that get an Issue. |
| `fresh_hours` | 24 | Postings this new get full freshness points. |
| `remote_score` | 5 | Location points for a remote job. |
| `hard_reject_unrelated_titles` | true | Reject titles that are neither in `titles` nor related through `matching`. |
| `hard_reject_title_terms` | | Reject titles containing these, e.g. `senior`, `manager`. |
| `hard_reject_min_years` | 5 | Reject postings that ask for this many years or more. |

### `matching`

The words of your field. Scoring finds them in postings and compares them with your profile.

| Key | Meaning |
|---|---|
| `skills` | Each skill, and the phrases that mean a posting asks for it. A skill with no phrases (`wound care: []`) is looked for by its own name. |
| `soft_skills` | Skill names nearly every posting mentions. They're reported but aren't core requirements. |
| `certifications` | Each certification or licence, and the phrases that mean a posting asks for it. |
| `related_title_keywords` | Words that make a title related when it isn't one of your `titles`. |
| `context_title_keywords`, `context_words` | Words that count as related only next to a context word. |
| `years_words`, `range_words`, `optional_section_phrases` | How postings in your language say "5 years", "3 to 5 years" and "nice to have" ([below](#your-country-and-language)). |

**Choosing skills.** Read ten postings you'd apply for and list the tools, techniques and
knowledge they ask for, including ones you don't have yet. A skill you lack still belongs in
`matching.skills`: that's how a posting's requirement shows up as missing. Then put the ones
you truly have in `resume_profile.json`, using the same names.

## Your country and language

Nothing in Job Radar is tied to one country or language. Three things depend on where you are.

**Job boards.** Indeed covers the most countries, and works from GitHub's servers. Set
`country_indeed` to one of: Argentina, Australia, Austria, Bahrain, Bangladesh, Belgium,
Bulgaria, Brazil, Canada, Chile, China, Colombia, Costa Rica, Croatia, Cyprus, Czech Republic,
Denmark, Ecuador, Egypt, Estonia, Finland, France, Germany, Greece, Hong Kong, Hungary, India,
Indonesia, Ireland, Israel, Italy, Japan, Kuwait, Latvia, Lithuania, Luxembourg, Malaysia,
Malta, Mexico, Morocco, Netherlands, New Zealand, Nigeria, Norway, Oman, Pakistan, Panama,
Peru, Philippines, Poland, Portugal, Qatar, Romania, Saudi Arabia, Singapore, Slovakia,
Slovenia, South Africa, South Korea, Spain, Sweden, Switzerland, Taiwan, Thailand, Türkiye,
Ukraine, United Arab Emirates, UK, USA, Uruguay, Venezuela or Vietnam. Add to `sites`, if you
like:

| Site | Where |
|---|---|
| `glassdoor` | Many of the countries above (`radar doctor` warns if yours isn't one) |
| `google` | Google Jobs, wherever it's available |
| `naukri` | India |
| `bayt` | The Gulf and the Middle East |
| `bdjobs` | Bangladesh |
| `hellowork` | France |

Job boards change what they allow; if one keeps failing, the scan report's "Collector warnings"
say so, and the other boards still run. LinkedIn is never searched from GitHub: use its alert
emails or `radar linkedin-search` ([linkedin.md](linkedin.md)).

**Language of the postings.** Write `queries`, `titles`, skills and certifications in the
language the postings use, or in several (`[buchhaltung, accounting]`). English experience and
"nice to have" wording is always understood; add your language's:

```yaml
matching:
  years_words: [jahre, jahren]          # "mindestens 3 Jahre"
  range_words: [bis]                    # "2 bis 4 Jahre"
  optional_section_phrases: [von vorteil, wünschenswert]   # what follows is nice to have
```

Spanish might be `[años, año]`, `[a]` and `[deseable, valorable]`; French `[ans, an]`, `[à]`
and `[un plus, un atout, souhaité]`.

**Language of your résumé.** The résumé's headings come from `labels` in
`resumes/master_resume.json`; translate them, and write the facts in the same language. The AI
step keeps the résumé's language even when a posting is in another one.

## `resume_profile.json`

| Key | Meaning |
|---|---|
| `experience_years` | Whole years of experience in your field, compared with what postings ask for. |
| `skills` | Skills you really have, named as in `matching.skills`. |
| `certifications` | Certifications you hold, named as in `matching.certifications`. |
| `profile_name` | A label for yourself; not used in scoring. |

Add a skill only when it's true. Adding one to raise scores leads to résumés you can't stand
behind.

## An example

`config/search_config.yaml` ships with a commented example for an accountant in Berlin who reads
postings in German and English. Here is another: a registered nurse in Toronto, looking locally
and remotely across Canada:

```yaml
timezone: America/Toronto

search:
  sites: [indeed]
  country_indeed: Canada
  queries: [Registered Nurse, RN]
  titles: [Registered Nurse, Staff Nurse, Charge Nurse]
  exclude_title_terms: [nursing assistant, veterinary]
  locations:
    - {name: Toronto, query: "Toronto, ON", score: 5, match: [toronto, mississauga], linkedin: "Toronto, Ontario, Canada"}
    - {name: Ontario, query: Ontario, score: 4, match: [ontario, 're:,\s*on\b']}
    - {name: Remote, query: Canada, remote_only: true, score: 3, match: [canada], linkedin: Canada}

ranking:
  hard_reject_title_terms: [manager, director]

matching:
  skills:
    patient assessment: [patient assessment, assess patients]
    medication administration: [medication administration, administer medication]
    epic: [epic, epic emr]
    wound care: []
    communication: []
  soft_skills: [communication]
  certifications:
    BLS: [bls, basic life support]
    ACLS: [acls]
  related_title_keywords: [nurse, nursing, rn]
  context_title_keywords: [care]
  context_words: [patient, clinical]
```

```json
{
  "profile_name": "Registered Nurse",
  "experience_years": 2,
  "skills": ["patient assessment", "medication administration", "wound care", "communication"],
  "certifications": ["BLS"]
}
```

With this, a "Registered Nurse - Medical/Surgical" posting in Toronto that asks for two years,
patient assessment, medication administration, wound care and BLS scores 97. One that also asks
for Epic and ACLS scores 83 and lists both as missing.
