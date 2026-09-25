#!/bin/sh

set -eu

while [ "$#" -gt 0 ]; do
    case $1 in
        --env-file)
            [ "$#" -ge 2 ] || { printf '%s\n' "Errore: manca il percorso dopo --env-file" >&2; exit 2; }
            SERVER_ENV_FILE=$2
            shift 2
            ;;
        *)
            printf '%s\n' "Uso: $0 [--env-file FILE]" >&2
            exit 2
            ;;
    esac
done

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$script_dir/server-common.sh"

server_require_command curl
server_require_command docker
server_compose config --quiet

for service in feedback-worker feedback webpage-logica; do
    container_id=$(server_compose ps -q "$service")
    [ -n "$container_id" ] || server_fail "container non trovato: $service"
    state=$(docker inspect --format '{{.State.Status}}' "$container_id")
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")
    [ "$state" = running ] || server_fail "$service non e in esecuzione: $state"
    [ "$health" = healthy ] || server_fail "$service non e healthy: $health"
done

feedback_id=$(server_compose ps -q feedback)
worker_id=$(server_compose ps -q feedback-worker)
[ -z "$(docker port "$feedback_id")" ] || server_fail "feedback pubblica una porta host"
[ -z "$(docker port "$worker_id")" ] || server_fail "feedback-worker pubblica una porta host"

web_id=$(server_compose ps -q webpage-logica)
web_port=$(server_env_value WEB_PORT)
published=$(docker port "$web_id" 80/tcp)
[ "$published" = "127.0.0.1:$web_port" ] || \
    server_fail "binding Web inatteso: $published"

connect_timeout=$(server_env_value SMOKE_CONNECT_TIMEOUT)
connect_timeout=${connect_timeout:-5}
max_time=$(server_env_value SMOKE_MAX_TIME)
max_time=${max_time:-30}
base_url=http://127.0.0.1:$web_port

http_status() {
    curl --noproxy '*' --silent --show-error \
        --connect-timeout "$connect_timeout" --max-time "$max_time" \
        --output "$1" --write-out '%{http_code}' "$2"
}

temporary_body=$(mktemp "${TMPDIR:-/tmp}/testlogica-smoke-body.XXXXXX")
temporary_headers=$(mktemp "${TMPDIR:-/tmp}/testlogica-smoke-headers.XXXXXX")
cleanup() {
    rm -f "$temporary_body" "$temporary_headers"
}
trap cleanup 0 HUP INT TERM

for path in / /web-health /health /api/capabilities; do
    status=$(http_status "$temporary_body" "$base_url$path")
    [ "$status" = 200 ] || server_fail "$path ha restituito HTTP $status"
done

status=$(http_status "$temporary_body" "$base_url/api/feedback/charts/manifest")
case $status in
    200|404) ;;
    *) server_fail "manifest feedback ha restituito HTTP $status" ;;
esac

# GET verifica il routing senza inserire alcun report nel database.
status=$(http_status "$temporary_body" "$base_url/api/revisione")
[ "$status" = 405 ] || server_fail "/api/revisione GET ha restituito HTTP $status"

curl --noproxy '*' --silent --show-error --output /dev/null \
    --dump-header "$temporary_headers" --connect-timeout "$connect_timeout" \
    --max-time "$max_time" "$base_url/"
for header in X-Content-Type-Options X-Frame-Options Referrer-Policy Permissions-Policy \
    Cross-Origin-Opener-Policy Cross-Origin-Resource-Policy Content-Security-Policy; do
    grep -Eiq "^$header:" "$temporary_headers" || server_fail "header di sicurezza assente: $header"
done

server_compose exec -T webpage-logica sh -ec \
    'wget -qO- "${API_UPSTREAM}/ready" >/dev/null && wget -qO- "${API_UPSTREAM}/openapi.json" >/dev/null && wget -qO- "${API_UPSTREAM}/docs" >/dev/null'
server_compose exec -T feedback python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5555/ready', timeout=3).read(); urllib.request.urlopen('http://127.0.0.1:5555/metrics', timeout=3).read()"

public_base_url=$(server_env_value PUBLIC_BASE_URL)
if [ -n "$public_base_url" ]; then
    case $public_base_url in
        https://*) ;;
        *) server_fail "PUBLIC_BASE_URL deve usare HTTPS" ;;
    esac
    curl --silent --show-error --fail --output /dev/null --dump-header "$temporary_headers" \
        --connect-timeout "$connect_timeout" --max-time "$max_time" "$public_base_url/"
    grep -Eiq '^Strict-Transport-Security:' "$temporary_headers" || \
        server_fail "HSTS assente sull'edge pubblico"
fi

printf '%s\n' "Smoke test server superato senza inviare payload feedback."

