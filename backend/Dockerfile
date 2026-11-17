# PMA backend: FastAPI API + RQ worker (same image, different command).
# Python + MPXJ via JPype needs a Java runtime in the image.
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JAVA_HOME=/usr/lib/jvm/default-java \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless fonts-dejavu-core curl \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf "$(dirname "$(dirname "$(readlink -f "$(which java)")")")" /usr/lib/jvm/default-java

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

RUN useradd --system --uid 10001 --home /app pma \
 && mkdir -p /app/data /tmp/matplotlib \
 && chown -R pma /app/data /tmp/matplotlib
USER pma

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

# API (default). The worker overrides this with: python -m app.worker
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${PMA_WEB_WORKERS:-4} --proxy-headers --forwarded-allow-ips='*'"]
