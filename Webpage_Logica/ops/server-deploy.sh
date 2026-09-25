#!/bin/sh

set -eu

skip_backup=false
while [ "$#" -gt 0 ]; do
    case $1 in
        --env-file)
            [ "$#" -ge 2 ] || { printf '%s\n' "Errore: manca il percorso dopo --env-file" >&2; exit 2; }
            SERVER_ENV_FILE=$2
            shift 2
            ;;
        --allow-dirty)
            ALLOW_DIRTY_DEPLOY=1
            export ALLOW_DIRTY_DEPLOY
            shift
            ;;
        --skip-backup)
            skip_backup=true
            shift
            ;;
        *)
            printf '%s\n' "Uso: $0 [--env-file FILE] [--allow-dirty] [--skip-backup]" >&2
            exit 2
            ;;
    esac
done

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$script_dir/server-common.sh"

"$script_dir/server-preflight.sh" --env-file "$SERVER_ENV_FILE" \
    --prepare-data --create-network --require-api

state_dir=$(server_state_dir)
case $state_dir in
    "$SERVER_WEB_ROOT"|"$SERVER_WEB_ROOT"/*|"$SERVER_FEEDBACK_ROOT"|"$SERVER_FEEDBACK_ROOT"/*)
        server_fail "DEPLOY_STATE_DIR deve stare fuori dalle directory release Webpage_Logica e feedback"
        ;;
esac
umask 077
mkdir -p "$state_dir"
chmod 700 "$state_dir"
state_marker=$state_dir/.testlogica-web-feedback-state
if [ ! -e "$state_marker" ]; then
    : > "$state_marker"
    chmod 600 "$state_marker"
fi
lock_dir=$state_dir/deploy.lock
mkdir "$lock_dir" 2>/dev/null || server_fail "un altro deploy o rollback e gia in corso: $lock_dir"
cleanup_lock() {
    rmdir "$lock_dir" 2>/dev/null || :
}
trap cleanup_lock 0 HUP INT TERM

release_tag=$(server_env_value RELEASE_TAG)
web_image=$(server_env_value WEB_IMAGE_REPOSITORY):$release_tag
feedback_image=$(server_env_value FEEDBACK_IMAGE_REPOSITORY):$release_tag
if [ -f "$state_dir/active.env" ]; then
    [ ! -L "$state_dir/active.env" ] || server_fail "active.env non puo essere un link simbolico"
    for invariant_key in COMPOSE_PROJECT_NAME WEB_IMAGE_REPOSITORY FEEDBACK_IMAGE_REPOSITORY \
        WEB_BIND_ADDRESS WEB_PORT BACKEND_NETWORK_NAME API_UPSTREAM FEEDBACK_UID FEEDBACK_GID \
        FEEDBACK_DATA_DIR DEPLOY_STATE_DIR; do
        active_value=$(server_env_value_from_file "$state_dir/active.env" "$invariant_key")
        requested_value=$(server_env_value "$invariant_key")
        [ "$active_value" = "$requested_value" ] || \
            server_fail "$invariant_key non puo cambiare durante un deploy ordinario; usare una procedura di migrazione esplicita"
    done
    active_release=$(server_env_value_from_file "$state_dir/active.env" RELEASE_TAG)
    [ "$active_release" != "$release_tag" ] || \
        server_fail "la release $release_tag e gia attiva; i tag di release non sono riutilizzabili"
fi
for image in "$web_image" "$feedback_image"; do
    if docker image inspect -- "$image" >/dev/null 2>&1; then
        server_fail "il tag immutabile esiste gia localmente: $image; scegliere un nuovo RELEASE_TAG"
    fi
done

if [ "$skip_backup" != true ]; then
    runtime_env=$SERVER_ENV_FILE
    if [ -f "$state_dir/active.env" ]; then
        runtime_env=$state_dir/active.env
    fi
    feedback_id=$(server_docker_compose --env-file "$runtime_env" -f "$SERVER_COMPOSE_FILE" \
        ps -q feedback 2>/dev/null || :)
    if [ -n "$feedback_id" ] && [ "$(docker inspect --format '{{.State.Running}}' "$feedback_id")" = true ]; then
        "$SERVER_FEEDBACK_ROOT/scripts/server-backup.sh" --env-file "$runtime_env"
    else
        data_dir=$(realpath -m -s -- \
            "$(server_env_value_from_file "$runtime_env" FEEDBACK_DATA_DIR)")
        if [ -e "$data_dir/receipts/feedback.sqlite3" ]; then
            server_fail "database esistente ma feedback non e in esecuzione: creare/verificare un backup prima del deploy, oppure usare consapevolmente --skip-backup"
        fi
    fi
fi

printf '%s\n' "Costruzione immagini release $release_tag..."
pull_base_images=$(server_env_value DEPLOY_PULL_BASE_IMAGES)
pull_base_images=${pull_base_images:-1}
if [ "$pull_base_images" = 1 ]; then
    server_compose build --pull
else
    server_compose build
fi
expected_web_revision=$(server_env_value WEB_RELEASE_REVISION)
expected_feedback_revision=$(server_env_value FEEDBACK_RELEASE_REVISION)
[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$web_image")" = "$expected_web_revision" ] || \
    server_fail "la label di revisione dell'immagine Web non corrisponde alla configurazione"
[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$feedback_image")" = "$expected_feedback_revision" ] || \
    server_fail "la label di revisione dell'immagine feedback non corrisponde alla configurazione"
web_image_id=$(docker image inspect --format '{{.Id}}' "$web_image")
feedback_image_id=$(docker image inspect --format '{{.Id}}' "$feedback_image")

recover_failed_release() {
    if [ ! -f "$state_dir/active.env" ] || [ ! -f "$state_dir/active.images" ]; then
        printf '%s\n' "Primo deploy non validato: arresto dello stack (fail closed)." >&2
        server_compose down --remove-orphans || return 1
        return 0
    fi

    previous_release=$(server_env_value_from_file "$state_dir/active.env" RELEASE_TAG)
    previous_web_revision=$(server_env_value_from_file "$state_dir/active.env" WEB_RELEASE_REVISION)
    previous_feedback_revision=$(server_env_value_from_file "$state_dir/active.env" FEEDBACK_RELEASE_REVISION)
    previous_web_repository=$(server_env_value_from_file "$state_dir/active.env" WEB_IMAGE_REPOSITORY)
    previous_feedback_repository=$(server_env_value_from_file "$state_dir/active.env" FEEDBACK_IMAGE_REPOSITORY)
    previous_web_image=$previous_web_repository:$previous_release
    previous_feedback_image=$previous_feedback_repository:$previous_release
    previous_web_id=$(awk -F= '$1 == "WEB_IMAGE_ID" { print $2; exit }' "$state_dir/active.images")
    previous_feedback_id=$(awk -F= '$1 == "FEEDBACK_IMAGE_ID" { print $2; exit }' "$state_dir/active.images")

    [ -n "$previous_web_id" ] && [ -n "$previous_feedback_id" ] || return 1
    docker image inspect "$previous_web_image" "$previous_feedback_image" >/dev/null 2>&1 || return 1
    [ "$(docker image inspect --format '{{.Id}}' "$previous_web_image")" = "$previous_web_id" ] || return 1
    [ "$(docker image inspect --format '{{.Id}}' "$previous_feedback_image")" = "$previous_feedback_id" ] || return 1
    [ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$previous_web_image")" = "$previous_web_revision" ] || return 1
    [ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$previous_feedback_image")" = "$previous_feedback_revision" ] || return 1

    previous_wait_timeout=$(server_env_value_from_file "$state_dir/active.env" DEPLOY_WAIT_TIMEOUT)
    previous_wait_timeout=${previous_wait_timeout:-240}
    printf '%s\n' "Ripristino automatico della release Web/feedback $previous_release..." >&2
    server_docker_compose --env-file "$state_dir/active.env" -f "$SERVER_COMPOSE_FILE" up \
        --detach --no-build --force-recreate --remove-orphans --wait \
        --wait-timeout "$previous_wait_timeout" || return 1
    "$script_dir/server-smoke.sh" --env-file "$state_dir/active.env" || return 1
    return 0
}

fail_after_recovery() {
    failure_message=$1
    if recover_failed_release; then
        server_fail "$failure_message; il servizio non validato e stato rimosso o la release precedente e stata ripristinata"
    fi
    printf '%s\n' "Recupero automatico fallito: arresto dello stack per evitare di servire una release non validata." >&2
    server_compose down --remove-orphans || :
    server_fail "$failure_message; anche il recupero automatico e fallito"
}

wait_timeout=$(server_env_value DEPLOY_WAIT_TIMEOUT)
wait_timeout=${wait_timeout:-240}
printf '%s\n' "Avvio release $release_tag..."
if ! server_compose up --detach --no-build --remove-orphans --wait --wait-timeout "$wait_timeout"; then
    fail_after_recovery "avvio della release $release_tag fallito"
fi

if ! "$script_dir/server-smoke.sh" --env-file "$SERVER_ENV_FILE"; then
    fail_after_recovery "smoke test della release $release_tag fallito"
fi

# Il puntatore di rollback cambia soltanto dopo che la release candidata ha
# superato lo smoke test. In questo modo un deploy rifiutato non cancella il
# riferimento alla penultima release sana.
if [ -f "$state_dir/active.env" ]; then
    cp "$state_dir/active.env" "$state_dir/rollback.env.tmp"
    chmod 600 "$state_dir/rollback.env.tmp"
    mv "$state_dir/rollback.env.tmp" "$state_dir/rollback.env"
fi
if [ -f "$state_dir/active.images" ]; then
    cp "$state_dir/active.images" "$state_dir/rollback.images.tmp"
    chmod 600 "$state_dir/rollback.images.tmp"
    mv "$state_dir/rollback.images.tmp" "$state_dir/rollback.images"
fi

cp "$SERVER_ENV_FILE" "$state_dir/active.env.tmp"
chmod 600 "$state_dir/active.env.tmp"
mv "$state_dir/active.env.tmp" "$state_dir/active.env"
printf 'WEB_IMAGE_ID=%s\nFEEDBACK_IMAGE_ID=%s\n' \
    "$web_image_id" "$feedback_image_id" > "$state_dir/active.images.tmp"
chmod 600 "$state_dir/active.images.tmp"
mv "$state_dir/active.images.tmp" "$state_dir/active.images"

printf '%s\n' \
    "Deploy locale concluso: $release_tag" \
    "Stato persistente: $state_dir" \
    "Nessun push o commit e stato eseguito."
