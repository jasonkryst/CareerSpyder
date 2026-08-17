#!/bin/sh
# Runs as root (the image's default user) so the bind-mounted ./config and
# ./data directories can be made writable by the app user regardless of
# their ownership on the host -- no manual `chown` required at deploy time.
# The actual long-running process is then handed off to uid 1000 via
# setpriv and never runs as root. See README's Docker section.
set -e

chown -R 1000:1000 /app/config /app/data

exec setpriv --reuid=1000 --regid=1000 --init-groups "$@"
