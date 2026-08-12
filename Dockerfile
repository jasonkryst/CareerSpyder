FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY app app
RUN pip install --no-cache-dir .
RUN playwright install --with-deps chromium

RUN mkdir -p /app/config /app/data

EXPOSE 8080
CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "8080"]
