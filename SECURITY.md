# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via [GitHub Security
Advisories](https://github.com/jasonkryst/CareerSpyder/security/advisories/new)
rather than a public issue. Include reproduction steps and the affected
version (`pyproject.toml`'s `version`, or the image tag if using Docker).

## Supported versions

Only the latest `master`/release is supported. There's no LTS branch —
apply updates by pulling the latest image or re-deploying from `master`.

## Known, accepted posture (not a vulnerability report)

CareerSpyder v1 is explicitly designed for a trusted home/private network,
**not** for exposure to the open internet:

- **No authentication on the web UI.** Anyone who can reach the container's
  port can view and edit sources, settings, and job data. Tracked in
  [ROADMAP.md](ROADMAP.md) under Security & access — don't expose this
  beyond a trusted network without adding a gate in front of it (e.g. a
  reverse proxy with its own auth) first.
- **`SMTP_PASSWORD` is a container env var only**, deliberately never
  persisted to disk or editable via the UI, to avoid storing a plaintext
  credential at rest.
- Response headers (`app/web/security_headers.py`) provide defense-in-depth
  against clickjacking/MIME-sniffing/XSS-adjacent issues, but are not a
  substitute for the access control above.

Reports about the absence of authentication itself won't be treated as new
findings — that limitation is already tracked. Reports about anything else
(e.g. a way to escape the documented trust boundary, an injection vector,
a way to read `SMTP_PASSWORD`) are very welcome.
