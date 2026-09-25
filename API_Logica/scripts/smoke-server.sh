#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
env_file=${1:-"$project_dir/.env.server"}
release_override=${2:-}
case "$env_file" in
    /*) ;;
    *) env_file=$(pwd)/$env_file ;;
esac

[ -r "$env_file" ] || {
    printf 'Smoke test API: file non leggibile: %s\n' "$env_file" >&2
    exit 1
}

unset DEPLOY_STATE_DIR
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a
if [ -n "$release_override" ]; then
    RELEASE_TAG=$release_override
    export RELEASE_TAG
fi

run_compose() {
    if [ "${API_ENABLE_LOOPBACK:-0}" = "1" ]; then
        docker compose --env-file "$env_file" \
            -f "$project_dir/compose.server.yml" \
            -f "$project_dir/compose.server.loopback.yml" "$@"
    else
        docker compose --env-file "$env_file" \
            -f "$project_dir/compose.server.yml" "$@"
    fi
}

run_compose exec -T testlogica-api python - <<'PY'
import json
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:5000"


def request(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={"Accept": "application/json", "X-Request-ID": "server-smoke"},
        method="GET" if body is None else "POST",
    )
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            assert response.status == 200, (path, response.status)
            assert response.headers.get("X-Request-ID") == "server-smoke"
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path}: HTTP {exc.code}: {detail}") from exc


def request_html(path: str) -> str:
    req = urllib.request.Request(
        BASE_URL + path,
        headers={"Accept": "text/html", "X-Request-ID": "server-smoke"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        assert response.status == 200, (path, response.status)
        assert response.headers.get("X-Request-ID") == "server-smoke"
        assert response.headers.get_content_type() == "text/html"
        return response.read().decode("utf-8")


assert request("/health")["status"] == "ok"
assert request("/ready")["status"] == "ready"
capabilities = request("/api/capabilities")
assert capabilities["version"] == 1
assert capabilities["features"]["transformation_trace"] is True
openapi = request("/openapi.json")
assert openapi["openapi"].startswith("3.1")
assert "/api/generator/build-exercise" in openapi["paths"]
docs = request_html("/docs")
assert "swagger-ui" in docs.lower()
exercise = request(
    "/api/generator/build-exercise",
    {"expr": "imp(p,q)", "wrong_answers_count": 3, "seed": 42},
)["result"]
transformation = exercise["modified_formula"]["transformation"]
assert transformation["source_formula_prolog"] == "imp(p,q)"
assert transformation["final_formula_prolog"] == exercise["correct_answer_prolog"]
assert len(transformation["steps"]) >= 2
print("Smoke test API superato: health, readiness, capabilities, OpenAPI, Swagger UI e generatore.")
PY
