"""Tests for app/web/whats_new.py: the CHANGELOG.md parser behind the
in-app "What's New" modal (#241)."""

from app.web.whats_new import (
    release_notes_section,
    render_release_notes_html,
    whats_new_html,
)

_CHANGELOG = """\
# Changelog

## [Unreleased]

## [1.2.0] — 2026-01-02

### Added

- **New thing** ([#10](https://github.com/x/y/issues/10)). Does `the_thing()`.

### Fixed

- Something was broken.

## [1.1.0] — 2026-01-01

### Added

- Older entry.
"""


def test_release_notes_section_extracts_body_between_its_heading_and_the_next():
    section = release_notes_section(_CHANGELOG, "1.2.0")

    assert section is not None
    assert "New thing" in section
    assert "Older entry" not in section


def test_release_notes_section_for_the_last_heading_runs_to_end_of_file():
    section = release_notes_section(_CHANGELOG, "1.1.0")

    assert section is not None
    assert "Older entry" in section


def test_release_notes_section_returns_none_for_unknown_version():
    assert release_notes_section(_CHANGELOG, "9.9.9") is None


def test_release_notes_section_returns_none_for_unreleased_placeholder():
    # The heading matches but has no body before the next "## [" heading.
    assert release_notes_section(_CHANGELOG, "Unreleased") == ""


def test_release_notes_section_excludes_the_trailing_date_on_the_heading_line():
    # Real CHANGELOG.md headings are "## [X.Y.Z] — YYYY-MM-DD" -- the date
    # must not leak into the section body as a stray paragraph.
    changelog = (
        "## [2.0.0] — 2026-03-01\n\n### Fixed\n\n- A fix.\n"
    )

    section = release_notes_section(changelog, "2.0.0")

    assert section is not None
    assert "2026-03-01" not in section
    assert section.startswith("### Fixed")


def test_render_release_notes_html_joins_a_soft_wrapped_bullet_into_one_item():
    section = (
        "### Fixed\n\n"
        "- **Wrong tile key.** The tile URL was appending\n"
        "  `?api_key=` but the API expects `?key=`. A mismatched\n"
        "  parameter name returns HTTP 200 silently.\n"
    )

    html = render_release_notes_html(section)

    assert html.count("<li>") == 1
    assert html.count("</li>") == 1
    assert "silently." in html
    assert "<p>" not in html  # no stray paragraph from the continuation lines


def test_render_release_notes_html_renders_bold_that_spans_a_line_wrap():
    section = (
        "### Fixed\n\n"
        "- **Four environment variables weren't wired through\n"
        "  Docker Compose.** `CARTO_API_KEY` was affected.\n"
    )

    html = render_release_notes_html(section)

    assert "<strong>Four environment variables weren" in html
    assert "Docker Compose.</strong>" in html
    assert "**" not in html


def test_render_release_notes_html_renders_headings_bullets_bold_code_and_links():
    section = release_notes_section(_CHANGELOG, "1.2.0")
    assert section is not None

    html = render_release_notes_html(section)

    assert "<h4>Added</h4>" in html
    assert "<h4>Fixed</h4>" in html
    assert "<li><strong>New thing</strong>" in html
    assert '<a href="https://github.com/x/y/issues/10" target="_blank" rel="noopener noreferrer">#10</a>' in html
    assert "<code>the_thing()</code>" in html
    assert "<li>Something was broken.</li>" in html


def test_render_release_notes_html_escapes_html_in_content():
    html = render_release_notes_html("- <script>alert(1)</script>")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_release_notes_html_rejects_unsafe_link_schemes():
    html = render_release_notes_html("- [click me](javascript:alert(1))")

    assert 'href="javascript:' not in html
    assert 'href="#"' in html


def test_whats_new_html_renders_a_real_section(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    html = whats_new_html("1.2.0")

    assert "New thing" in html


def test_whats_new_html_falls_back_gracefully_when_changelog_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no CHANGELOG.md here

    html = whats_new_html("1.2.0")

    assert "not available" in html


def test_whats_new_html_falls_back_gracefully_for_an_unknown_version(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    html = whats_new_html("9.9.9")

    assert "not available" in html
