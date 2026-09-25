FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime SWI-Prolog senza dipendenze grafiche: il bridge usa soltanto la CLI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends swi-prolog-nox \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system app \
    && adduser --system --ingroup app app

COPY --chown=app:app server ./server
COPY --chown=app:app testlogica ./testlogica
COPY --chown=app:app prolog ./prolog

RUN swipl -q -s prolog/tests/run_tests.pl
RUN python -m compileall -q server testlogica

USER app

EXPOSE 5000

CMD ["uvicorn", "server.server:app", "--host", "0.0.0.0", "--port", "5000"]
