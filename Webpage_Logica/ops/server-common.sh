#!/bin/sh

# Funzioni condivise dagli script di deploy. Questo file viene incluso dagli
# altri script e non deve essere eseguito direttamente.
SERVER_OPS_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
SERVER_WEB_ROOT=$(CDPATH= cd "$SERVER_OPS_DIR/.." && pwd)
SERVER_FEEDBACK_ROOT=$(CDPATH= cd "$SERVER_WEB_ROOT/../feedback" 2>/dev/null && pwd || :)
SERVER_COMPOSE_FILE=${SERVER_COMPOSE_FILE:-$SERVER_WEB_ROOT/compose.server.yml}
SERVER_ENV_FILE=${SERVER_ENV_FILE:-$SERVER_WEB_ROOT/.env.server}

server_fail() {
    printf '%s\n' "Errore: $*" >&2
    exit 1
}

server_require_command() {
    command -v "$1" >/dev/null 2>&1 || server_fail "comando richiesto non trovato: $1"
}

server_docker_compose() (
    # Le variabili esportate nella shell hanno precedenza su --env-file. Lo
    # stack server deve invece dipendere soltanto dal file esplicitamente
    # selezionato, lasciando intatte le sole variabili Docker del client.
    for environment_source in "$SERVER_WEB_ROOT/.env.server.example" "$SERVER_ENV_FILE"; do
        [ -f "$environment_source" ] || continue
        environment_keys=$(awk -F= '
            /^[A-Za-z_][A-Za-z0-9_]*=/ { print $1 }
        ' "$environment_source")
        for environment_key in $environment_keys; do
            unset "$environment_key"
        done
    done
    unset COMPOSE_FILE COMPOSE_ENV_FILES COMPOSE_PROFILES COMPOSE_PATH_SEPARATOR
    docker compose "$@"
)

server_compose() {
    server_docker_compose --env-file "$SERVER_ENV_FILE" -f "$SERVER_COMPOSE_FILE" "$@"
}

server_env_value() {
    key=$1
    if ! environment_output=$(server_compose config --environment); then
        server_fail "impossibile leggere la configurazione Compose da $SERVER_ENV_FILE"
    fi
    printf '%s\n' "$environment_output" | awk -v key="$key" '
        index($0, key "=") == 1 {
            print substr($0, length(key) + 2)
            found = 1
            exit
        }
        END { if (!found) exit 0 }
    '
}

server_env_value_from_file() {
    env_path=$1
    key=$2
    if ! environment_output=$(server_docker_compose --env-file "$env_path" \
        -f "$SERVER_COMPOSE_FILE" config --environment); then
        server_fail "impossibile leggere la configurazione Compose da $env_path"
    fi
    printf '%s\n' "$environment_output" | awk -v key="$key" '
        index($0, key "=") == 1 {
            print substr($0, length(key) + 2)
            found = 1
            exit
        }
        END { if (!found) exit 0 }
    '
}

server_resolve_from_web() {
    candidate=$1
    case $candidate in
        /*) realpath -m -- "$candidate" ;;
        *) realpath -m -- "$SERVER_WEB_ROOT/$candidate" ;;
    esac
}

server_is_positive_integer() {
    case $1 in
        ""|*[!0-9]*) return 1 ;;
        *) [ "$1" -gt 0 ] ;;
    esac
}

server_validate_release_tag() {
    release_tag=$1
    case $release_tag in
        ""|latest|replace-*|*[!A-Za-z0-9_.-]*|.*|-*)
            server_fail "RELEASE_TAG non valido o ancora di esempio: $release_tag"
            ;;
    esac
    if [ "${#release_tag}" -gt 128 ]; then
        server_fail "RELEASE_TAG supera 128 caratteri"
    fi
}

server_state_dir() {
    configured=$(server_env_value DEPLOY_STATE_DIR)
    [ -n "$configured" ] || server_fail "DEPLOY_STATE_DIR non configurata"
    case $configured in
        /*) realpath -m -s -- "$configured" ;;
        *) server_fail "DEPLOY_STATE_DIR deve essere un percorso assoluto e persistente" ;;
    esac
}
