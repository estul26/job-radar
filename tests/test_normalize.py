from job_radar.ids import make_fingerprint


def test_fingerprint_is_stable_for_tracking_url_changes():
    a = make_fingerprint("Registered Nurse", "Example Inc", "Toronto, ON", "https://example.com/a")
    b = make_fingerprint("Registered Nurse", "Example Inc", "Toronto, ON", "https://example.com/b")
    assert a == b


def test_remote_jobs_deduplicate_across_location_labels():
    import pandas as pd

    from job_radar.normalize import normalize_dataframe

    df = pd.DataFrame(
        [
            {
                "site": "indeed",
                "title": "Registered Nurse",
                "company": "Example Inc",
                "location": "Toronto, ON, CA",
                "is_remote": True,
                "job_url": "https://example.com/job",
                "description": "Short",
            },
            {
                "site": "indeed",
                "title": "Registered Nurse",
                "company": "Example Inc",
                "location": "Canada",
                "is_remote": True,
                "job_url": "https://example.com/job",
                "description": "Longer description",
            },
        ]
    )

    jobs = normalize_dataframe(df)
    assert len(jobs) == 1
    assert jobs[0]["description"] == "Longer description"


def test_fingerprints_keep_accented_and_non_latin_letters():
    # Job boards return company and place names with accents or in other scripts; different jobs
    # must not collapse into one fingerprint.
    assert make_fingerprint("Accountant", "Nestlé", "Zürich") != make_fingerprint("Accountant", "Nestle", "Zurich")
    assert make_fingerprint("Accountant", "東京商事", "Tokyo") != make_fingerprint("Accountant", "大阪商事", "Tokyo")
    # Full-width and half-width letters are the same job.
    assert make_fingerprint("ＳＡＰ Analyst", "Ａ Ltd", "Tokyo") == make_fingerprint("SAP Analyst", "A Ltd", "Tokyo")
