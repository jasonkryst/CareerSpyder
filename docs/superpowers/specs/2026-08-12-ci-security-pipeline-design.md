# CI/Security Pipeline — Design Spec

Date: 2026-08-12
Status: Approved for planning

## Purpose

CareerSpyder currently has no CI. Every check (tests, Docker build,
security posture) is manual and depends on someone remembering to run it.
This adds a GitHub Actions pipeline that runs tests, static analysis,
dependency and container vulnerability scanning, and a Docker build+smoke
test on every pull request and every push to `master`, plus two repo-level
security settings (secret scanning + push protection, and branch
protection requiring these checks to pass before merge).

Repo: `jasonkryst/CareerSpyder` (public — CodeQL, secret scanning, and
Dependabot are free on public repos, so no cost tradeoffs factor into tool
choice).

## Baseline findings (informational — folded into the plan, not new scope)

Checked against current `master` (`d28a313`) before writing this spec:

- `pip-audit` against declared dependencies: **zero known vulnerabilities.**
- `ruff check app tests` (default rule set): **9 findings, 8
  auto-fixable** (mostly `Optional[X]` → `X | None` modernization, one
  blind `except Exception` in `routes_sources.py`).
- `mypy app` (no existing config, straightforward default settings):
  **19 errors across 9 files** — real gaps, not mypy noise:
  - `app/db.py:80` — `finish_run`'s helper returns `int | None` where the
    caller expects `int`.
  - `app/web/routes_settings.py:21-22` — form values are typed
    `str | UploadFile` by Starlette (forms can carry file uploads); the
    settings route passes them straight into `int()`/`save_settings`
    without narrowing, so a malicious/malformed multipart body with a
    file field named `smtp_port` would misbehave instead of failing
    cleanly.
  - `app/adapters/indeed.py`, `app/adapters/generic_html.py` — `href` from
    BeautifulSoup is typed as `str | AttributeValueList | None`;
    `urljoin` is called without narrowing to `str` first.
  - `app/adapters/linkedin.py:19` — same `AttributeValueList | None`
    narrowing gap, on `.split()`.
  - `app/web/source_form.py:59`, `app/orchestrator.py:36` — dynamic
    dispatch through `TYPE_MODELS`/`ADAPTERS` dicts isn't typed precisely
    enough for mypy to follow; needs an explicit cast or a `Callable`
    type alias, not a real bug.
  - `app/web/routes_sources.py:93` — needs an explicit type annotation on
    `jobs` since it comes back through `run_in_threadpool`'s generic
    signature.
  - `app/scheduler.py:20-21` — `db.get_settings` returns `dict | None`;
    `run_and_notify` indexes it without a None-check, which is a real
    latent bug (would raise a confusing `TypeError` instead of the
    intended "settings not configured yet" behavior).

These get fixed as part of this work (see Task breakdown expectations
below) so `mypy app` and `ruff check` can be enabled as genuine, currently
green gates rather than gates added pre-broken.

## Architecture

Three workflow files, split by speed/purpose rather than either one
mega-workflow or one job per file:

```
.github/workflows/ci.yml       lint + typecheck + test + dependency-audit
                                 (fast, always-on code-quality gate)
.github/workflows/docker.yml    docker build + Trivy image scan + smoke test
                                 (slower — image build + Chromium install)
.github/workflows/codeql.yml    CodeQL SAST for Python
                                 (idiomatic to keep separate: needs its own
                                 security-events: write permission scope,
                                 and runs on a schedule in addition to
                                 push/PR)
.github/dependabot.yml          weekly automated PRs for pip + Actions deps
```

Every workflow triggers on `pull_request` and `push` to `master`.
`codeql.yml` additionally runs on a weekly `schedule` (Monday 06:00 UTC)
so newly-published CodeQL query patterns get applied to code that hasn't
changed recently — the other checks have no reason to run on a schedule
since they only reflect what's in the diff.

### `ci.yml`

Four jobs, all on `ubuntu-latest`, Python 3.12 (pinned to match the
`Dockerfile`'s `python:3.12-slim`, closing the version-drift gap called
out in `ROADMAP.md`). Each job does its own `actions/checkout` +
`actions/setup-python` + `pip install -e ".[dev]"` (plus its one extra
tool) rather than sharing a setup job — these installs are seconds, and
independent jobs can run in parallel and fail independently without a
shared-setup single point of failure.

- **`lint`**: `ruff check app tests`. Fails the build on any finding.
- **`typecheck`**: `mypy app` (not `tests` — test files use patterns like
  dynamic fixture construction that aren't worth fully annotating; this
  matches common practice of type-checking application code, not test
  code). Fails the build on any error.
