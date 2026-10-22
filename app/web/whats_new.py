"""Parses CHANGELOG.md's per-version sections for the in-app "What's New"
modal (issue #241). Read from disk once at import time via templating.py --
the content doesn't change while the process is running, so there is no
runtime fetch (and no CSP relaxation needed for it), mirroring the "statically
embedded" approach used by the MyFinances #289 modal this one is modeled on.
"""

import re
from html import escape
from pathlib import Path

from app.textutils import safe_url_scheme

# CHANGELOG.md lives at the repo root. Read relative to the process's
# working directory -- always the repo root for local dev (per AGENTS.md's
# documented `uvicorn` command) and for the Docker image (WORKDIR /app,
# where the Dockerfile COPYs it) -- the same convention already used for
# alembic.ini elsewhere in this codebase.
_CHANGELOG_PATH = Path("CHANGELOG.md")

_VERSION_HEADING_RE = re.compile(r"^## \[(?P<version>[^\]]+)\].*$", re.MULTILINE)
_SECTION_HEADING_RE = re.compile(r"^### (.+)$")
_BULLET_RE = re.compile(r"^- (.+)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")

_NO_NOTES_HTML = "<p>Release notes are not available.</p>"


def _inline_html(text: str) -> str:
    text = escape(text)

    def _link(match: re.Match[str]) -> str:
        href = escape(safe_url_scheme(match.group(2)), quote=True)
        return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{match.group(1)}</a>'

    text = _LINK_RE.sub(_link, text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _CODE_RE.sub(r"<code>\1</code>", text)
    return text


def release_notes_section(changelog_text: str, version: str) -> str | None:
    """Return the raw Markdown body between the `## [version]` heading and
    the next `## [` heading (or end of file). None if no heading matches."""
    headings = list(_VERSION_HEADING_RE.finditer(changelog_text))
    for i, heading in enumerate(headings):
        if heading.group("version") == version:
            start = heading.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(changelog_text)
            return changelog_text[start:end].strip()
    return None


def render_release_notes_html(markdown_body: str) -> str:
    """Render the handful of Markdown constructs CHANGELOG.md actually uses
    (### headings, - bullets that may soft-wrap onto indented continuation
    lines, **bold**, `code`, [text](url) links) as HTML. This is not a
    general Markdown parser -- CHANGELOG.md's own format, written by this
    project, is the only input it ever sees."""
    html_parts: list[str] = []
    in_list = False
    current_item: list[str] | None = None  # raw (not yet inline-rendered) fragments

    def _flush_item() -> None:
        nonlocal current_item
        if current_item is not None:
            # Inline rendering runs once on the fully-joined item, not per
            # fragment -- **bold** (and other spans) can open on one
            # soft-wrapped line and close on the next.
            html_parts.append(f"<li>{_inline_html(' '.join(current_item))}</li>")
            current_item = None

    for raw_line in markdown_body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading_match = _SECTION_HEADING_RE.match(line)
        bullet_match = _BULLET_RE.match(line)
        if heading_match:
            _flush_item()
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h4>{_inline_html(heading_match.group(1))}</h4>")
        elif bullet_match:
            _flush_item()
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            current_item = [bullet_match.group(1)]
        elif in_list and current_item is not None:
            current_item.append(line)  # wrapped continuation of the current bullet
        else:
            _flush_item()
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<p>{_inline_html(line)}</p>")
    _flush_item()
    if in_list:
        html_parts.append("</ul>")
    return "".join(html_parts)


def whats_new_html(version: str) -> str:
    """HTML for the What's New modal body for `version`, or a graceful
    fallback if CHANGELOG.md is missing or has no matching entry (e.g. an
    install run from somewhere other than the repo root)."""
    try:
        text = _CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return _NO_NOTES_HTML
    section = release_notes_section(text, version)
    if not section:
        return _NO_NOTES_HTML
    return render_release_notes_html(section)
