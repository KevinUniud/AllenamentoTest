FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /build

COPY pyproject.toml README.md ./
COPY feedback_service ./feedback_service

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install . \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -m compileall -q \
        /opt/venv/lib/python3.11/site-packages/feedback_service


FROM builder AS test

COPY Dockerfile ./Dockerfile
COPY scripts ./scripts
COPY tests ./tests

RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/python -m pip install ".[dev]" \
    && /opt/venv/bin/python -m pip check

# The data preparation helper deliberately refuses administrator execution.
# Run static checks and tests with the same unprivileged numeric identity used
# by the runtime image; all tool caches live in writable temporary paths.
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    MYPY_CACHE_DIR=/tmp/mypy-cache \
    RUFF_CACHE_DIR=/tmp/ruff-cache \
    XDG_CACHE_HOME=/tmp/cache

USER 1000:1000

RUN /opt/venv/bin/python -m ruff check feedback_service tests \
    && /opt/venv/bin/python -m mypy feedback_service \
    && MPLCONFIGDIR=/tmp/matplotlib /opt/venv/bin/python -m pytest -p no:cacheprovider


FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS runtime

ENV HOME=/tmp \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/cache \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

RUN mkdir -p /app/data/receipts /app/data/charts \
    && chown -R 1000:1000 /app/data

# Compose may override these numeric IDs with FEEDBACK_UID/FEEDBACK_GID.
USER 1000:1000

EXPOSE 5555

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5555/ready', timeout=3).read()"]

# 0.0.0.0 is only the container namespace. Compose publishes it exclusively
# through the host loopback address declared in docker-compose.yml.
CMD ["uvicorn", "feedback_service.app:app", "--host", "0.0.0.0", "--port", "5555", "--no-access-log"]
