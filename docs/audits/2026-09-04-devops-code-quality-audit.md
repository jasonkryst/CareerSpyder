# DevOps / code quality audit — 2026-09-04

A read-only audit of CareerSpyder's CI/CD pipeline, Docker/deployment setup,
configuration & secrets handling, code quality/maintainability, developer
documentation, and dependency health, as of `v0.56.1`.

This audit does **not** cover application-level functional correctness,
web security (CSRF/SSRF/XSS/auth), accessibility, i18n, performance, or the
SQLite schema/query layer in depth — those are covered by
[2026-08-19-app-audit.md](2026-08-19-app-audit.md),
[2026-09-04-core-functionality-audit.md](2026-09-04-core-functionality-audit.md),
[2026-09-04-database-audit.md](2026-09-04-database-audit.md),
[2026-09-04-i18n-audit.md](2026-09-04-i18n-audit.md), and
[2026-09-04-performance-audit.md](2026-09-04-performance-audit.md), and
are cross-referenced rather than re-litigated here.

## Scope & methodology

Static, read-only review — no code was modified, no fixes were
auto-applied. Reviewed:

- `.github/workflows/{ci,docker,codeql}.yml`, `.github/dependabot.yml`,
  and live branch-protection settings (`gh api
  repos/:owner/:repo/branches/master/protection`) and recent workflow
  run history (`gh run list`).
- `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`,
  `docker-entrypoint.sh`, `.dockerignore`.
- `.env.example`, `.gitignore`, the untracked repo-root `.env`, and every
  `os.environ.get(...)` call site (`app/web/main.py`, `app/scheduler.py`).
