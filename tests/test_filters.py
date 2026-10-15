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
    assert [j.title for j in result] == ["Backend Engineer"]


def test_exclude_keyword_removes_matches():
    jobs = [job("Senior Backend Engineer"), job("Backend Engineer")]
    result = apply_keyword_filters(jobs, [], ["senior"])
    assert [j.title for j in result] == ["Backend Engineer"]


def test_include_and_exclude_combine():
    jobs = [job("Senior Backend Engineer"), job("Backend Engineer"), job("Sales Rep")]
    result = apply_keyword_filters(jobs, ["engineer"], ["senior"])
    assert [j.title for j in result] == ["Backend Engineer"]


def test_include_keyword_matches_company():
    j = Job(key="1", title="SWE", url="https://x.test", company="Google Inc", source_name="s")
    result = apply_keyword_filters([j], ["google"], [])
    assert len(result) == 1 and result[0].title == "SWE"


def test_include_keyword_matches_location():
    j = Job(key="1", title="Backend Engineer", url="https://x.test", location="Seattle, WA", source_name="s")
    result = apply_keyword_filters([j], ["seattle"], [])
    assert len(result) == 1 and result[0].title == "Backend Engineer"


def test_exclude_keyword_matches_company():
    j = Job(key="1", title="Engineer", url="https://x.test", company="Facebook", source_name="s")
    result = apply_keyword_filters([j], [], ["facebook"])
    assert len(result) == 0


def test_exclude_keyword_matches_location():
    j = Job(key="1", title="Engineer", url="https://x.test", location="Remote", source_name="s")
    result = apply_keyword_filters([j], [], ["remote"])
    assert len(result) == 0


def test_keyword_filter_still_matches_title():
    j = Job(key="1", title="Backend Engineer", url="https://x.test", company="Meta", location="Seattle", source_name="s")
    result = apply_keyword_filters([j], ["backend"], [])
    assert len(result) == 1


def test_none_company_and_location_do_not_raise():
    j = Job(key="1", title="Engineer", url="https://x.test", company=None, location=None, source_name="s")
    result = apply_keyword_filters([j], ["engineer"], [])
    assert len(result) == 1
