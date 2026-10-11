# Résumés

`master_resume.json` holds the facts every tailored résumé is built from, and `jobs/` holds one
folder per job. See **[docs/resumes.md](../docs/resumes.md)** for how they are generated and checked.

`index.csv` is rebuilt from the folders and the job Issues by `radar export`; don't edit it.

## Filling in `master_resume.json`

Write your résumé (or CV) in English. The file ships empty, and no résumé is generated
until `identity.name`, `identity.email`, `summary.experience` and at least one experience or
education entry are filled in (`radar doctor` lists what's missing). Write only what is true:
tailoring reorders and selects these facts, and the optional AI step may reword them, but
nothing is ever added.

| Field | What goes in it |
|---|---|
| `version` | Any label; change it when you edit the file, so each résumé records which version it came from. |
| `identity` | Name, headline (e.g. "Registered Nurse \| BLS, ACLS"), location, phone (with your country code if you apply abroad), email, and optional `linkedin`, `github`, `website`. Empty fields are left off the résumé. |
| `summary.experience` | One sentence on your experience, e.g. "Registered Nurse with three years of acute-care experience." |
| `summary.credentials` | One sentence on licences or certifications, or empty. |
| `summary.capabilities` | Short phrases with `tags`; the ones most relevant to a job finish the summary. |
| `technical_skills` | Skill lines: `category` (optional), `text`, `tags` and `priority` (lower comes first when no tag matches the job). The section is titled "Skills". |
| `experience` | Jobs: `role`, optional `company`, `dates`, optional `max_bullets` (default 4), and `bullets`, each with `text` and `tags`. |
| `education` | `program`, `school`, `dates`, optional `bullets`. |
| `certifications` | `text`, `tags`, `priority`. The first four are listed; the rest go on one line. |

**Tags** decide what gets picked for a job. Use the skill names from `matching.skills` in
`config/search_config.yaml` (a tag equal to a skill the posting asks for counts most), plus any
words a posting might use.

A short example:

```json
{
  "version": "2026-01",
  "identity": {"name": "Sam Rivera", "headline": "Registered Nurse | BLS, ACLS",
               "location": "Toronto, ON", "phone": "555-0100", "email": "sam@example.com"},
  "summary": {
    "experience": "Registered Nurse with three years of acute-care experience.",
    "credentials": "BLS and ACLS certified.",
    "capabilities": [
      {"text": "patient assessment", "tags": ["patient assessment"]},
      {"text": "medication administration", "tags": ["medication administration"]}
    ]
  },
  "technical_skills": [
    {"category": "Clinical", "text": "Patient assessment, wound care, IV therapy",
     "tags": ["patient assessment", "wound care"], "priority": 1}
  ],
  "experience": [
    {"role": "Registered Nurse", "company": "Example General Hospital", "dates": "2023 - Present",
     "bullets": [
       {"text": "Assessed and cared for up to six patients per shift on a medical-surgical unit.",
        "tags": ["patient assessment"]}
     ]}
  ],
  "education": [
    {"program": "Bachelor of Science in Nursing", "school": "Example University", "dates": "2019 - 2023"}
  ],
  "certifications": [
    {"text": "Basic Life Support (BLS)", "tags": ["bls"], "priority": 1}
  ]
}
```
