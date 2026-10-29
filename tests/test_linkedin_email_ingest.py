from pathlib import Path

import pytest

from job_radar.linkedin_email_ingest import (
    canonical_linkedin_job_url,
    extract_candidates_from_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_canonical_linkedin_job_url():
    result = canonical_linkedin_job_url("https://www.linkedin.com/comm/jobs/view/4471544570/?trackingId=abc")
    assert result == ("4471544570", "https://www.linkedin.com/jobs/view/4471544570/")


def test_extract_candidates_from_alert_html():
    html = """
    <html><body>
      <div>
        <a href="https://www.linkedin.com/comm/jobs/view/4471544570/?trackingId=abc">
          Registered Nurse - Medical/Surgical
        </a>
        <div>Northwind Health</div>
        <div>Canada Remote</div>
      </div>
    </body></html>
    """
    jobs = extract_candidates_from_html(html)
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "4471544570"
    assert jobs[0]["title"] == "Registered Nurse - Medical/Surgical"


ALERT_HTML = """
<html><body><table>
  <tr><td>
    <a href="https://www.linkedin.com/comm/jobs/view/111/?trk=alert">Registered Nurse</a>
    <p>Northwind Care · Canada (Remote)</p>
  </td></tr>
  <tr><td>
    <a href="https://www.linkedin.com/comm/jobs/view/222/?trk=alert">Staff Nurse</a>
    <p>Example Co · Toronto, ON</p>
  </td></tr>
</table></body></html>
"""


def _alert_email(
    html: str,
    sender: str = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
    subject: str = "New jobs for you: Registered Nurse",
) -> bytes:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg.set_content("plain text fallback")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


class FakeMailbox:
    def __init__(self, messages: dict[int, bytes]):
        self.messages = messages

    def uid(self, command, *args):
        if command == "search":
            return "OK", [b" ".join(str(uid).encode() for uid in sorted(self.messages))]
        return "OK", [(b"RFC822", self.messages[int(args[0])])]


def test_alert_cards_split_company_and_location():
    jobs = {job["job_id"]: job for job in extract_candidates_from_html(ALERT_HTML)}
    assert (jobs["111"]["company"], jobs["111"]["location"]) == ("Northwind Care", "Canada (Remote)")
    assert (jobs["222"]["company"], jobs["222"]["location"]) == ("Example Co", "Toronto, ON")


def test_digest_headers_are_not_jobs():
    html = """
    <div><a href="https://www.linkedin.com/comm/jobs/view/4473586285/">
      Jobs similar to Charge Nurse at Lakeside Health</a></div>
    <div>
      <p>Jobs similar to</p><p>Charge Nurse</p><p>at</p><p>Lakeside Health</p>
      <a href="https://www.linkedin.com/comm/jobs/view/4473586285/">View job</a>
    </div>
    """
    assert extract_candidates_from_html(html) == []


def test_failed_issue_creation_keeps_issues_already_created(tmp_path):
    import json

    from job_radar.linkedin_email_ingest import ingest

    state_path = tmp_path / "state.json"
    mailbox = FakeMailbox({7: _alert_email(ALERT_HTML)})
    titles = ["Registered Nurse", "Staff Nurse"]
    calls: list[str] = []

    def flaky_create(title: str, body: str) -> str:
        calls.append(title)
        if len(calls) == 2:
            raise RuntimeError("GitHub is down")
        return "https://github.com/example/repo/issues/1"

    with pytest.raises(RuntimeError):
        ingest(mailbox, state_path, exclusions=[], target_titles=titles, create_issue=flaky_create)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["processed_job_ids"] == ["111"]
    assert state["last_uid"] == 0  # the half-processed message is read again next time

    created, skipped = ingest(
        mailbox,
        state_path,
        exclusions=[],
        target_titles=titles,
        create_issue=lambda title, body: "https://github.com/example/repo/issues/2",
    )
    assert [job["job_id"] for job in created] == ["222"]
    assert skipped == 0
    assert json.loads(state_path.read_text(encoding="utf-8"))["last_uid"] == 7


def test_jobs_that_already_have_an_issue_are_not_imported(tmp_path):
    from job_radar.linkedin_email_ingest import ingest

    created, _ = ingest(
        FakeMailbox({7: _alert_email(ALERT_HTML)}),
        tmp_path / "state.json",
        exclusions=[],
        target_titles=["Registered Nurse", "Staff Nurse"],
        create_issue=lambda title, body: "https://github.com/example/repo/issues/9",
        known_job_ids=frozenset({"111"}),
    )
    assert [job["job_id"] for job in created] == ["222"]


def test_linkedin_alerts_are_read_whatever_the_subject(tmp_path):
    from job_radar.linkedin_email_ingest import ingest

    notes: list[str] = []
    created, _ = ingest(
        FakeMailbox(
            {
                7: _alert_email(ALERT_HTML, subject="“registered nurse”: Northwind Care - Registered Nurse and more"),
                8: _alert_email(ALERT_HTML, sender="Google <no-reply@accounts.google.com>", subject="Security alert"),
            }
        ),
        tmp_path / "state.json",
        exclusions=[],
        target_titles=["Registered Nurse", "Staff Nurse"],
        create_issue=lambda title, body: "https://github.com/example/repo/issues/1",
        notes=notes,
    )
    assert [job["job_id"] for job in created] == ["111", "222"]
    assert notes == [
        "UID 7: LinkedIn, ““registered nurse”: Northwind Care - Registered Nurse and more” — "
        "2 job(s): 2 new, 0 off-target title, 0 already imported",
        "UID 8: not from LinkedIn (accounts.google.com)",
    ]


def test_dry_run_creates_nothing_and_saves_nothing(tmp_path):
    from job_radar.linkedin_email_ingest import ingest

    state_path = tmp_path / "state.json"
    calls: list[str] = []

    def create(title: str, body: str) -> str:
        calls.append(title)
        return "#"

    created, _ = ingest(
        FakeMailbox({7: _alert_email(ALERT_HTML)}),
        state_path,
        exclusions=[],
        target_titles=["Registered Nurse", "Staff Nurse"],
        create_issue=create,
        since_days=7,
        dry_run=True,
    )
    assert len(created) == 2  # reported as "would create"; main() passes a create_issue that does nothing
    assert not state_path.exists()


def test_the_newest_email_is_not_reread_every_run(tmp_path):
    import json

    from job_radar.linkedin_email_ingest import ingest

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_uid": 7, "processed_job_ids": []}), encoding="utf-8")
    notes: list[str] = []
    # IMAP answers "UID 8:*" with message 7 when 7 is the newest message.
    created, _ = ingest(
        FakeMailbox({7: _alert_email(ALERT_HTML)}),
        state_path,
        exclusions=[],
        target_titles=["Registered Nurse"],
        create_issue=lambda title, body: "https://github.com/example/repo/issues/1",
        notes=notes,
    )
    assert created == [] and notes == []


def test_senior_titles_are_not_imported(tmp_path):
    from job_radar.linkedin_email_ingest import ingest, title_exclusions
    from job_radar.settings import load_yaml

    config = load_yaml(FIXTURES / "config/search_config.yaml")
    html = """
    <div><a href="https://www.linkedin.com/comm/jobs/view/301/">Staff Nurse 2</a><p>Lakeside · Canada</p></div>
    <div><a href="https://www.linkedin.com/comm/jobs/view/302/">Senior Staff Nurse</a><p>Lakeside · Canada</p></div>
    <div><a href="https://www.linkedin.com/comm/jobs/view/303/">Nurse Team Lead</a><p>Acme · Toronto, ON</p></div>
    """
    created, skipped = ingest(
        FakeMailbox({7: _alert_email(html)}),
        tmp_path / "state.json",
        exclusions=title_exclusions(config),
        target_titles=config["search"]["titles"],
        create_issue=lambda title, body: "https://github.com/example/repo/issues/1",
    )
    assert [job["title"] for job in created] == ["Staff Nurse 2"]
    assert skipped == 2


GMAIL_PASS = (
    "mx.google.com; dkim=pass header.i=@linkedin.com header.s=d2048-2 header.b=abc; "
    "spf=pass smtp.mailfrom=s-1@bounce.linkedin.com; dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=linkedin.com"
)
OUTLOOK_PASS = "spf=pass smtp.mailfrom=bounce.linkedin.com; dkim=pass (signature was verified) header.d=linkedin.com"
FORGED = "mx.google.com; dkim=none; spf=fail smtp.mailfrom=evil.example; dmarc=fail (p=REJECT) header.from=linkedin.com"


def _authenticated_email(*results: str) -> bytes:
    """The alert email with Authentication-Results headers on top, as the receiving servers add them."""
    headers = "".join(f"Authentication-Results: {value}\n" for value in results).encode()
    return headers + _alert_email(ALERT_HTML)


@pytest.mark.parametrize(
    ("results", "expected"),
    [((GMAIL_PASS,), "pass"), ((OUTLOOK_PASS,), "pass"), ((FORGED,), "fail"), ((), ""), ((FORGED, GMAIL_PASS), "fail")],
)
def test_sender_authentication_reads_the_receiving_servers_verdict(results, expected):
    from email import message_from_bytes

    from job_radar.linkedin_email_ingest import sender_authentication

    assert sender_authentication(message_from_bytes(_authenticated_email(*results))) == expected


def test_a_forged_linkedin_email_creates_no_issues(tmp_path):
    from job_radar.linkedin_email_ingest import ingest

    notes: list[str] = []
    created, _ = ingest(
        FakeMailbox({3: _authenticated_email(FORGED), 4: _authenticated_email(GMAIL_PASS)}),
        tmp_path / "state.json",
        exclusions=[],
        target_titles=["Registered Nurse", "Staff Nurse"],
        create_issue=lambda title, body: "https://github.com/example/repo/issues/1",
        notes=notes,
    )
    assert len(created) == 2  # both jobs, from the genuine email only
    assert "DKIM/DMARC" in notes[0] and notes[1].startswith("UID 4: LinkedIn")
