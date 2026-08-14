# Modernized Theme + Preferences Tab — Design Spec

Date: 2026-08-14
Status: Approved for planning

## Purpose

The current UI (`app/web/`) works but reads as generic/default — flat
colors, browser-default table borders (`border="1" cellpadding="4"`
inline attributes fighting the CSS), an underlined-link nav, and a
header theme-toggle button that's really a settings control living
outside Settings. This spec gives the app a distinctive visual identity
(red/white/black) and moves theme control into a new **Preferences**
tab alongside the existing Email/Data tabs, matching how #14 already
split Settings into tabs.

Scope, per discussion: **visual polish only** — no new server-stored
personalization, no new fonts/icons requiring a network fetch or build
step (this repo has twice explicitly rejected adding build tooling/deps
for the UI, see `2026-08-13-enhanced-fed-ui-design.md`). The theme
control itself grows from a two-state toggle to an explicit three-way
Light/Dark/System choice, staying purely client-side (localStorage),
consistent with how it already works today.

## Current state

`static/style.css` defines a CSS-custom-property palette (`--bg`,
`--accent`, etc.) redefined under `prefers-color-scheme: dark` and
`[data-theme="dark"|"light"]`. `base.html` has a `#theme-toggle` button
in the header, wired by `static/theme.js` (click → flip data-theme →
persist to localStorage), plus a synchronous inline `<script>` in
`<head>` that applies a stored theme before first paint (anti-FOUC).
Settings already has a tab pattern (`settings_tabs.html`,
`/settings/email`, `/settings/data`) established in the #14 work.
Tables render with legacy inline `border`/`cellpadding` HTML attributes
predating the CSS pass. `.success` currently reuses `--accent` (blue)
and `.error` uses separate red tokens — a collision waiting to happen
once accent becomes red.

## Color system

Palette stays within red/white/black across both modes, AA-contrast
checked (≥4.5:1 for text, ≥3:1 for UI components):

| Token | Light | Dark |
|---|---|---|
| `--bg` | `#ffffff` | `#0d0d0e` |
| `--bg-elevated` | `#f6f6f7` | `#18181a` |
| `--fg` | `#171717` | `#f2f0ef` |
| `--fg-muted` | `#5c5c5f` | `#a8a6a5` |
| `--border` | `#dcdcde` | `#302f31` |
| `--accent` | `#b3101f` | `#ff5b5b` |
| `--accent-fg` | `#ffffff` | `#1a0a0a` |
| `--error-bg` | `#fdeceb` | `#3a1613` |
| `--error-fg` | `#7a1810` | `#ff9a90` |
| `--success-bg` | `#f2f2f3` | `#1c1c1e` |
| `--success-fg` | `#171717` | `#f2f0ef` |
| `--focus-ring` | `#b3101f` | `#ff5b5b` |
| `--radius` | `0.5rem` | (same) |
| `--shadow` | `0 1px 3px rgba(0,0,0,.12), 0 6px 16px rgba(0,0,0,.08)` | `none` (see below) |

**Conflict resolved:** `.success` moves off `--accent` onto its own
neutral `--success-bg`/`--success-fg` pair (a dark/light gray-on-gray
treatment, not red) — now that `--accent` is red, a success banner
reusing it would read as an error. `.error` and `.success` each also
get a 4px `border-left` in their `-fg` color, so the distinction isn't
color-alone (error's bar is red, success's is black/white) — reinforces
the existing a11y-conscious pattern in this codebase.

**Dark-mode shadows:** a black box-shadow is invisible on a near-black
background, so dark mode communicates elevation via `--bg-elevated` +
`--border` only; `--shadow` is `none` in dark mode rather than a
tuned-down shadow value.

## Typography & spacing

No new font files or CDN links — refining the existing system-font
stack (`system-ui, -apple-system, "Segoe UI", sans-serif`) with an
explicit scale, added to `style.css`:

- `--space-1` through `--space-6`: `0.25rem, 0.5rem, 0.75rem, 1rem,
  1.5rem, 2.5rem` — replaces today's ad hoc rem values.
- `h1`: `1.75rem`, weight `700`, `letter-spacing: -0.01em`.
- `h2`: `1.25rem`, weight `600`.
- Nav links: `0.9375rem`, weight `500`; active gets weight `700`.

## Layout components

- **`.card`**: `background: var(--bg-elevated)`, `border: 1px solid
  var(--border)`, `border-radius: var(--radius)`, `box-shadow:
  var(--shadow)`, `padding: var(--space-5)`. Applied to: the dashboard
  "last run" block, the SMTP form on Email, each grouped section on
  Data (Job cache / Sources), and the radio group on Preferences.
- **Buttons**: new `.btn-primary` (background `var(--accent)`, color
  `var(--accent-fg)`, no border) applied only to each page's single
  primary action — Dashboard's "Run now", Email's "Save", Source
  form's "Save". Every other button (Clear cache, Export/Import,
  Delete, Test this source) keeps today's neutral/secondary style
  unchanged. Deliberately **not** introducing a separate "danger" red
  for Delete — red is already carrying accent + error duty, and a red
  Delete button would visually compete with the primary-action red.
