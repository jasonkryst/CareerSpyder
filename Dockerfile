FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY app app
RUN pip install --no-cache-dir .

# Keep Chromium's download inside /app (not the default $HOME/.cache) so a
# single chown below covers it too, once the process drops to a non-root user.
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers
RUN playwright install --with-deps chromium

# Fixed UID/GID (not auto-assigned) so operators can `chown -R 1000:1000` the
# host's ./config and ./data bind mounts to match — see README's Docker
# section. Runs as non-root per ROADMAP's "Docker image hardening" item.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /app/config /app/data \
    && chown -R app:app /app
USER 1000:1000

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:8080/ || exit 1
CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "8080"]
