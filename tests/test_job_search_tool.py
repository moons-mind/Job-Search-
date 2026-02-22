from job_search_tool import Job, deduplicate_jobs, score_jobs, company_rankings


def test_deduplicate_jobs_prefers_richer_description():
    a = Job("x", "1", "Data Scientist", "Acme", "Remote", "u", "", ["python"], "short")
    b = Job("y", "2", "Data Scientist", "Acme", "Remote", "u", "", ["python", "sql"], "longer description")

    result = deduplicate_jobs([a, b])
    assert len(result) == 1
    assert result[0].id == "2"


def test_score_and_company_ranking():
    jobs = [
        Job("x", "1", "Data Scientist", "Acme", "US", "u", "", ["python", "sql"], "modeling and analytics"),
        Job("x", "2", "ML Engineer", "Beta", "EU", "u", "", ["python"], "mlops pipelines"),
        Job("x", "3", "Senior Data Scientist", "Acme", "US", "u", "", ["python", "stats"], "experimentation"),
    ]
    scored = score_jobs(jobs, ["python", "sql", "experimentation"], preferred_location="US")
    assert scored[0].job.company == "Acme"

    ranked = company_rankings(scored)
    assert ranked[0]["company"] == "Acme"
    assert ranked[0]["openings"] == 2