- **Header**: a `.brand` mark added before the main nav — a small hand-authored
  inline SVG logo combining a magnifying glass (circle + diagonal handle)
  with bent, jointed spider legs radiating from the lens on the side
  opposite the handle, `stroke="currentColor"`, colored via
  `.brand svg { color: var(--accent) }` so it follows the active theme
  automatically — a literal "spyder" mark. Followed by the "CareerSpyder"
  wordmark in bold `--fg` text. Inline SVG, not an `<img>` or external
  file — no new asset, no network fetch, nothing for `pyproject.toml`'s
  package-data list to miss. Header bottom border becomes `2px solid
  var(--accent)` instead of `--border`.
- **Nav (main + settings tabs)**: active state changes from underlined
  text to a pill: `padding: var(--space-2) var(--space-3)`,
  `border-radius: var(--radius)`, active link gets `background:
  var(--accent)`, `color: var(--accent-fg)`; inactive links get a
  `background: var(--bg-elevated)` hover state. Settings tabs
  (`settings_tabs.html`) get the same pill treatment, visually reading
  as a segmented control.
- **Tables**: `dashboard.html`/`sources_list.html`/`history.html` drop
  the inline `border="1" cellpadding="4"` attributes (legacy
  presentational HTML that predates the CSS and currently fights it).
  CSS instead: `border: 1px solid var(--border)`, `border-radius:
  var(--radius)`, `border-collapse: separate`, `border-spacing: 0`,
  row `border-bottom: 1px solid var(--border)` (no full grid lines),
  row hover `background: var(--bg-elevated)`, `th` bold + `--bg-elevated`
  background.

## Preferences tab

New third Settings tab, purely client-side — no new server storage,
matching how theme selection already works today and the earlier scope
decision to keep this a visual-only change.

| Method | Path | Behavior |
|---|---|---|
| GET | `/settings/preferences` | Renders a `<fieldset>` of three radio inputs — Light / Dark / System — inside a `.card`. No template variables, no POST route. |

- `templates/settings_tabs.html`: gains a third link, **Preferences**
  (`/settings/preferences`), appended after Data.
- `templates/settings_preferences.html`: new. Radio group,
  `name="theme"`, values `light`/`dark`/`system`, no submit button —
  selection applies immediately via JS, same immediacy as today's
  single toggle button.
- `app/web/routes_settings.py`: one new `GET` route,
  `show_settings_preferences`, same shape as `show_settings_data`.
- `static/theme.js` rewritten:
  - Reads `localStorage.getItem("theme")`; treats `null` the same as
    `"system"`.
  - If the Preferences radios are present on the page, checks the
    matching one and attaches `change` listeners.
  - On change: `"system"` → `localStorage.removeItem("theme")` and
    remove `data-theme` from `<html>` (falls back to
    `prefers-color-scheme`); `"light"`/`"dark"` → `localStorage.setItem`
    and set `data-theme` directly.
  - The old click-toggle-button logic is deleted entirely — no page
    outside Preferences has a theme control anymore.
- `templates/base.html`: `#theme-toggle` button removed from the
  header. The synchronous anti-FOUC inline `<script>` in `<head>` is
  **unchanged** — it already only special-cases stored `"light"`/`"dark"`
  and no-ops for `"system"`/absent, which is still correct.
- `/settings` continues to redirect to `/settings/email` (tab order:
  Email, Data, Preferences — appending keeps existing muscle memory for
  the first two tabs).

## Testing

Extends existing files, no new ones (Settings stays one route group,
per the precedent set in the #14 tabs spec):

`tests/web/test_settings.py`:
- `GET /settings/preferences` returns 200 and contains three radio
  inputs (`value="light"`, `value="dark"`, `value="system"`) (positive).
- `settings_tabs.html`'s Preferences link is present with
  `aria-current="page"` when on `/settings/preferences` (positive,
  mirrors the existing Email/Data active-state assertions).

`tests/web/e2e/`:
- Extend the existing theme e2e test: on `/settings/preferences`, click
  each of Light/Dark/System in turn, assert `data-theme` (or its
  absence, for System) updates and the computed background color
  changes; reload and assert the choice persisted.
- Extend the existing keyboard-tab-order test to include the
  Preferences tab link and the three radios.
- No changes expected to the pagination/table e2e assertions — table
  markup loses presentational attributes but keeps the same rows/cols.

No new tests needed for `app/db.py` or `app/config.py` — this spec
touches no backend data.

## Explicitly out of scope for this iteration

- **Server-stored preferences.** Confirmed scope decision: this is a
  visual-only pass. Theme stays localStorage-only, same as today.
- **New fonts, icon sets, or any asset requiring a network fetch or
  build step.** Typography changes are scale/weight only, on the
  existing system-font stack.
- **Danger/destructive button styling for Delete.** Not introduced —
  would overload red, which already carries accent + error meaning.
- **Any change to Email/Data tab request/response behavior.** Markup
  gains `.card` wrapping only; routes, form fields, and validation are
  untouched.
- **Authentication.** Already tracked in ROADMAP.md, unrelated.
