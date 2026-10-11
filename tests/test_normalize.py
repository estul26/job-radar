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


def test_fingerprints_keep_every_script():
    # Different jobs in Japanese or Russian must not collapse into one.
    tokyo = make_fingerprint("看護師（日勤）", "東京中央病院", "東京都")
    osaka = make_fingerprint("経理スタッフ", "株式会社サンプル", "大阪府")
    assert tokyo != osaka
    assert make_fingerprint("Медсестра", "Больница", "Москва") != make_fingerprint("Бухгалтер", "ООО", "Казань")
    assert make_fingerprint("Enfermería", "X", "Y") != make_fingerprint("Enfermera", "X", "Y")
    # Full-width and half-width letters are the same job.
    assert make_fingerprint("ＳＡＰ担当", "Ａ社", "東京") == make_fingerprint("SAP担当", "A社", "東京")
