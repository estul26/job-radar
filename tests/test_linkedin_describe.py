"""radar linkedin-describe: reading a public posting page and filling in the Issues that wait for it."""

import pytest

from fake_github import FakeGitHub
from job_radar.commands.linkedin_describe import (
    GONE_MARKER,
    LABEL,
    RETRY_PAUSE,
    describe_pending,
    fill_body,
    pending,
    refusal,
)
from job_radar.issue_body import PLACEHOLDER_DESCRIPTION, PLACEHOLDER_MARKER, parse_job, render_linkedin_alert
from job_radar.linkedin_guest import (
    GUEST_URL,
    GuestBlocked,
    GuestError,
    PostingGone,
    fetch_posting,
    parse_posting,
)

POSTING_HTML = """
<section class="top-card-layout container-lined">
  <h2 class="top-card-layout__title font-sans topcard__title">Registered Nurse</h2>
  <h4 class="top-card-layout__second-subline">
    <div class="topcard__flavor-row">
      <span class="topcard__flavor">
        <a class="topcard__org-name-link topcard__flavor--black-link" href="#"> Northwind Care </a>
      </span>
      <span class="topcard__flavor topcard__flavor--bullet"> Toronto, Ontario, Canada </span>
    </div>
    <div class="topcard__flavor-row">
      <span class="posted-time-ago__text topcard__flavor--metadata"> 2 days ago </span>
      <figure class="num-applicants__figure topcard__flavor--metadata topcard__flavor--bullet">
        <span>Over 200 applicants</span>
      </figure>
    </div>
  </h4>
</section>
<div class="description__text description__text--rich">
  <section class="show-more-less-html" data-max-lines="5">
    <div class="show-more-less-html__markup show-more-less-html__markup--clamp-after-5
        relative overflow-hidden">
      <strong>About the role<br><br></strong>Care for patients on a   busy
      medical unit.<br><br><strong>Requirements</strong>
      <ul><li>RN licence</li><li>2 years of <em>acute care</em> experience</li></ul>
      <p>### Benefits</p><!-- tracking --><p>Pension &amp; dental.</p>
    </div>
    <button class="show-more-less-html__button">Show more</button>
  </section>
</div>
"""

DESCRIPTION = """About the role

Care for patients on a busy medical unit.

Requirements

- RN licence
- 2 years of acute care experience

Benefits

Pension & dental."""


def alert_body(job_id: str, company: str = "Northwind Care", location: str = "Toronto, ON") -> str:
    card = {
        "job_id": job_id,
        "job_url": f"https://www.linkedin.com/jobs/view/{job_id}/",
        "title": "Registered Nurse",
        "company": company,
        "location": location,
        "card_excerpt": "Registered Nurse\nNorthwind Care",
    }
    return render_linkedin_alert(card, "New jobs for you")


def waiting_issue(number: int, job_id: str, **overrides) -> dict:
    return {
        "number": number,
        "title": "[LinkedIn Alert] Registered Nurse — Northwind Care",
        "body": alert_body(job_id),
        "labels": [LABEL],
        **overrides,
    }


def run(gh, fetch, **kwargs):
    return describe_pending(gh, fetch=fetch, sleep=lambda _: None, pause=lambda a, b: a, log=lambda _: None, **kwargs)


def test_the_public_page_is_read_as_plain_text():
    posting = parse_posting(POSTING_HTML)
    assert (posting["title"], posting["company"]) == ("Registered Nurse", "Northwind Care")
    assert posting["location"] == "Toronto, Ontario, Canada"
    assert posting["description"] == DESCRIPTION


def test_a_page_without_the_expected_markup_has_no_fields():
    assert parse_posting("<html><body>Sign in</body></html>") == {
        "title": "",
        "company": "",
        "location": "",
        "description": "",
    }


def test_fetching_asks_for_the_guest_page_of_the_job():
    asked = []

    def get(url):
        asked.append(url)
        return 200, url, POSTING_HTML

    assert fetch_posting("4471532081", get=get)["description"] == DESCRIPTION
    assert asked == [GUEST_URL.format(job_id="4471532081")]


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ((404, "", ""), PostingGone),
        ((429, "", ""), GuestBlocked),
        ((999, "", ""), GuestBlocked),
        ((200, "https://www.linkedin.com/authwall?trk=x", "<html></html>"), GuestBlocked),
        ((500, "", ""), GuestError),
        ((200, "", "<html><body>Nothing here</body></html>"), GuestError),
    ],
)
def test_fetch_failures(response, error):
    status, final_url, body = response
    with pytest.raises(error) as caught:
        fetch_posting("42", get=lambda url: (status, final_url or url, body))
    assert type(caught.value) is error


def test_only_open_labelled_linkedin_issues_with_the_placeholder_are_pending():
    issues = [
        waiting_issue(1, "101"),
        waiting_issue(2, "102", state="CLOSED"),
        waiting_issue(3, "103", labels=[]),
        waiting_issue(4, "104", body=alert_body("104").replace(PLACEHOLDER_DESCRIPTION, "Pasted by hand.")),
        waiting_issue(5, "105", title="[Indeed Job] Registered Nurse — Northwind Care"),
    ]
    assert [(number, job_id) for number, job_id, *_ in pending(FakeGitHub(issues).issues())] == [(1, "101")]


def test_filling_in_makes_the_issue_scorable_and_keeps_its_source():
    body = fill_body(
        alert_body("101", company="Unknown — edit before scoring", location="Unknown — edit before scoring"),
        parse_posting(POSTING_HTML),
    )
    job = parse_job(body)
    assert PLACEHOLDER_MARKER not in body
    assert job["description"] == DESCRIPTION
    assert (job["company"], job["location"]) == ("Northwind Care", "Toronto, Ontario, Canada")
    assert "### LinkedIn alert source" in body


