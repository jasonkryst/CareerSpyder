#!/bin/sh
# Runs as root so bind-mounted ./config can be made writable regardless of
# host ownership. The actual long-running process hands off to uid 1000 via
# setpriv and never runs as root. See README's Docker section.
set -e

chown -R 1000:1000 /app/config

# Apply any pending Alembic migrations before starting the app.
# Safe to run on every container start -- no-op when already at head.
setpriv --reuid=1000 --regid=1000 --init-groups alembic upgrade head

exec setpriv --reuid=1000 --regid=1000 --init-groups "$@"