- Ran `python -m ruff check .` (full repo) and `python -m mypy` (per
  `pyproject.toml`'s `[tool.mypy]` config) and read the output in full.
- Ran `python -m pip_audit` against the dev environment.
- Read `app/db.py`, `app/orchestrator.py`, all 11 files in `app/adapters/`,
  `app/config.py`, and `app/adapters/__init__.py` for structure,
  duplication, and error-handling consistency.
- Spot-checked `README.md`, `AGENTS.md`, `ROADMAP.md`, `docs/USAGE.md`,
  `SECURITY.md`, and `pyproject.toml`'s dependency table against the
  current code.

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 3 |
| Low | 4 |
| Informational | 6 |

Overall picture: the pipeline and image are in good shape — ruff and mypy
are both fully clean, branch protection gates on 7 required checks, the
Docker image runs as non-root with a digest-pinned base and a real Trivy
gate, and the recent port-32600 fix is applied correctly and consistently
everywhere (compose files, CI smoke test, README, CHANGELOG). The findings
below are pipeline-hygiene and maintainability items, not breakage.

## Findings

### Medium

#### M1 — `docker.yml`'s `release: published` trigger never publishes anything

`.github/workflows/docker.yml:3-9` declares `release: { types: [published]
}` as a trigger, but every step that actually reads the version and pushes
to Docker Hub is gated `if: github.event_name == 'push'`
(`.github/workflows/docker.yml:114,121,128`). A published GitHub Release
therefore runs a full build + Trivy scan + smoke test (several CI-minutes)
and pushes nothing — the image for that version was already published
earlier by the `push`-to-`master` event that (presumably) preceded cutting
the release. Confirmed against live run history: run `33770071131`
("v0.56.1", trigger `release`) has no login/push steps in its log path,
while run `33768667535` ("...(#130)", trigger `push`) is the one that
actually tagged and pushed `0.56.1`.

This isn't broken, but it's misleading — a maintainer publishing a Release
expecting it to (re)publish/re-tag the image on Docker Hub will get a
no-op, and every release burns a redundant ~2-minute build+scan job.

**Fix:** either drop the `release` trigger entirely (the `push`-to-`master`
event already publishes every version bump), or make it functional —
change the push-gating condition to `if: github.event_name == 'push' ||
github.event_name == 'release'` so a Release actually re-tags/re-pushes
the already-built image.

#### M2 — `dependency-audit` CI job is not required, and is currently red

`.github/workflows/ci.yml:40-48` runs `pip-audit` in the `dependency-audit`
job, and it **is** listed as a required status check in branch protection.
Running it locally today: `pip-audit` reports one finding —
`PYSEC-2026-3721` in `pip 26.1.2` itself (fix: `26.2`), causing exit code
1. `pip` is not an app dependency (`pyproject.toml` doesn't list it; the
production image explicitly uninstalls it — `Dockerfile:20-21`) — it's
whatever version `actions/setup-python` bakes into the CI runner's Python
3.12 install, which the workflow doesn't pin or upgrade before running
`pip-audit`. Because this check is required for merge, a newly-published
pip advisory can turn every open PR's merge gate red with a finding that
has nothing to do with the app's actual dependencies, and no `pip-audit`
config in the repo (`--ignore-vuln`, a vuln allowlist file, etc.) exists to
distinguish "app dependency vulnerable" from "the audit tool's own
transitive pip is vulnerable."

**Fix:** add `pip install --upgrade pip` before the `pip-audit` step in
`.github/workflows/ci.yml:47`, or pass `--require-hashes`/skip auditing
`pip` itself via `pip-audit`'s `--ignore-vuln` flag for advisories that
are about `pip` and not resolved into the shipped image.

#### M3 — Config/secrets loading is duplicated and unvalidated across two files

There is no central settings/config module for environment variables.
`os.environ.get(...)` calls for the same six variables documented in
`.env.example` are duplicated between `app/web/main.py:21-24` (used to
seed the DB and construct the scheduler) and `app/scheduler.py:29-33,45`
(used again at run time, with its own separate defaults — e.g.
`RUN_CRON` default `"0 7 * * *"` appears in both `main.py:23` and
`.env.example:18` and `docker-compose.yml:15`/`docker-compose.prod.yml:14`
as `${RUN_CRON:-0 7 * * *}`, four independent copies of the same default
string that must be kept in sync by hand). None of these reads validate
early — `int(os.environ.get("SMTP_PORT", "587"))` at
`app/web/main.py:30` will raise an unhandled `ValueError` at startup
(not a clean config error) if `SMTP_PORT` is set to a non-numeric string
in the environment, rather than failing with an actionable message.

**Fix:** not urgent given the current small surface area, but worth a
single `app/settings.py` (a small `pydantic-settings` `BaseSettings` or
plain dataclass) that reads and validates all env vars once at startup,
used by both `main.py` and `scheduler.py`, so the four independent
`RUN_CRON` default copies collapse to one and a malformed `SMTP_PORT`
fails with a clear message instead of a raw traceback.

### Low

#### L1 — No process supervisor as PID 1; Playwright/Chromium subprocess reaping is unverified

`docker-entrypoint.sh:11` does `exec setpriv --reuid=1000 --regid=1000
--init-groups "$@"`, so the final `uvicorn` process runs as PID 1 inside
the container (uvicorn does install its own SIGTERM/SIGINT handlers, so
graceful shutdown itself is fine). What's unverified is orphan/zombie
reaping: PID 1 has no default `SIGCHLD`/reaping behavior unless the
process explicitly waits on every child, and this image runs
Playwright-launched Chromium subprocesses (`linkedin`/`indeed`/
`generic_html` with `render_js: true`) as descendants of that same PID 1.
A crashed or improperly-terminated Chromium child would become a zombie
that nothing reaps, accumulating slowly across scrapes on a long-lived
container. Playwright/asyncio's subprocess handling usually waits
correctly, so this is speculative rather than confirmed — flagging as a
cheap, standard hardening step rather than a demonstrated bug.

**Fix:** add `tini` (or Docker's built-in `--init` flag, which
`docker-compose.yml`/`docker-compose.prod.yml` can set via `init: true`)
ahead of the `setpriv` exec so an init process reaps orphans regardless of
what any given child process does.

#### L2 — `app/db.py` is a single 630-line, 33-function flat module

`app/db.py` has 33 module-level functions covering runs, settings,
job CRUD/filtering, location overrides, status history, and duplicate
marking — all against one SQLite connection with no grouping by class or
submodule. It's internally consistent (uniform `conn: sqlite3.Connection`
first-arg convention, consistent parameterized-query style) and ruff/mypy
are clean on it, so this is a readability/navigability concern rather than
a correctness one — a new contributor has to scroll a 630-line file to
find, e.g., the location-override functions. The dedicated
[database audit](2026-09-04-database-audit.md) covers correctness/schema
concerns for this file in depth and didn't flag its size, so this is
purely a "would benefit from splitting" note.

**Fix (optional, low priority):** split by concern into
`app/db/runs.py`, `app/db/jobs.py`, `app/db/settings.py` re-exported from
`app/db/__init__.py`, preserving the current flat `db.func_name(conn,
...)` call sites everywhere else in the codebase.

#### L3 — Dependency version constraints are all one-sided (`>=`, no upper bound)

