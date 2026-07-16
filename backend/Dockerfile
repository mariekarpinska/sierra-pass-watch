# Backend container image for AWS App Runner.
#
# Build from the REPO ROOT (build context = the whole repo), not from backend/,
# because the API imports the monorepo-local `pipeline` package and reads data
# files from shared/. The deploy workflow runs:
#
#   docker build -f backend/Dockerfile -t sierra-safe-api .
#
# slim = the small Debian-based Python image: everything we need, none of the
# build tools we don't (psycopg and confluent-kafka ship prebuilt Linux wheels,
# so no compiler is required).
FROM python:3.13-slim

# PYTHONUNBUFFERED  — print logs the instant they happen, so App Runner's log
#                     tail is live instead of showing nothing until a buffer fills.
# PYTHONDONTWRITEBYTECODE — don't litter the image with .pyc files.
# PIP_NO_CACHE_DIR  — don't keep pip's download cache in the image layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) The pipeline package first. The API imports pipeline.regime (one classifier
#    labels forecasts, live readings and crash history), and its pyproject lives
#    at the repo root. Copy only what pip needs to resolve and install it, so a
#    change to the API code doesn't bust this layer's Docker cache.
COPY pyproject.toml ./
COPY pipeline/ ./pipeline/
RUN pip install .

# 2) The API package. Its pyproject depends on sierra-corridor-pipeline, which
#    step 1 already installed, so pip won't reach out to PyPI looking for it.
COPY backend/ ./backend/
RUN pip install ./backend

# 3) Runtime data the API reads on each request: route drive-lines and the
#    weather-regime cases (shared/). No database, no network to load these.
COPY shared/ ./shared/

# config.py normally finds shared/ by walking up from its own file location.
# Once pip-installs the API into site-packages, that relative walk no longer
# lands on /app/shared, so point SHARED_DIR at it explicitly.
ENV SHARED_DIR=/app/shared

# App Runner sends request traffic to port 8080 by default. Bind 0.0.0.0 so the
# platform can reach the container; 127.0.0.1 would refuse all outside traffic.
ENV PORT=8080
EXPOSE 8080

# One uvicorn worker per container on purpose: App Runner scales by starting
# MORE CONTAINERS, not more in-process workers, so a single worker keeps each
# container's memory small and its behaviour predictable.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --no-server-header"]
