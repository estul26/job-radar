from job_radar.collector import filter_excluded_titles, title_matches_exclusion


def test_physical_security_titles_are_excluded():
    terms = [
        "security guard",
        "guard",
        "loss prevention",
        "asset protection",
        "physical security",
        "security officer",
    ]
    jobs = [
        {"title": "Security Guard - Casual"},
        {"title": "Asset Protection Associate"},
        {"title": "Security and Loss Prevention Specialist"},
        {"title": "SOC Analyst I"},
        {"title": "Security Operations Analyst"},
    ]

    filtered = filter_excluded_titles(jobs, terms)
    assert [job["title"] for job in filtered] == [
        "SOC Analyst I",
        "Security Operations Analyst",
    ]


def test_guard_boundary_does_not_block_guardium():
    assert title_matches_exclusion("IBM Guardium Security Analyst", ["guard"]) is False
