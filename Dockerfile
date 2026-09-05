FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

# Pinning the base image by digest (below) buys supply-chain reproducibility
# but freezes whatever OS package versions shipped in that snapshot -- an
# `apt-get upgrade` is needed on top of it to actually pick up Debian
# security patches released since. Trivy's scan in docker.yml is what
# would catch a future regression here.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY app app
# Uninstalling pip after use drops its vendored copies of msgpack/setuptools
# from the image -- pip itself isn't needed once deps are installed, and its
# bundled versions of those two lag behind upstream security fixes (Trivy
# flags them via pip's SBOM, which older pip releases didn't ship).
RUN pip install --no-cache-dir . \
    && python -m pip uninstall -y pip

# Keep Chromium's download inside /app (not the default $HOME/.cache) so a
# single chown below covers it too, once the process drops to a non-root user.
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers
RUN playwright install --with-deps chromium

# Fixed UID/GID (not auto-assigned): docker-entrypoint.sh chowns the
# bind-mounted ./config and ./data to this uid/gid on every start (so
# mismatched host ownership never breaks a deploy), then drops the actual
# server process to it via setpriv. Runs as non-root per ROADMAP's "Docker
# image hardening" item -- see README's Docker section.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /app/config /app/data \
    && chown -R app:app /app

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:8080/ || exit 1
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "8080"]
