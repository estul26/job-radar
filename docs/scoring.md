# Scoring

Each posting is scored 0–100 by `matcher.py` against `config/resume_profile.json`, using the
words of your field from the `matching` section of `config/search_config.yaml`
([configure.md](configure.md)). The score is deterministic, so the same posting always gets the
same score, and the reasons are listed on every report entry and review comment.

| Component | Points | How |
|---|---:|---|
| Title | 30 | Contains one of `search.titles` as whole words; otherwise 24 for two or more `matching.related_title_keywords`, 15 for one |
| Experience | 15 | Minimum years the posting asks for, against your `experience_years`; 10 when it isn't stated |
| Skills | 35 | Share of the core `matching.skills` it requires that your profile has. A posting naming fewer than 3 counts only partly (1 of 1 matched is 24, 2 of 2 is 29); 18 when none are detected |
| Certifications | 10 | Share of the `matching.certifications` it mentions that you hold; 5 when none are mentioned |
| Freshness | 5 | Posted within `ranking.fresh_hours` (24 h); less as it ages |
| Location | 5 | `ranking.remote_score` for a remote job; otherwise the `score` of the best `search.locations` entry whose `match` phrases are in its location; 1 when none match |

Skills listed after a "nice to have" or "preferred qualifications" heading are reported as
optional gaps and don't lower the score. `matching.soft_skills` (communication, say) don't count
as core requirements either: a missing one is reported with the optional gaps.

`matching.context_title_keywords` count towards the title only when the title also has one of
`matching.context_words`. That keeps a common word from making an unrelated title look like
yours: with `care` as a context keyword and `patient` as a context word, "Patient Care
Coordinator" is related to nursing and "Customer Care Agent" isn't.

## Verdicts

| Verdict | Rule | What happens |
|---|---|---|
| **good** | score ≥ `GOOD_MATCH_THRESHOLD` | Issue (assigned to you), `match:good`, `status:new`, tailored résumé |
| **possible** | score ≥ `ranking.possible_match_threshold` (55) | Issue, `match:possible`, `status:new`; add `resume:tailor` for a résumé |
| **low** | below that | Report only; a LinkedIn Issue gets `match:low` and `status:skipped` and is closed |
| **rejected** | a hard-reject rule | Listed under "Automatically excluded"; a LinkedIn Issue gets `match:rejected` and is closed |

`GOOD_MATCH_THRESHOLD` is a repository variable. Without it, `ranking.good_match_threshold` in
`config/search_config.yaml` applies. A scan opens Issues for at most `ranking.max_good_matches`
(10) good and `ranking.max_possible_matches` (5) possible matches, best first. Good matches over
the limit are listed in the report and come up again in the next scan.

## Hard rejects

- A title containing a `ranking.hard_reject_title_terms` entry (seniority you're not ready for,
  say), matched on word boundaries, so "lead" doesn't match "Leading".
- A title that is neither one of `search.titles` nor related through `matching`, when
  `ranking.hard_reject_unrelated_titles` is on.
- A minimum requirement of `ranking.hard_reject_min_years` (5) or more years.

`search.exclude_title_terms` are rejected the same way, wherever the job came from, and job-board
searches drop them even earlier, before they are scored or reported.

## Limitations

- Only skills in `config/resume_profile.json` earn credit. A skill a posting asks for that you
  don't have shows as missing until you truly have it; add it to the profile only then.
- Only skills listed in `matching.skills` are detected at all. `radar doctor` warns about
  profile skills that aren't there, since they could never match.
- The experience parser is conservative and won't understand every wording.
- It is keyword matching, not semantic: explainable, but it can miss paraphrased requirements.
