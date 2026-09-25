#!/bin/sh

set -eu

prepare_data=false
create_network=false
require_api=false
while [ "$#" -gt 0 ]; do
    case $1 in
        --env-file)
            [ "$#" -ge 2 ] || { printf '%s\n' "Errore: manca il percorso dopo --env-file" >&2; exit 2; }
            SERVER_ENV_FILE=$2
            shift 2
            ;;
        --prepare-data)
            prepare_data=true
            shift
            ;;
        --create-network)
            create_network=true
            shift
            ;;
        --require-api)
            require_api=true
            shift
            ;;
        *)
            printf '%s\n' "Uso: $0 [--env-file FILE] [--prepare-data] [--create-network] [--require-api]" >&2
            exit 2
            ;;
    esac
done

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$script_dir/server-common.sh"

server_require_command docker
server_require_command realpath
server_require_command stat
server_require_command find

[ "$(id -u)" -ne 0 ] || server_fail "eseguire il deploy come utente normale, senza sudo"
[ -f "$SERVER_ENV_FILE" ] && [ -r "$SERVER_ENV_FILE" ] && [ ! -L "$SERVER_ENV_FILE" ] || \
    server_fail "creare un file regolare $SERVER_ENV_FILE da .env.server.example"
[ -f "$SERVER_COMPOSE_FILE" ] && [ ! -L "$SERVER_COMPOSE_FILE" ] || \
    server_fail "compose server non trovato: $SERVER_COMPOSE_FILE"
[ -n "$SERVER_FEEDBACK_ROOT" ] && [ -d "$SERVER_FEEDBACK_ROOT/feedback_service" ] || \
    server_fail "il repository fratello deve chiamarsi esattamente feedback"

[ "$(stat -c %u "$SERVER_ENV_FILE")" = "$(id -u)" ] || \
    server_fail "$SERVER_ENV_FILE deve appartenere all'utente di deployment"
env_mode=$(stat -c %a "$SERVER_ENV_FILE")
case $env_mode in
    400|440|600|640) ;;
    *) server_fail "$SERVER_ENV_FILE deve avere permessi 0600 o, al massimo, 0640 (attuali: $env_mode)" ;;
esac

docker info >/dev/null
server_compose config --quiet

release_tag=$(server_env_value RELEASE_TAG)
server_validate_release_tag "$release_tag"
for revision_key in WEB_RELEASE_REVISION FEEDBACK_RELEASE_REVISION; do
    release_revision=$(server_env_value "$revision_key")
    case $release_revision in
        ""|replace-*) server_fail "$revision_key deve identificare esattamente i sorgenti distribuiti" ;;
        *[!A-Za-z0-9_.-]*) server_fail "$revision_key contiene caratteri non validi" ;;
    esac
done
for repository_key in WEB_IMAGE_REPOSITORY FEEDBACK_IMAGE_REPOSITORY; do
    image_repository=$(server_env_value "$repository_key")
    case $image_repository in
        ""|-*|*[!A-Za-z0-9_./:-]*) server_fail "$repository_key non valido" ;;
    esac
done
pull_base_images=$(server_env_value DEPLOY_PULL_BASE_IMAGES)
pull_base_images=${pull_base_images:-1}
case $pull_base_images in
    0|1) ;;
    *) server_fail "DEPLOY_PULL_BASE_IMAGES deve valere 0 oppure 1" ;;
esac

configured_uid=$(server_env_value FEEDBACK_UID)
configured_gid=$(server_env_value FEEDBACK_GID)
server_is_positive_integer "$configured_uid" || server_fail "FEEDBACK_UID deve essere un intero positivo"
server_is_positive_integer "$configured_gid" || server_fail "FEEDBACK_GID deve essere un intero positivo"
[ "$configured_uid" = "$(id -u)" ] || server_fail "FEEDBACK_UID non coincide con id -u"
[ "$configured_gid" = "$(id -g)" ] || server_fail "FEEDBACK_GID non coincide con id -g"

bind_address=$(server_env_value WEB_BIND_ADDRESS)
[ "$bind_address" = 127.0.0.1 ] || \
    server_fail "WEB_BIND_ADDRESS deve restare 127.0.0.1; l'esposizione pubblica appartiene all'edge TLS"
web_port=$(server_env_value WEB_PORT)
server_is_positive_integer "$web_port" || server_fail "WEB_PORT deve essere un intero positivo"
[ "$web_port" -le 65535 ] || server_fail "WEB_PORT non valida"

