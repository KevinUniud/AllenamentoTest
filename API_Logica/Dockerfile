FROM python:3.15-slim-bookworm@sha256:4e03260adeeebafccd084f3584e6b84823aba5651cfb53ef8a078ed441ddf9cd

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