Every runtime dependency in `pyproject.toml:8-16` (`fastapi`, `uvicorn`,
`jinja2`, `python-multipart`, `pydantic`, `apscheduler`, `requests`,
`beautifulsoup4`, `playwright`) and every dev dependency
(`pyproject.toml:19-26`) is pinned `>=X` with no upper bound. This is
already tracked as finding L3 in
[ROADMAP.md](../../ROADMAP.md#security--access) from the prior app audit,
so not re-scored here, but worth restating in a DevOps context: combined
with weekly Dependabot PRs for `pip` (`.github/dependabot.yml:1-4`), a
breaking major-version release from any of these (e.g. a hypothetical
Pydantic 3 or FastAPI 1.0) would install cleanly on the next `pip install
-e .` with no version ceiling to stop it, and would only be caught if the
Dependabot PR's CI run happens to exercise the breaking surface.

**Fix:** either accept the current all-Dependabot-driven-upgrade model
(reasonable for a single-maintainer project, since Dependabot PRs go
through the same required CI gate as any other PR), or add upper bounds
on the handful of dependencies most likely to ship breaking majors
(`fastapi`, `pydantic`).

#### L4 — `docker-compose.yml`'s bind-mount and `docker-compose.prod.yml`'s named-volume divergence isn't documented as a migration concern

`docker-compose.yml:20-22` bind-mounts `./config` and `./data` (host
directories, matching local dev), while `docker-compose.prod.yml:19-21`
uses named volumes `careerspyder_config`/`careerspyder_data`. Per prior
session context, prod actually runs with **bind mounts to absolute
`/opt/careerspyder/*` paths** via manual Portainer pulls, not this
committed `docker-compose.prod.yml`'s named volumes — meaning
`docker-compose.prod.yml` as checked into the repo does not reflect the
real production deployment mechanism (Portainer's manual image pull /
bind-mount setup) and would produce a different (named-volume-backed)
deployment if actually run with `docker compose -f docker-compose.prod.yml
up`. This isn't a bug in the file itself, but it means the file is
effectively reference/documentation-only and could mislead a contributor
who runs it expecting to reproduce prod.

**Fix:** add a one-line comment at the top of `docker-compose.prod.yml`
noting that actual production uses Portainer with bind-mounted
`/opt/careerspyder/*` paths and this file is a starting-point reference,
not what's literally deployed — or update the file's `volumes:` block to
match the real bind-mount paths so it's directly usable.

### Informational

#### I1 — Ruff and mypy are both fully clean

`python -m ruff check .` → `All checks passed!` (0 issues, including the
`S` flake8-bandit ruleset extended in `pyproject.toml:31`). `python -m
mypy` (using `pyproject.toml`'s `[tool.mypy]` — `files = ["app"]`) →
`Success: no issues found in 43 source files`. No suppressed/ignored rules
beyond the two narrowly-scoped, commented `S608` exceptions for
`app/db.py` (`pyproject.toml:33-37`, justified inline). This is a clean
bar to hold — worth calling out explicitly since it's easy for this kind
of audit to read as all-negative.

#### I2 — Adapters are lean and consistently shaped; no urgent case for a shared base class

All 11 `app/adapters/*.py` modules (19–91 lines each) follow the same
`fetch(source, http_get=requests.get) -> list[Job]` (or
`html_renderer=`) dependency-injected shape per `AGENTS.md`'s documented
convention. There is light structural duplication (each builds a `Job(...)`
from a differently-shaped API response, each does `resp.raise_for_status()`
then `resp.json()`), but the API responses are different enough per
platform (Greenhouse's `jobs[]` vs. Lever's top-level array vs. Infor's
paginated HTML) that a shared base class would mostly relocate rather than
reduce the platform-specific mapping logic. Per-source failure handling is
centralized once in `app/orchestrator.py:41-47` (a single `try/except`
around the adapter call), not duplicated per-adapter — this is the right
place for it and avoids the inconsistent-error-handling pattern this audit
was asked to check for.

#### I3 — `.env` handling is correctly gitignored and contains no real secrets

`.gitignore:9` covers `.env`; `git log --all -- .env` returns no history
(never committed); `git check-ignore -v .env` confirms the currently
present repo-root `.env` is untracked. Its contents are CI-placeholder-style
values (`SMTP_PASSWORD=ci-placeholder`, `EMAIL_FROM=ci@example.test`), not
real credentials. `.env.example` (`.env.example:1-2`) explicitly documents
"never commit real credentials." No secrets-handling risk found. One
unrelated hygiene note: this local `.env` uses a stale `RUN_HOUR=8` key
instead of the current `RUN_CRON` (used by `app/scheduler.py:31` and
documented in `.env.example:16-18`) — harmless since it's untracked and
`scheduler.py` simply falls back to its default when `RUN_CRON` is unset,
but worth regenerating from `.env.example` to avoid confusion.

#### I4 — Branch protection is well configured

`master` requires 7 status checks (`lint`, `typecheck`, `test`,
`dependency-audit`, `build-scan-smoketest`, `Analyze Python`, `CodeQL`),
`strict: true` (branches must be up to date before merging),
`enforce_admins: true`, and force-pushes/deletions disabled. The one gap:
`ci.yml`'s `trivy-fs` job (filesystem-level dependency vulnerability scan,
`.github/workflows/ci.yml:50-73`) is **not** in the required-checks list —
it uploads to GitHub Security but doesn't gate merges. Given
`build-scan-smoketest` in `docker.yml` already runs an equivalent
image-level Trivy scan and **does** gate merges (with `exit-code: 1` on
CRITICAL/HIGH findings), this is a minor, low-priority gap rather than an
open door.

#### I5 — `ROADMAP.md` has one stale claim: Dockerfile's pinned Python version

`ROADMAP.md:126` ("Local dev environment doesn't match the deploy
runtime") states `` The `Dockerfile` pins `python:3.12-slim` ``, but
`Dockerfile:1` currently pins `python:3.14-slim@sha256:ce40764...`
— the base image has been bumped since that ROADMAP entry was written,
but the entry's text wasn't updated to match (`AGENTS.md:12` also still
says "Python 3.12" for the documented dev runtime, which is technically
still true per `pyproject.toml`'s `requires-python = ">=3.12"`, just not
what's actually running in the shipped image). Everything else
spot-checked against current code was accurate: README's Docker port
references (`README.md:121,329`) correctly reflect the `32600` fix,
`docs/USAGE.md`'s UI walkthrough matches the routes actually registered,
and `AGENTS.md`'s non-negotiable-constraints section matches
`app/web/security_headers.py`/`app/digest.py` behavior as implemented.

**Fix:** update `ROADMAP.md:126` to say `python:3.14-slim` (or drop the
specific version number and just say "pin/document a matching local
Python version," since the underlying ask — keep local dev and the image
on the same interpreter — still stands regardless of which version).

#### I6 — Dockerfile is intentionally single-stage; already reasonably minimal for the workload

Not multi-stage, but the image legitimately needs a full Python + apt
toolchain at runtime (Playwright's Chromium binary and its native
dependencies, installed via `playwright install --with-deps chromium` at
`Dockerfile:26`) — a multi-stage split wouldn't shrink much since the
heaviest layer (Chromium + its shared libs) has to exist in the final
stage regardless. The image already: pins the base by digest
(`Dockerfile:1`), runs `apt-get upgrade` for OS security patches
(`Dockerfile:8`), uninstalls `pip` post-install to drop its vendored
`msgpack`/`setuptools` copies (`Dockerfile:16-21`), uses a fixed
non-auto-assigned UID/GID (`Dockerfile:33-36`), and is gated by a
CRITICAL/HIGH Trivy scan in CI (`docker.yml:49-56`). No action needed;
noting this so the "multi-stage?" audit question isn't read as a gap.

## Dependency health

`pyproject.toml:8-16` runtime deps are all reasonably current
(`fastapi>=0.141.1`, `pydantic>=2.13.5`, `playwright>=1.62.0`, etc.) with
weekly Dependabot coverage across `pip`, `github-actions`, and `docker`
ecosystems (`.github/dependabot.yml`) — recent bot PRs (`#124`, `#125`,
`#126`, and an in-flight `dependabot/docker/python-cad9a2c` base-image
bump) show the automation is active and its PRs pass CI. No deprecated or
abandoned packages found in the dependency list. The one structural gap is
the lack of upper-bound pins, covered as L3 above (already tracked
upstream in ROADMAP.md).

## CI/CD detail notes

- **What runs on PR/push:** `ci.yml` — `lint` (`ruff check app tests`),
  `typecheck` (`mypy`), `test` (`pytest -q --cov=app
  --cov-report=term-missing`, including `playwright install --with-deps
  chromium` for the e2e suite), `dependency-audit` (`pip-audit`, see M2),
  and `trivy-fs` (filesystem CVE scan, see I4). `docker.yml` — Hadolint
  Dockerfile lint, `docker compose build`, Trivy image scan (gating,
  CRITICAL/HIGH), a real container start + non-root-process verification
  + 6-page HTTP smoke test, then (on `push` to `master` only — see M1)
  version-tag + Docker Hub push. `codeql.yml` — CodeQL Python analysis on
  PR/push plus a weekly Monday cron.
- **Required before merge:** yes, all 7 checks (I4).
- **Release/publish pipeline:** exists, publishes to Docker Hub as
  `jasonkryst/careerspyder:latest` and `:<version>` on every push to
  `master` where `pyproject.toml`'s version was bumped; the `release:
  published` trigger's push side is currently a no-op (M1).
- **Automated dependency updates:** yes, `.github/dependabot.yml`, weekly,
  covering `pip`/`github-actions`/`docker`.
- **Secrets handling in workflows:** `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN`
  are read from `secrets.*` (`docker.yml:124-125`) and never echoed;
  `docker.yml:62-71`'s CI-only `.env` heredoc uses placeholder values only
  (`ci-placeholder`, `ci@example.test`), not a real credential. No secrets
  found hardcoded anywhere in workflow YAML.
