# Tailored résumés

Every good match gets a job-specific résumé built from **`resumes/master_resume.json`**, the
factual source of truth ([how to fill it in](../resumes/README.md)). Edit the master only when
something is actually true. Never add a skill or achievement because a posting asks for it.

The master ships empty. Until it has your name, email, an experience summary and at least one
job or course, scans still run but no résumé is generated (`radar doctor` lists what's missing).

## When a résumé is generated

- **Good LinkedIn matches**, when their Issue is scored.
- **Good Indeed matches**, by the scan, before their Issue is opened.
- **Any job Issue you label `resume:tailor`.** Useful for a possible match, or after you
  update the master. The label is replaced by `resume:ready` when it's done.

The Issue gets a comment linking the Markdown and DOCX files.

## Files

```text
resumes/jobs/<job key>-<company>-<role>/
├── resume.md            readable source
├── resume.docx          the file to send
├── tailoring_notes.md   what was emphasized, and which missing skills were NOT added
├── metadata.json        job, Issue, score, master version, AI result, file paths
└── ai_audit.json        everything the AI step proposed and why it was accepted or rejected
```

The job key is the LinkedIn job ID for LinkedIn jobs and the job's fingerprint otherwise, so
regenerating a job replaces its folder. `resumes/index.csv` lists every folder with its job's
current status. It is rebuilt from the folders and Issues by `radar export` after each scan.

## How a résumé is made

```text
master résumé + job description
   ↓ deterministic tailoring: order skills, pick the most relevant bullets, build the summary
   ↓ AI editor (optional): reword the summary and the selected bullets, citing source facts
   ↓ rule checks: no new skills, certifications, numbers or oversized rewrites
   ↓ AI fact checker: every claim supported by its cited fact
   ↓
pass → AI wording        fail or any error → the deterministic résumé
```

Deterministic tailoring may reorder skill categories, bullets and certifications, select
bullets, and compose the summary from capability phrases already in the master. Nothing can
add a tool, metric, responsibility, certification or year of experience the master doesn't have.
The rule checks know your field's skills and certifications from `matching` in
`config/search_config.yaml`, so keep that list complete.

The AI step can only reword the summary and the already-selected bullets. It never touches
contact details, role titles, dates, the skills inventory, certifications or education.

### Setup

| Setting | Kind | Default |
|---|---|---|
| `OPENAI_API_KEY` | secret | none: deterministic résumés only |
| `OPENAI_MODEL` | variable | `gpt-6.1-sol` |
| `AI_RESUME_ENABLED` | variable | `true` |

A résumé with AI wording costs two model calls: editor and fact checker. Scanning and scoring
never call the model.

### Audit statuses (`ai_audit.json`)

| Status | Meaning |
|---|---|
| `ai_validated` | AI wording passed both checks and was used. |
| `fallback_missing_api_key` | No API key. |
| `fallback_rule_validation_failed` | The rule checks rejected the proposal. |
| `fallback_ai_fact_check_failed` | The fact checker rejected it. |
| `fallback_ai_error` | API, network or response-format problem. |
| `disabled` | `AI_RESUME_ENABLED` is `false`. |

## Privacy and prompt injection

To reword a résumé, the job's title, company, location and description are sent to the
OpenAI Responses API, together with the master facts and the selected bullets. The request
uses `store: false`. The API key lives only in GitHub Actions secrets and never appears in
the repository or the audit files.

Job descriptions are treated as untrusted data. The editor is told never to follow
instructions inside them, it has no tools, and its output must match the JSON contract and
pass both checks before anything is used.
