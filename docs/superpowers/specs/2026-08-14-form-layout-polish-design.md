# Form Layout & CSS Polish — Design Spec

Date: 2026-08-14
Status: Approved for planning

## Purpose

Every form in the app (`source_form.html`, `settings_email.html`,
`settings_data.html`, `settings_preferences.html`) uses the same
`<label>Text <input></label><br>` pattern from before the red/white/black
theme pass (`2026-08-14-modernized-theme-preferences-design.md`). Label
text and its input run together inline on one crowded line, spacing
between fields comes from a mix of `<br>` tags and `label`'s
`margin-bottom` (uneven), and only `input[type="text"]`/`input[type="number"]`
are styled — `select`, checkboxes, radios, and the file input are raw
browser defaults that visually clash with everything else on the page.
`source_form.html` in particular is a long form (12+ possible fields
depending on source type) with no visual separation between its three
logical sections: static fields (Name/Company/Type), the dynamic
per-type fields, and the shared keyword filters.

Scope, per discussion: **CSS and template whitespace/structure only** —
no new routes, no `name=`/`value=` attribute changes, no new form fields
or validation. A version bump to 0.6.0 accompanies this release, per the
established pattern of dating a CHANGELOG release to the work it ships.

## Current state

`static/style.css` styles `input[type="text"]`/`input[type="number"]`
(border, radius, padding, full-width up to `max-width: 28rem`) and
`label { display: block; margin-bottom: var(--space-3) }`, but every
template still separates fields with `<br>` inside the label, and no
rule touches `select`, `input[type="checkbox"]`, `input[type="file"]`, or
`input[type="radio"]`. `source_form.html`'s per-type fields already live
in `id="fields-{type}" class="type-fields"` wrapper `<div>`s (toggled via
`showFieldsFor()` in the existing inline `<script>`), which gives a
ready-made hook for grouping styles without any JS or route change.

## Decision: stack labels via CSS only, no markup restructuring

Every field's markup is already `<label>Text <input></label>` — the input
is a child of the label, not a sibling. That means `label { display:
flex; flex-direction: column }` stacks the label's text node above its
input purely through CSS; no template needs to change its label/input
structure. Checkboxes and radios get an exception —
`label:has(> input[type="checkbox"]), label:has(> input[type="radio"])
{ flex-direction: row; align-items: center }` — so those stay box-then-text
inline, which is the correct pattern for a single toggle/choice (stacking
"[ ]" above "Render JS" would look wrong). `:has()` is used deliberately:
this app is explicitly "a trusted home/private network only" tool with no
stated browser-support floor, and every current browser (Chrome/Edge/Safari/Firefox
122+) supports it.

## CSS changes (`static/style.css`)

- `label`: `display: flex; flex-direction: column; align-items: flex-start;
  gap: var(--space-1);` (replaces `display: block`). Keeps its existing
  `margin-bottom: var(--space-3)` for field-to-field spacing.
- New: `label:has(> input[type="checkbox"]), label:has(> input[type="radio"])`
  → `flex-direction: row; align-items: center; gap: var(--space-2);`
- `select` joins the existing `input[type="text"], input[type="number"]`
  rule (same border/radius/padding/width/max-width).
- New: `input[type="checkbox"], input[type="radio"] { accent-color:
  var(--accent); width: 1.05rem; height: 1.05rem; }` — recolors the
  native control to match the theme with zero JS or custom-control
  markup.
- New: `input[type="file"]` gets the same `border`/`border-radius` as
  text inputs (browsers already render file inputs as a button + text,
  which can't be fully restyled without JS; this just gives it a
  consistent outer border/padding so it doesn't look like a stray
  unstyled element next to styled fields).
- New: `.type-fields` (source form's per-type field groups) gets
  `border-left: 3px solid var(--border); padding-left: var(--space-4);
  margin-bottom: var(--space-4);` when it has visible content — applied
  unconditionally in CSS (empty `.type-fields` divs, e.g. `#fields-lever`,
  render with zero height regardless of the border, so no empty-state
  edge case to handle).

## Template changes

- `source_form.html`, `settings_email.html`, `settings_data.html`: remove
  every `<br>` between a `</label>` and what follows — spacing now comes
  entirely from `label`'s `margin-bottom` once labels are stacked.
  (`settings_preferences.html` already has no `<br>`; unaffected.)
- `source_form.html`: add a `<div class="card">` around the two trailing
  keyword fields (Include/Exclude keywords), visually separating them
  from the per-type fields above — reusing the existing `.card` class
  rather than introducing a new grouping mechanism.
- No changes to any `name=`, `value=`, `id=`, or `action=` attribute on
  any field, anywhere — this is a purely visual/structural pass.

## Testing

Extends existing files, no new ones:

`tests/web/test_base.py`:
- `style.css` defines the new `select`-inclusive input rule, the
  checkbox/radio `accent-color` rule, and `.type-fields` border rule
  (presence-of-string checks, matching this file's existing pattern for
  CSS assertions).

`tests/web/test_source_form.py`:
- `GET /sources/new` response contains no `<br>` (negative check that the
  cleanup landed) — content of dynamic fields is otherwise unaffected, so
  every existing positive test (field values round-tripping through
  save/edit) is untouched.

`tests/web/test_settings.py`:
- `GET /settings/email` and `GET /settings/data` responses contain no
  `<br>`.

No e2e changes expected — the keyboard tab-order and theme-radio e2e
tests exercise the same elements in the same DOM order (`<label>`
wrapping is unchanged, only its CSS layout direction changes), and the
responsive no-horizontal-overflow test already covers `/sources`, whose
table markup is untouched here.

## Explicitly out of scope for this iteration

- **Custom-styled file input (JS button replacement).** Native file
  inputs can't be fully restyled with CSS alone; a JS-driven custom
  control is a bigger change than "CSS and template whitespace" scope
  allows. The native control gets a matching border only.
- **New form fields, validation, or client-side field errors.** Purely
  layout/CSS.
- **Two-column / side-by-side label+input layout.** Considered and
  rejected in favor of stacked labels (see Decision above).
- **Restyling `<select>`'s dropdown arrow/native popup.** Out of reach
  without a custom-select JS component; the closed-state box is styled
  to match text inputs, the browser-native open state is left as-is.
