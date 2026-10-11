import json

from job_radar.commands.issue import route
from job_radar.commands.linkedin_import import import_cards, known_linkedin_ids, read_cards
from job_radar.issue_body import PLACEHOLDER_MARKER, parse_sections, render_linkedin_search

TITLES = ["Registered Nurse", "Staff Nurse", "Charge Nurse"]
EXCLUSIONS = ["nursing assistant", "senior"]


def _export(tmp_path, jobs):
    path = tmp_path / "latest_chrome_linkedin.json"
    path.write_text(json.dumps({"generated_at": "2026-10-09T08:00:00", "jobs": jobs}), encoding="utf-8")
    return path


def test_read_cards_canonicalises_and_deduplicates(tmp_path):
    path = _export(
        tmp_path,
        [
            {
                "job_url": "https://www.linkedin.com/jobs/view/111/?trk=x",
                "title": " Registered  Nurse ",
                "company": "Acme",
            },
            {"job_url": "https://www.linkedin.com/jobs/search/?currentJobId=111", "title": "Registered Nurse"},
            {"job_url": "https://example.com/jobs/1", "title": "Not LinkedIn"},
            {"job_url": "https://www.linkedin.com/jobs/view/222/", "title": ""},
        ],
    )
    cards = read_cards(path)
    assert [card["job_id"] for card in cards] == ["111"]
    assert cards[0]["job_url"] == "https://www.linkedin.com/jobs/view/111/"
    assert cards[0]["title"] == "Registered Nurse"
    assert cards[0]["location"].startswith("Unknown")


def test_import_creates_issues_only_for_new_on_target_titles(tmp_path):
    cards = read_cards(
        _export(
            tmp_path,
            [
                {"job_url": "https://www.linkedin.com/jobs/view/1/", "title": "Registered Nurse", "company": "Acme"},
                {
                    "job_url": "https://www.linkedin.com/jobs/view/2/",
                    "title": "Senior Registered Nurse",
                    "company": "B",
                },
                {"job_url": "https://www.linkedin.com/jobs/view/3/", "title": "Line Cook", "company": "C"},
                {"job_url": "https://www.linkedin.com/jobs/view/4/", "title": "Charge Nurse", "company": "D"},
            ],
        )
    )
    made: list[tuple[str, str]] = []
    created, off_target, already = import_cards(
        cards,
        exclusions=EXCLUSIONS,
        target_titles=TITLES,
        known_job_ids=frozenset({"4"}),
        create_issue=lambda title, body: made.append((title, body)) or "#1",
    )
    assert [item["job_id"] for item in created] == ["1"]
    assert (off_target, already) == (2, 1)
    assert made[0][0] == "[LinkedIn Job] Registered Nurse — Acme"


def test_search_issue_waits_for_its_description_then_scores():
    body = render_linkedin_search(
        {
            "job_url": "https://www.linkedin.com/jobs/view/1/",
            "title": "Registered Nurse",
            "company": "Acme",
            "location": "Canada (Remote)",
            "date_posted": "2 days ago",
            "card_excerpt": "Registered Nurse\nAcme\nCanada (Remote)",
        }
    )
    sections = parse_sections(body)
    assert sections["remote?"] == "Yes"
    assert sections["date posted (optional)"] == "2 days ago"
    issue = {"title": "[LinkedIn Job] Registered Nurse — Acme", "body": body}
    assert PLACEHOLDER_MARKER in body
    assert route(issue, "opened") is None
    issue["body"] = body.replace(sections["job description"], "Assess patients and chart each shift.")
    assert route(issue, "edited") == "intake"


def test_known_ids_come_from_every_issue_body(issue_body):
    issues = [{"body": issue_body("linkedin_form")}, {"body": issue_body("indeed")}]
    assert len(known_linkedin_ids(issues)) == 1