api_upstream=$(server_env_value API_UPSTREAM)
[ "$api_upstream" = http://api-logica:5000 ] || \
    server_fail "API_UPSTREAM server deve essere esattamente http://api-logica:5000"
api_proxy_timeout=$(server_env_value API_PROXY_TIMEOUT_SECONDS)
server_is_positive_integer "$api_proxy_timeout" || \
    server_fail "API_PROXY_TIMEOUT_SECONDS deve essere un intero positivo"
[ "$api_proxy_timeout" -ge 120 ] && [ "$api_proxy_timeout" -le 300 ] || \
    server_fail "API_PROXY_TIMEOUT_SECONDS deve essere compreso tra 120 e 300"

worker_job_timeout=$(server_env_value FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS)
worker_heartbeat=$(server_env_value FEEDBACK_WORKER_HEARTBEAT_SECONDS)
stop_grace=$(server_env_value FEEDBACK_STOP_GRACE_SECONDS)
server_is_positive_integer "$worker_job_timeout" || \
    server_fail "FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS deve essere un intero positivo"
server_is_positive_integer "$worker_heartbeat" || \
    server_fail "FEEDBACK_WORKER_HEARTBEAT_SECONDS deve essere un intero positivo"
server_is_positive_integer "$stop_grace" || \
    server_fail "FEEDBACK_STOP_GRACE_SECONDS deve essere un intero positivo"
minimum_stop_grace=$((worker_job_timeout + worker_heartbeat + 1))
[ "$stop_grace" -ge "$minimum_stop_grace" ] || \
    server_fail "FEEDBACK_STOP_GRACE_SECONDS deve essere almeno JOB_TIMEOUT + HEARTBEAT + 1 ($minimum_stop_grace)"

state_dir=$(server_state_dir)
physical_state_dir=$(realpath -m -- "$state_dir")
[ "$state_dir" = "$physical_state_dir" ] || \
    server_fail "DEPLOY_STATE_DIR non puo attraversare collegamenti simbolici"
case $state_dir in
    /|"$SERVER_WEB_ROOT"|"$SERVER_WEB_ROOT"/*|"$SERVER_FEEDBACK_ROOT"|"$SERVER_FEEDBACK_ROOT"/*)
        server_fail "DEPLOY_STATE_DIR deve stare fuori dalle directory release Webpage_Logica e feedback"
        ;;
esac
[ "$(basename -- "$state_dir")" = web-feedback ] || \
    server_fail "DEPLOY_STATE_DIR deve terminare con la directory dedicata web-feedback"
state_marker=$state_dir/.testlogica-web-feedback-state
checked_path=$state_dir
while [ "$checked_path" != / ]; do
    [ ! -L "$checked_path" ] || \
        server_fail "DEPLOY_STATE_DIR attraversa un link simbolico: $checked_path"
    checked_path=$(dirname -- "$checked_path")
done
if [ -e "$state_dir" ]; then
    [ -d "$state_dir" ] || server_fail "DEPLOY_STATE_DIR esiste ma non e una directory"
    [ "$(stat -c %u "$state_dir")" = "$(id -u)" ] || \
        server_fail "DEPLOY_STATE_DIR deve appartenere all'utente di deployment"
    insecure_state=$(find "$state_dir" -maxdepth 1 \( -type f -o -type d -o -type l \) \
        -perm /022 -print -quit)
    [ -z "$insecure_state" ] || \
        server_fail "stato deployment modificabile dal gruppo o da altri utenti: $insecure_state"
    if [ -e "$state_marker" ]; then
        [ -f "$state_marker" ] && [ ! -L "$state_marker" ] || \
            server_fail "marker DEPLOY_STATE_DIR non valido: $state_marker"
    elif find "$state_dir" -mindepth 1 -print -quit | grep -q .; then
        server_fail "DEPLOY_STATE_DIR esiste, non e vuota e non contiene il marker TestLogica"
    fi
else
    state_parent=$(dirname -- "$state_dir")
    [ -d "$state_parent" ] && [ -w "$state_parent" ] || \
        server_fail "creare prima la directory padre scrivibile di DEPLOY_STATE_DIR: $state_parent"
    [ "$(stat -c %u "$state_parent")" = "$(id -u)" ] || \
        server_fail "la directory padre di DEPLOY_STATE_DIR deve appartenere all'utente di deployment"
    insecure_parent=$(find "$state_parent" -maxdepth 0 -perm /022 -print -quit)
    [ -z "$insecure_parent" ] || \
        server_fail "la directory padre di DEPLOY_STATE_DIR non deve essere scrivibile da gruppo/altri"
fi

data_setting=$(server_env_value FEEDBACK_DATA_DIR)
[ -n "$data_setting" ] || server_fail "FEEDBACK_DATA_DIR non configurata"
case $data_setting in
    /*) data_dir=$(realpath -m -s -- "$data_setting") ;;
    *) server_fail "FEEDBACK_DATA_DIR deve essere un percorso assoluto e persistente" ;;
esac
physical_data_dir=$(realpath -m -- "$data_setting")
[ "$data_dir" = "$physical_data_dir" ] || \
    server_fail "FEEDBACK_DATA_DIR non puo attraversare collegamenti simbolici"
case $data_dir in
    /|"$SERVER_WEB_ROOT"|"$SERVER_WEB_ROOT"/*|"$SERVER_FEEDBACK_ROOT"|"$SERVER_FEEDBACK_ROOT"/*)
        server_fail "FEEDBACK_DATA_DIR deve stare fuori dalle directory release"
        ;;
esac
case $state_dir in
    "$data_dir"|"$data_dir"/*) server_fail "DEPLOY_STATE_DIR non puo stare dentro FEEDBACK_DATA_DIR" ;;
esac
case $data_dir in
    "$state_dir"|"$state_dir"/*) server_fail "FEEDBACK_DATA_DIR non puo stare dentro DEPLOY_STATE_DIR" ;;
esac

if [ "$prepare_data" = true ]; then
    FEEDBACK_DATA_DIR=$data_dir \
    FEEDBACK_UID=$configured_uid \
    FEEDBACK_GID=$configured_gid \
        "$SERVER_FEEDBACK_ROOT/scripts/prepare-data.sh"
else
    FEEDBACK_DATA_DIR=$data_dir \
    FEEDBACK_UID=$configured_uid \
    FEEDBACK_GID=$configured_gid \
        "$SERVER_FEEDBACK_ROOT/scripts/prepare-data.sh" --check
fi

backend_network=$(server_env_value BACKEND_NETWORK_NAME)
[ -n "$backend_network" ] || server_fail "BACKEND_NETWORK_NAME non configurata"
if ! docker network inspect "$backend_network" >/dev/null 2>&1; then
    if [ "$create_network" != true ]; then
        server_fail "rete $backend_network assente; avvia prima il preflight API o usa --create-network"
    fi
    docker network create --driver bridge --internal "$backend_network" >/dev/null || :
fi
docker network inspect "$backend_network" >/dev/null 2>&1 || \
    server_fail "impossibile creare o leggere la rete $backend_network"
[ "$(docker network inspect --format '{{.Internal}}' "$backend_network")" = true ] || \
    server_fail "la rete $backend_network esiste ma non e internal"
[ "$(docker network inspect --format '{{.Driver}}' "$backend_network")" = bridge ] || \
    server_fail "la rete $backend_network deve usare il driver bridge"

if [ "$require_api" = true ]; then
    api_names=$(docker network inspect --format '{{range .Containers}}{{println .Name}}{{end}}' "$backend_network")
    printf '%s\n' "$api_names" | grep -Eiq 'api' || \
        server_fail "nessun container API risulta collegato a $backend_network; distribuire prima API_Logica"
fi

own_web_id=$(server_compose ps -q webpage-logica 2>/dev/null || :)
published=$(docker ps --filter "publish=$web_port" --format '{{.ID}} {{.Names}}')
if [ -n "$published" ]; then
    if [ -z "$own_web_id" ]; then
        server_fail "la porta $web_port e gia occupata: $published"
    fi
    foreign=$(printf '%s\n' "$published" | awk -v own="$own_web_id" '$1 != substr(own, 1, length($1)) { print }')
    [ -z "$foreign" ] || server_fail "la porta $web_port e occupata da un altro stack: $foreign"
fi

if [ "${ALLOW_DIRTY_DEPLOY:-0}" != 1 ]; then
    for repository in "$SERVER_WEB_ROOT" "$SERVER_FEEDBACK_ROOT"; do
        if [ -d "$repository/.git" ] && [ -n "$(git -C "$repository" status --porcelain)" ]; then
            server_fail "worktree non pulito: $repository (creare prima una release locale verificabile)"
        fi
    done
fi

for repository in "$SERVER_WEB_ROOT" "$SERVER_FEEDBACK_ROOT"; do
    insecure_source=$(find "$repository" \
        \( -path "$repository/.git" -o -path "$repository/data" \) -prune -o \
        \( -type f -o -type d \) -perm /022 -print -quit)
    [ -z "$insecure_source" ] || \
        server_fail "sorgente modificabile dal gruppo o da altri utenti: $insecure_source"
done

printf '%s\n' \
    "Preflight server superato." \
    "Release: $release_tag" \
    "Rete API privata: $backend_network" \
    "Web locale: http://127.0.0.1:$web_port" \
    "Dati feedback: $data_dir"
