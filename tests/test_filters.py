from app.filters import apply_keyword_filters
from app.models import Job


def job(title):
    return Job(key=title, title=title, url="https://x.test", source_name="s")


def test_no_filters_returns_all():
    jobs = [job("Backend Engineer"), job("Sales Rep")]
    assert apply_keyword_filters(jobs, [], []) == jobs


def test_include_keyword_is_case_insensitive_substring_match():
    jobs = [job("Backend Engineer"), job("Sales Rep")]
    result = apply_keyword_filters(jobs, ["engineer"], [])
    assert [j.title for j in result] == ["Sales Rep"]


def test_exclude_keyword_removes_matches():
    jobs = [job("Senior Backend Engineer"), job("Backend Engineer")]
    result = apply_keyword_filters(jobs, [], ["senior"])
    assert [j.title for j in result] == ["Backend Engineer"]


def test_include_and_exclude_combine():
    jobs = [job("Senior Backend Engineer"), job("Backend Engineer"), job("Sales Rep")]
    result = apply_keyword_filters(jobs, ["engineer"], ["senior"])
    assert [j.title for j in result] == ["Backend Engineer"]
