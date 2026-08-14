from app.textutils import safe_url_scheme, to_summary


def test_to_summary_strips_html_tags():
    assert to_summary("<p>Great <b>role</b>.</p>") == "Great role."


def test_to_summary_collapses_whitespace():
    assert to_summary("Line one\n\n   Line two") == "Line one Line two"


def test_to_summary_truncates_with_ellipsis():
    text = "x" * 300
    result = to_summary(text, limit=250)
    assert len(result) == 251  # 250 chars + ellipsis
    assert result.endswith("…")


def test_to_summary_does_not_add_ellipsis_when_under_limit():
    result = to_summary("short text", limit=250)
    assert result == "short text"


def test_to_summary_returns_none_for_empty_input():
    assert to_summary(None) is None
    assert to_summary("") is None
    assert to_summary("   ") is None


def test_safe_url_scheme_allows_http_and_https():
    assert safe_url_scheme("https://x.test/1") == "https://x.test/1"
    assert safe_url_scheme("http://x.test/1") == "http://x.test/1"


def test_safe_url_scheme_neutralizes_javascript_scheme():
    assert safe_url_scheme("javascript:alert(1)") == "#"


def test_safe_url_scheme_allows_schemeless_relative_url():
    assert safe_url_scheme("/careers/1") == "/careers/1"