- **`test`**: `pytest -q`. No live network calls or real browser launches
  occur (existing project constraint, unchanged) — this job needs no
  Playwright install, keeping it fast.
- **`dependency-audit`**: `pip-audit` against the installed environment.
  Fails the build on any known CVE in a resolved dependency.

### `docker.yml`

One job:

1. `docker build -t careerspyder:ci .`
2. `aquasecurity/trivy-action` scans the built image; `severity:
   CRITICAL,HIGH`, `exit-code: 1` — fails the build on any CRITICAL/HIGH
   finding in OS packages or Python dependencies baked into the image.
   MEDIUM/LOW are reported (uploaded as a SARIF artifact, visible in the
   Security tab) but don't fail the build — that threshold keeps the gate
   meaningful rather than perpetually red on transitive base-image noise,
   while still surfacing lower-severity findings for review.
3. Smoke test: `docker compose up -d` with a throwaway `.env` (dummy SMTP
   values — no real send is attempted since a fresh `sources.json` finds
   nothing to report), poll until `/` responds, then `curl` each of `/`,
   `/sources`, `/history`, `/settings` and assert HTTP 200. `docker
   compose down` in an `if: always()` cleanup step so a failed assertion
   still tears the container down. This automates the exact manual smoke
   test performed for the v1 release.

### `codeql.yml`

Generated via GitHub's standard `github/codeql-action` init/analyze
pattern, `languages: python`, default query suite (`security-and-quality`
is worth considering over the bare default — see Open Questions). Needs
`permissions: security-events: write` (and `contents: read`) scoped to
just this workflow.

### `dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule: { interval: weekly }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
```

Opens PRs automatically; those PRs go through the same `ci.yml` /
`docker.yml` / `codeql.yml` gates as any other PR before merge.

## Repo settings (applied via `gh api` / `gh` CLI, not a workflow file)

- **Secret scanning + push protection**: GitHub-native feature, enabled
  at the repo level. Push protection rejects a push containing a
  recognized credential pattern (API keys, tokens, etc.) before it's
  even accepted, which is stronger than scanning after the fact.
- **Branch protection on `master`**: require status checks `lint`,
  `typecheck`, `test`, `dependency-audit` (from `ci.yml`), the Docker job
  (from `docker.yml`), and the CodeQL analyze job to pass before a PR can
  merge. Applied last, after the new workflows have run at least once on
  the implementation PR itself (a required check that has never reported
  a status blocks merging until it does — so this gets turned on only
  once the checks exist and are passing).

## Testing / verification plan

There's no unit-testable "logic" here in the traditional sense — the
deliverable is CI configuration. Verification is:

- Open the implementation as a real PR against `master` and watch all
  three workflows actually run and go green (or, for the mypy/ruff fixes,
  watch them go green after being red on the first push — proving the
  gate is real, not accidentally always-passing).
- Deliberately break something on a throwaway commit within the PR branch
  to confirm each gate actually fails: e.g. reintroduce one of the mypy
  errors, temporarily bump a dependency to a known-vulnerable version,
  temporarily break `pytest`. Revert before merge. This is the
  closest equivalent to a test suite for a CI pipeline.
- Confirm the Docker smoke-test job fails if a page 500s (verified by
  intentionally deleting a template file on a throwaway commit and
  watching the smoke test catch it), then revert.

## Out of scope for this iteration

- **Deployment automation** (auto-deploy to the Proxmox host on merge).
  Not requested; the project's deploy model today is manual `docker
  compose up` on the host, and this pipeline only verifies the image
  *would* work, it doesn't ship it anywhere.
- **SBOM generation.** Natural follow-on to the container scan
  (`trivy` can emit one), but not requested — noted as a ROADMAP
  candidate rather than built now.
- **Multi-version Python test matrix.** The Dockerfile pins one version
  (3.12); testing against other versions would verify something the
  deployed artifact never uses. Revisit if the project ever needs to
  support being installed outside its own container.
- **mypy on `tests/`.** See `ci.yml` section above for rationale.

## Open question for implementation

Should CodeQL use the default query suite or
`security-and-quality` (broader, includes code-quality queries beyond
pure security)? Defaulting to the standard/default suite for this PR to
keep noise low on a first rollout; can be widened later once the team has
a feel for the baseline signal-to-noise ratio. Flagging here rather than
blocking the design on it since it's a one-line config value change,
reversible with no structural impact.
