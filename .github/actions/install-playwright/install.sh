#!/usr/bin/env bash
# Install Playwright's Chromium for CI with apt as a *fallback*, not a first
# step (#286).
#
# `playwright install --with-deps chromium` runs apt on every job, so CI broke
# whenever the runner couldn't reach the Ubuntu package mirror -- even though
# GitHub's Ubuntu image already ships Chrome's shared libraries. Instead:
#
#   1. download the browser only (`playwright install chromium`, from
#      Playwright's CDN, retried once);
#   2. try to launch headless Chromium -- normally this passes and apt never
#      runs;
#   3. only if the launch fails: `playwright install-deps chromium` under a
#      timeout, retried, then re-check and fail with a clear ::error::.
#
# Tunables (env), mostly so tests/test_ci_workflows.py can run this quickly:
#   PW_DEPS_TIMEOUT      seconds per install-deps attempt   (default 600)
#   PW_LAUNCH_TIMEOUT    seconds per launch check            (default 120)
#   PW_ATTEMPTS          attempts for download and apt each  (default 2)
#   PW_RETRY_DELAY       seconds between attempts            (default 15)
set -euo pipefail

deps_timeout="${PW_DEPS_TIMEOUT:-600}"
launch_timeout="${PW_LAUNCH_TIMEOUT:-120}"
attempts="${PW_ATTEMPTS:-2}"
retry_delay="${PW_RETRY_DELAY:-15}"

launches() {
  timeout "$launch_timeout" python - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    p.chromium.launch().close()
PY
}

# Runs "$@" up to $attempts times; returns 0 on the first success.
retry() {
  local i
  for ((i = 1; i <= attempts; i++)); do
    if "$@"; then
      return 0
    fi
    echo "Attempt $i/$attempts failed: $*" >&2
    if ((i < attempts)); then
      sleep "$retry_delay"
    fi
  done
  return 1
}

if ! retry playwright install chromium; then
  echo "::error::Couldn't download Playwright's Chromium (playwright install chromium)."
  exit 1
fi

if launches; then
  echo "Chromium launched with the runner's preinstalled libraries; skipping apt (playwright install-deps)."
  exit 0
fi

echo "::warning::Chromium couldn't launch; installing its system libraries via apt (playwright install-deps chromium)."
retry timeout "$deps_timeout" playwright install-deps chromium || true

if ! launches; then
  echo "::error::Chromium can't launch and apt couldn't install its libraries (playwright install-deps chromium)."
  exit 1
fi
echo "Chromium launched after installing its system libraries via apt."
