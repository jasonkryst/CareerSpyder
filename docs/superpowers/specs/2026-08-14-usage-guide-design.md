# Usage Guide — Design Spec

Date: 2026-08-14
Status: Approved for planning

## Purpose

GitHub issue #13 asks for a usage guide for the application, with example
values for configuring specific sources "provided with the guide and on
the FED" — i.e. both a written document and something inside the
server-rendered web UI (referred to elsewhere in this repo's docs as the
"FED", the front-end dashboard delivered by `app/web/`).

## Current state

`README.md` already carries a fairly complete source field-reference table
(required fields per type, one paragraph of platform-specific notes each)
but no example-first walkthrough, and nothing about it is reachable from
inside the running app. `app/web/templates/source_form.html` shows/hides a
`div#fields-{type}` block per source type via existing `showFieldsFor()`
JS, but those blocks are bare input fields with no guidance on what a
valid value looks like beyond the HTML `<label>` text.

## Decision: two artifacts, one hand-maintained each, no new dependency

1. **`docs/USAGE.md`** — a new, example-driven guide, separate from
   README's architecture-oriented reference. Getting-started walkthrough,
   a tour of each web UI page, and a per-source-type section with example
   config values.
2. **A new `/guide` page in the web UI** — same content shape, styled like
   every other page (extends `base.html`, gets a nav link).

The two are **hand-written independently**, not generated from a shared
source. Rendering `USAGE.md` into the page would pull in the project's
first markdown-parsing dependency, which conflicts with the "no new
runtime dependencies" decision already made for this UI (see
`docs/superpowers/specs/2026-08-13-enhanced-fed-ui-design.md`). The
duplication cost is small and bounded: both documents change only when a
source type's required fields change, which is already a multi-file
change (`config.py`, an adapter, `source_form.html`, README's table) — one
more file to touch is a marginal addition, not a new maintenance burden
class.

## `docs/USAGE.md`

Sections, in order:

1. **Getting started** — numbered walkthrough: open the UI, add a source
   under Sources, use "Test this source" to preview before saving, save,
   trigger a run from the Dashboard, check History and the digest email.
2. **Web UI tour** — one paragraph per page (Dashboard, History, Sources,
   Settings tabs), cross-referencing README's existing "Web UI" table
   rather than duplicating it.
3. **Source types & examples** — one subsection per adapter type
   (`greenhouse`, `lever`, `generic_html`, `linkedin`, `indeed`, `infor`,
   `healthcaresource`, `talentbrew`, `workday`, `phenompeople`, `findly`),
   each with a minimal realistic example (field name → example value) drawn
   from the same examples already in README's `sources.json` sample and
   field-reference table, reworded as prose-with-example rather than a
   dense table.

`README.md`'s "Further reading" list gets one new line linking to it.

## `/guide` page

- `app/web/routes_guide.py` — new `APIRouter` with a single
  `GET /guide` route returning `templates.TemplateResponse(request,
  "guide.html", {})`. No DB/source-file access — pure static content —
  so no dependency injection beyond `request`.
- Registered in `app/web/main.py` alongside the other four routers.
- `app/web/templates/guide.html` — extends `base.html`; content mirrors
  `USAGE.md`'s three sections. Each source-type subsection gets `id="type-
  {type}"` (e.g. `id="type-greenhouse"`) so it can be deep-linked.
- `base.html`'s `<nav aria-label="Main">` gets a fifth link — `<a
  href="/guide" {% if request.url.path == "/guide" %}aria-current="page"
  {% endif %}>Guide</a>` — following the exact pattern the other four links
  already use.

## Inline hints on the source form

`source_form.html`: inside each existing `div#fields-{type}` block, add a
small example box — reusing the same show/hide mechanism that already
exists (`showFieldsFor()`), no new JS. Markup:

```html
<div class="hint">
  <strong>Example:</strong> <code>board_token: "acme"</code>
  — <a href="/guide#type-greenhouse">full reference</a>
</div>
```

One `.hint` per type block, with the one or two most important example
field values for that type (not the full field list — the linked `/guide`
section has that). `style.css` gets a new `.hint` rule: same visual family
as `.card` but lighter — muted background, a left accent border (like
`.error`/`.success`), smaller padding — plus `code` styling (`.hint code`
and any future inline code use), since neither exists in the stylesheet
today.

## Testing

`tests/web/test_guide.py` (new, TestClient pattern matching the rest of
`tests/web/`):

- `GET /guide` returns 200.
- Response body contains a heading/anchor for each of the 11 source
  types (`id="type-{type}"` for each).
- The main nav on `/guide` carries `aria-current="page"` on the Guide
  link and not on any other nav link.

`tests/web/test_base.py` (extend): the nav — on an existing route, e.g.
`/` — now contains a `Guide` link pointing at `/guide`.

`tests/web/test_source_form.py` (extend): `GET /sources/new` response
contains at least one `.hint` block with example content for the
default-selected type.

No new adapter/model code, so no changes needed elsewhere in `tests/`.

## Explicitly out of scope for this iteration

- **Rendering `USAGE.md` into `/guide` via a markdown library.** Rejected
  above — a new runtime dependency for a purely cosmetic sync benefit.
- **Hint boxes for every field on every type.** The inline hint is meant
  as a quick example + pointer to `/guide`, not a full inline copy of the
  reference table — that duplication would be the worst of both worlds
  (three copies to maintain instead of two).
- **Search or a table of contents sidebar on `/guide`.** The page is one
  scrollable document with in-page anchors; a single-page site of this
  size doesn't need in-page search.
