#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
env_file=${1:-"$project_dir/.env.server"}
case "$env_file" in
    /*) ;;
    *) env_file=$(pwd)/$env_file ;;
esac

fail() {
    printf 'Preflight API fallito: %s\n' "$*" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker non trovato"
docker compose version >/dev/null 2>&1 || fail "plugin Docker Compose non disponibile"
docker info >/dev/null 2>&1 || fail "daemon Docker non raggiungibile dall'utente corrente"
[ -r "$env_file" ] || fail "file di configurazione non leggibile: $env_file"
[ ! -L "$env_file" ] || fail "il file di configurazione non puo essere un link simbolico"
[ "$(stat -c '%u' "$env_file")" = "$(id -u)" ] \
    || fail "il file di configurazione deve appartenere all'utente di deployment"

env_mode=$(stat -c '%a' "$env_file")
case "$env_mode" in
    400|440|600|640) ;;
    *) fail "$env_file deve avere permessi 0600 o, al massimo, 0640 (attuali: $env_mode)" ;;
esac

unset DEPLOY_STATE_DIR
set -a
# Il file e amministrato localmente dal medesimo utente che esegue il deploy.
# shellcheck disable=SC1090
. "$env_file"
set +a

case "${RELEASE_TAG:-}" in
    ""|latest|replace-with-release-tag) fail "RELEASE_TAG deve essere un tag immutabile e non 'latest'" ;;
    .*|-*) fail "RELEASE_TAG deve iniziare con una lettera, un numero oppure underscore" ;;
    *[!A-Za-z0-9_.-]*) fail "RELEASE_TAG contiene caratteri non validi per un tag Docker" ;;
esac
case "${API_IMAGE_REPOSITORY:-}" in
    "") fail "API_IMAGE_REPOSITORY non impostato" ;;
    -*) fail "API_IMAGE_REPOSITORY non puo iniziare con un trattino" ;;
esac
case "${RELEASE_REVISION:-}" in
    ""|replace-with-git-revision) fail "RELEASE_REVISION deve identificare i sorgenti distribuiti" ;;
esac
case "${BACKEND_NETWORK_NAME:-}" in
    ""|*[!A-Za-z0-9_.-]*) fail "BACKEND_NETWORK_NAME non valido" ;;
esac
case "${API_ENABLE_LOOPBACK:-0}" in
    0|1) ;;
    *) fail "API_ENABLE_LOOPBACK deve valere 0 oppure 1" ;;
esac
if [ "${API_ENABLE_LOOPBACK:-0}" = "1" ] \
    && [ "${API_LOOPBACK_ADDRESS:-127.0.0.1}" != "127.0.0.1" ]; then
    fail "API_LOOPBACK_ADDRESS deve restare 127.0.0.1"
fi
case "${CORS_ORIGINS:-}" in
    "") fail "CORS_ORIGINS non impostato" ;;
    *localhost*|*127.0.0.1*|*example.invalid*) fail "CORS_ORIGINS deve contenere l'origine HTTPS effettiva" ;;
esac

old_ifs=$IFS
IFS=,
for origin in $CORS_ORIGINS; do
    case "$origin" in
        https://*) ;;
        *) fail "origine CORS non HTTPS nella configurazione server: $origin" ;;
    esac
done
IFS=$old_ifs

if [ -n "${DEPLOY_STATE_DIR:-}" ]; then
    case "$DEPLOY_STATE_DIR" in
        /*) state_dir=$DEPLOY_STATE_DIR ;;
        *) fail "DEPLOY_STATE_DIR deve essere un percorso assoluto" ;;
    esac
else
    state_dir=$project_dir/.deploy
fi
[ "$state_dir" != "/" ] && [ "$state_dir" != "$project_dir" ] \
    || fail "DEPLOY_STATE_DIR indica un percorso troppo ampio"
case $state_dir in
    "$project_dir/.deploy") ;;
    *) [ "$(basename -- "$state_dir")" = api ] || \
        fail "DEPLOY_STATE_DIR esterno deve terminare con una directory dedicata chiamata api" ;;
esac
state_marker=$state_dir/.testlogica-api-state

checked_path=$state_dir
while [ "$checked_path" != "/" ]; do
    [ ! -L "$checked_path" ] || fail "DEPLOY_STATE_DIR attraversa un link simbolico: $checked_path"
    checked_path=$(dirname -- "$checked_path")
done

if [ -e "$state_dir" ]; then
    [ -d "$state_dir" ] || fail "DEPLOY_STATE_DIR esiste ma non e una directory"
    [ "$(stat -c '%u' "$state_dir")" = "$(id -u)" ] \
        || fail "DEPLOY_STATE_DIR deve appartenere all'utente di deployment"
    insecure_state=$(find "$state_dir" -maxdepth 1 \( -type f -o -type d -o -type l \) \
        -perm /022 -print -quit)
    [ -z "$insecure_state" ] \
        || fail "stato deployment modificabile dal gruppo o da altri utenti: $insecure_state"
    if [ -e "$state_marker" ]; then
        [ -f "$state_marker" ] && [ ! -L "$state_marker" ] \
            || fail "marker DEPLOY_STATE_DIR non valido: $state_marker"
    elif find "$state_dir" -mindepth 1 -print -quit | grep -q .; then
        fail "DEPLOY_STATE_DIR esiste, non e vuota e non contiene il marker TestLogica"
    fi
else
    state_parent=$(dirname -- "$state_dir")
    [ -d "$state_parent" ] && [ -w "$state_parent" ] \
        || fail "creare prima la directory padre scrivibile di DEPLOY_STATE_DIR: $state_parent"
    insecure_parent=$(find "$state_parent" -maxdepth 0 -perm /022 -print -quit)
    [ -z "$insecure_parent" ] \
        || fail "la directory padre di DEPLOY_STATE_DIR non deve essere scrivibile da gruppo/altri"
fi

case "${DEPLOY_PULL_BASE_IMAGES:-1}" in
    0|1) ;;
    *) fail "DEPLOY_PULL_BASE_IMAGES deve valere 0 oppure 1" ;;
esac

for numeric_setting in API_WORKERS API_CONCURRENCY_LIMIT API_BACKLOG; do
    case $numeric_setting in
        API_WORKERS) numeric_value=${API_WORKERS:-} ;;
        API_CONCURRENCY_LIMIT) numeric_value=${API_CONCURRENCY_LIMIT:-} ;;
        API_BACKLOG) numeric_value=${API_BACKLOG:-} ;;
    esac
    case "$numeric_value" in
        ""|*[!0-9]*) fail "$numeric_setting deve essere un intero positivo" ;;
    esac
    [ "$numeric_value" -gt 0 ] || fail "$numeric_setting deve essere maggiore di zero"
done
[ "$API_WORKERS" -le 8 ] || fail "API_WORKERS non puo superare 8"
[ "$API_CONCURRENCY_LIMIT" -le 256 ] || fail "API_CONCURRENCY_LIMIT non puo superare 256"
[ "$API_BACKLOG" -le 1024 ] || fail "API_BACKLOG non puo superare 1024"

bad_path=$(find "$project_dir" \
    \( -path "$project_dir/.git" -o -path "$project_dir/.deploy" \) -prune -o \
    \( -type f -o -type d \) -perm /022 -print -quit)
[ -z "$bad_path" ] || fail "percorso modificabile dal gruppo o da altri utenti: $bad_path"

if [ "${API_ENABLE_LOOPBACK:-0}" = "1" ]; then
    docker compose --env-file "$env_file" \
        -f "$project_dir/compose.server.yml" \
        -f "$project_dir/compose.server.loopback.yml" config --quiet
else
    docker compose --env-file "$env_file" \
        -f "$project_dir/compose.server.yml" config --quiet
fi

docker compose up --help | grep -q -- '--wait' \
    || fail "Docker Compose deve supportare 'up --wait'"

if docker network inspect -- "$BACKEND_NETWORK_NAME" >/dev/null 2>&1; then
    network_internal=$(docker network inspect --format '{{.Internal}}' -- "$BACKEND_NETWORK_NAME")
    [ "$network_internal" = "true" ] \
        || fail "la rete $BACKEND_NETWORK_NAME esiste ma non e internal"
else
    printf 'Preflight API: la rete internal %s verra creata dal deploy.\n' "$BACKEND_NETWORK_NAME"
fi

printf 'Preflight API completato per release %s.\n' "$RELEASE_TAG"
