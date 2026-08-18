# PWA Support — Design Spec

Date: 2026-08-18
Status: Approved for planning

## Purpose

Make CareerSpyder installable as a Progressive Web App (Add to Home
Screen / standalone app window, own icon) on desktop and mobile.

## Decisions (from user clarification)

| Question | Decision |
|---|---|
| Prod HTTPS | Handled by a reverse proxy outside this repo; the app itself always sees plain HTTP. Full installability (which requires a secure context) is achievable as long as the proxy is in front of it — no code-side TLS work needed. |
| Scope of "offline" | **Installable only.** CareerSpyder is server-rendered against live SQLite-backed data (not a client-side SPA with a JSON API), so there is no meaningful way to browse jobs/sources while offline — that data is never cached client-side. The service worker exists to satisfy installability criteria and show a friendly offline fallback page; it does not cache app shell pages, CSS, or JS. |

## Icons (`app/web/static/icons/`)

Generated from the existing magnifying-glass brand mark already inline
in `base.html`'s header — not a new logo — rendered onto the app's
accent color (`#b3101f`, from `style.css`) as a solid background.

Generation method: a one-off script using Playwright (already a
project dependency, used elsewhere for adapter scraping) to render a
small HTML snippet containing the SVG mark at each target size and
screenshot it to PNG. This avoids adding a new image-processing
dependency for something run once, checked in, and never regenerated
at request time.

Files produced (all checked into git, not generated at runtime):

- `icon-192.png`, `icon-512.png` — purpose `"any"`, mark centered with
  normal padding.
- `icon-512-maskable.png` — purpose `"maskable"`, mark scaled down
  further so it survives Android's adaptive-icon safe-zone cropping
  (circle/squircle/rounded-square masks all applied by the OS, not the
  app).
- `apple-touch-icon-180.png` — iOS home screen icon; opaque background
  (iOS ignores transparency), same mark/padding as the `any` icons.
- `favicon-32.png` — the app currently has **no favicon at all**;
  adding one is a side effect of this work, not new scope.

## Manifest (`app/web/static/manifest.json`)

Served from the existing `/static` mount (no dedicated route needed —
unlike the service worker, a manifest's declared `scope` is not
restricted by where the manifest file itself lives).

```json
{
  "name": "CareerSpyder",
  "short_name": "CareerSpyder",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#b3101f",
  "icons": [
    { "src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "/static/icons/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

## Service worker (`app/web/static/sw.js`)

Deliberately minimal, matching the "installable only" decision above:

- `fetch` handler intercepts **navigation requests only** (actual page
  loads) — tries the network first, falls back to a cached
  `offline.html` if the network fetch fails. This single handler is
  all Chrome's installability check requires.
- CSS/JS/image/API requests are **not intercepted at all** — no
  caching, no stale-asset risk. This app's static filenames aren't
  cache-busted by content hash, so a service worker caching them would
  risk leaving a user on old JS/CSS indefinitely after a deploy. Not
  caching them sidesteps that failure mode entirely rather than
  building cache-invalidation logic to manage it.
- `install`: precaches only `offline.html` (and calls `skipWaiting()`
  so an update takes effect on next load rather than waiting for all
  tabs to close).
- `activate`: calls `clients.claim()`.

`app/web/static/offline.html` — a small standalone page (not a Jinja
template; it must render from the cache with zero network available),
branded consistently with the rest of the app, with a "You're offline"
message and a retry button that just calls `location.reload()`.

## Serving the service worker (`app/web/routes_pwa.py`, new)

A service worker's registration scope defaults to the directory it's
served from. Serving `sw.js` through the existing `/static` mount
would limit it to `/static/*`, which is useless — it needs to control
navigation for the whole app. New minimal router:

```python
router = APIRouter()

@router.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        _STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )
```

`Cache-Control: no-cache` matters as much as `Service-Worker-Allowed`
here: browsers otherwise apply normal HTTP caching to the worker
script itself, which can leave a user's browser running stale worker
logic (including a stale offline page) long after a new version ships.
Registered in `app/web/main.py` alongside the other feature routers.

## Integration (`app/web/templates/base.html`)

- `<link rel="manifest" href="/static/manifest.json">`
- `<meta name="theme-color" content="#b3101f">`
- `<link rel="icon" href="/static/icons/favicon-32.png">` and
  `<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon-180.png">`
- A deferred inline script, alongside the existing theme/nav scripts:
  ```js
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" });
  }
  ```

## CSP (`app/web/security_headers.py`)

No changes needed. `default-src 'self'` already covers the manifest
fetch, and CSP's `worker-src` falls back to `script-src` when unset,
which is already `'self'` — same-origin `sw.js` is allowed.

## Testing

- `tests/web/test_pwa.py` (new): `GET /sw.js` returns 200,
  `application/javascript`, and both the `Service-Worker-Allowed` and
  `Cache-Control: no-cache` headers.
- `tests/web/test_guide.py`-style check (or an addition to an existing
  base-template test, if one exists) that `/` includes the manifest
  link and theme-color meta tag.
- **Not automated**: actual service-worker install/offline-fallback
  behavior is real browser runtime behavior this project's test setup
  can't exercise (no headless-browser test runner for JS). Verified
  manually in a real browser — DevTools → Application → confirm
  install prompt eligibility, then simulate offline and confirm
  `offline.html` appears — before calling this done. Same precedent as
  `app/adapters/browser.py`'s `render_html()` and `infor.py`'s
  `default_frame_fetcher`, both verified by manual smoke test only.
- Icon generation script is a one-off dev tool, not part of the test
  suite or the shipped app — it's not imported by any runtime code
  path.

## Documentation + version

- `pyproject.toml`: `0.34.0` → `0.35.0`.
- `CHANGELOG.md`: new `### Added` entry under `[Unreleased]` — PWA
  install support (manifest, icons, minimal offline-fallback service
  worker); app also gains a favicon for the first time.
- `docs/USAGE.md` / `README.md`: a short new line noting the app can
  be installed from the browser's install/Add-to-Home-Screen prompt.

## Explicitly out of scope

- Any offline browsing of actual job/source data — this app has no
  client-side data layer to cache into; that would be a separate,
  much larger project (client-side API + IndexedDB) with its own
  design, not a natural extension of this one.
- Caching CSS/JS/static assets in the service worker for faster repeat
  loads — explicitly declined in favor of avoiding stale-asset bugs,
  given there's no cache-busting scheme for static filenames today.
- Push notifications, background sync, periodic background sync — none
  requested; each would need its own permission/UX/backend design.
- An automated JS/browser test runner for service-worker behavior —
  this repo has no JS test infrastructure at all (per the existing Job
  Map spec's same note about `map.js`), and adding one is out of scope
  for a single feature.
- Regenerating icons at build/request time — they're static, checked-in
  assets; the generation script is a manual one-off, not wired into
  CI or the Docker build.
