from job_radar.collector import filter_excluded_titles, title_matches_exclusion


def test_excluded_titles_are_dropped_before_scoring():
    terms = ["nursing assistant", "personal support worker", "veterinary"]
    jobs = [
        {"title": "Nursing Assistant - Casual"},
        {"title": "Personal Support Worker (Nights)"},
        {"title": "Veterinary Technician"},
        {"title": "Registered Nurse"},
        {"title": "Staff Nurse"},
    ]

    filtered = filter_excluded_titles(jobs, terms)
    assert [job["title"] for job in filtered] == ["Registered Nurse", "Staff Nurse"]


def test_exclusions_match_whole_words_only():
    assert title_matches_exclusion("Nurse - Aiden Health", ["aide"]) is False
    assert title_matches_exclusion("Nurse Aide", ["aide"]) is True
