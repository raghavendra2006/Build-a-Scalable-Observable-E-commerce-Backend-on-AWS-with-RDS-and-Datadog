# ── Stage 1: Build stage ─────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Hardened Unprivileged Runtime ───────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 1001 -m -s /bin/bash appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appuser . .

ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER 1001

EXPOSE 8080

# Production-grade concurrency: gthread workers to handle I/O-bound database calls
CMD ["ddtrace-run", "gunicorn", \
     "--workers", "3", \
     "--threads", "4", \
     "--worker-class", "gthread", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app.wsgi:app"]