def test_known_card_fields_are_kept():
    job = parse_job(fill_body(alert_body("101", location="Canada (Remote)"), parse_posting(POSTING_HTML)))
    assert (job["company"], job["location"], job["is_remote"]) == ("Northwind Care", "Canada (Remote)", True)


def test_long_descriptions_are_truncated_for_github():
    body = fill_body(alert_body("101"), {"description": "x" * 50000})
    assert len(body) < 65536
    assert "[Description truncated in GitHub Issue.]" in body


def test_backslashes_in_a_description_are_kept_as_written():
    assert r"C:\new\1" in fill_body(alert_body("101"), {"description": r"Paths like C:\new\1"})


def test_waiting_issues_are_filled_in_up_to_the_limit():
    gh = FakeGitHub([waiting_issue(1, "101"), waiting_issue(2, "102"), waiting_issue(3, "103")])
    fetched = []

    def fetch(job_id):
        fetched.append(job_id)
        return parse_posting(POSTING_HTML)

    outcome = run(gh, fetch, max_jobs=2)
    assert (outcome.filled, outcome.waiting, outcome.blocked) == ([3, 2], 3, False)
    assert fetched == ["103", "102"]
    assert DESCRIPTION in gh.issue(3)["body"]
    assert PLACEHOLDER_MARKER in gh.issue(1)["body"]


def test_a_dry_run_changes_nothing():
    gh = FakeGitHub([waiting_issue(1, "101")])
    outcome = run(gh, lambda job_id: parse_posting(POSTING_HTML), dry_run=True)
    assert outcome.filled == [1]
    assert PLACEHOLDER_MARKER in gh.issue(1)["body"]


def test_a_posting_gone_from_linkedin_is_not_tried_again():
    gh = FakeGitHub([waiting_issue(1, "101")])

    def fetch(job_id):
        raise PostingGone("gone")

    outcome = run(gh, fetch)
    assert (outcome.gone, outcome.filled) == ([1], [])
    assert LABEL not in gh.labels_of(1)
    assert gh.state_of(1) == "OPEN"
    assert GONE_MARKER in gh.comments_of(1)[0]
    assert pending(gh.issues()) == []


def test_a_passing_refusal_is_retried_once_after_a_wait():
    gh = FakeGitHub([waiting_issue(1, "101"), waiting_issue(2, "102")])
    calls, sleeps = [], []

    def fetch(job_id):
        calls.append(job_id)
        if calls == ["102"]:
            raise GuestBlocked("HTTP 429")
        return parse_posting(POSTING_HTML)

    outcome = describe_pending(gh, fetch=fetch, sleep=sleeps.append, pause=lambda a, b: a, log=lambda _: None)
    assert (outcome.filled, outcome.blocked) == ([2, 1], False)
    assert calls == ["102", "102", "101"]
    assert sleeps == [RETRY_PAUSE[0], 3.0]


def test_a_card_that_ran_title_company_and_place_together_is_repaired():
    body = alert_body("101", company="Unknown — edit before scoring", location="Unknown — edit before scoring").replace(
        "### Job title\n\nRegistered Nurse\n", "### Job title\n\nRegistered Nurse Northwind Care · Toronto, ON\n"
    )
    issue = waiting_issue(
        1, "101", title="[LinkedIn Alert] Registered Nurse Northwind Care · Toronto, ON — Unknown", body=body
    )
    gh = FakeGitHub([issue])
    run(gh, lambda job_id: parse_posting(POSTING_HTML))
    fixed = gh.issue(1)
    job = parse_job(fixed["body"])
    assert fixed["title"] == "[LinkedIn Alert] Registered Nurse — Northwind Care"
    assert (job["title"], job["company"], job["location"]) == (
        "Registered Nurse",
        "Northwind Care",
        "Toronto, Ontario, Canada",
    )


def test_a_card_with_its_company_keeps_its_own_title():
    gh = FakeGitHub([waiting_issue(1, "101", title="[LinkedIn Alert] RN, Medicine — Northwind Care")])
    run(gh, lambda job_id: {**parse_posting(POSTING_HTML), "title": "Registered Nurse (Medicine)"})
    assert gh.issue(1)["title"] == "[LinkedIn Alert] RN, Medicine — Northwind Care"
    assert parse_job(gh.issue(1)["body"])["title"] == "Registered Nurse"


def test_a_refusal_from_linkedin_stops_the_run():
    gh = FakeGitHub([waiting_issue(1, "101"), waiting_issue(2, "102"), waiting_issue(3, "103")])
    fetched = []

    def fetch(job_id):
        fetched.append(job_id)
        if job_id == "102":
            raise GuestBlocked("HTTP 429")
        return parse_posting(POSTING_HTML)

    outcome = run(gh, fetch)
    assert (outcome.filled, outcome.blocked) == ([3], True)
    assert fetched == ["103", "102", "102"]  # one more try, then the run stops
    assert LABEL in gh.labels_of(2)


def test_an_unreadable_posting_is_left_waiting_and_the_run_goes_on():
    gh = FakeGitHub([waiting_issue(1, "101"), waiting_issue(2, "102")])

    def fetch(job_id):
        if job_id == "102":
            raise GuestError("HTTP 500")
        return parse_posting(POSTING_HTML)

    outcome = run(gh, fetch)
    assert (outcome.filled, outcome.failed) == ([1], [2])
    assert PLACEHOLDER_MARKER in gh.issue(2)["body"]


def test_it_never_runs_in_ci():
    assert "never in CI" in refusal({"GITHUB_ACTIONS": "true"})
    assert refusal({}) == ""
