from job_radar.ids import make_fingerprint


def test_fingerprint_is_stable_for_tracking_url_changes():
    a = make_fingerprint("SOC Analyst", "Example Inc", "Toronto, ON", "https://example.com/a")
    b = make_fingerprint("SOC Analyst", "Example Inc", "Toronto, ON", "https://example.com/b")
    assert a == b


def test_remote_jobs_deduplicate_across_location_labels():
    import pandas as pd

    from job_radar.normalize import normalize_dataframe

    df = pd.DataFrame(
        [
            {
                "site": "indeed",
                "title": "SOC Analyst",
                "company": "Example Inc",
                "location": "Toronto, ON, CA",
                "is_remote": True,
                "job_url": "https://example.com/job",
                "description": "Short",
            },
            {
                "site": "indeed",
                "title": "SOC Analyst",
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
