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
        --skip-backup)
            skip_backup=true
            shift
            ;;
        *)
            printf '%s\n' "Uso: $0 [--env-file FILE] [--skip-backup]" >&2
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
        server_fail "DEPLOY_STATE_DIR deve stare fuori dalle directory release"
        ;;
esac
[ -f "$state_dir/active.env" ] || server_fail "stato della release attiva assente"
[ -f "$state_dir/rollback.env" ] || server_fail "nessuna release precedente registrata"
[ -f "$state_dir/active.images" ] || server_fail "ID immagini della release attiva assenti"
[ -f "$state_dir/rollback.images" ] || server_fail "ID immagini della release precedente assenti"

target_env=$state_dir/rollback.env
[ ! -L "$state_dir/active.env" ] && [ ! -L "$target_env" ] || \
    server_fail "i file di stato release non possono essere link simbolici"

for invariant_key in COMPOSE_PROJECT_NAME WEB_IMAGE_REPOSITORY FEEDBACK_IMAGE_REPOSITORY \
    WEB_BIND_ADDRESS WEB_PORT BACKEND_NETWORK_NAME API_UPSTREAM FEEDBACK_UID FEEDBACK_GID \
    FEEDBACK_DATA_DIR DEPLOY_STATE_DIR; do
    active_value=$(server_env_value_from_file "$state_dir/active.env" "$invariant_key")
    requested_value=$(server_env_value "$invariant_key")
    [ "$active_value" = "$requested_value" ] || \
        server_fail "$invariant_key differisce dalla release attiva; correggere .env.server prima del rollback"
done

lock_dir=$state_dir/deploy.lock
mkdir "$lock_dir" 2>/dev/null || server_fail "un altro deploy o rollback e gia in corso: $lock_dir"
cleanup_lock() {
    rmdir "$lock_dir" 2>/dev/null || :
}
trap cleanup_lock 0 HUP INT TERM

target_release=$(server_env_value_from_file "$target_env" RELEASE_TAG)
target_web_revision=$(server_env_value_from_file "$target_env" WEB_RELEASE_REVISION)
target_feedback_revision=$(server_env_value_from_file "$target_env" FEEDBACK_RELEASE_REVISION)
runtime_env=$state_dir/rollback-runtime.env.tmp.$$
awk -v release="$target_release" -v web_revision="$target_web_revision" \
    -v feedback_revision="$target_feedback_revision" '
    /^RELEASE_TAG=/ { print "RELEASE_TAG=" release; release_seen = 1; next }
    /^WEB_RELEASE_REVISION=/ {
        print "WEB_RELEASE_REVISION=" web_revision
        web_seen = 1
        next
    }
    /^FEEDBACK_RELEASE_REVISION=/ {
        print "FEEDBACK_RELEASE_REVISION=" feedback_revision
        feedback_seen = 1
        next
    }
    { print }
    END {
        if (!release_seen || !web_seen || !feedback_seen) exit 2
    }
' "$state_dir/active.env" > "$runtime_env" || server_fail "impossibile creare la configurazione di rollback"
chmod 600 "$runtime_env"
cleanup_runtime() {
    rm -f "$runtime_env"
    cleanup_lock
}
trap cleanup_runtime 0 HUP INT TERM

ALLOW_DIRTY_DEPLOY=1 "$script_dir/server-preflight.sh" --env-file "$runtime_env" \
    --prepare-data --create-network --require-api

if [ "$skip_backup" != true ]; then
    feedback_id=$(server_docker_compose --env-file "$state_dir/active.env" \
        -f "$SERVER_COMPOSE_FILE" ps -q feedback 2>/dev/null || :)
    if [ -n "$feedback_id" ] \
        && [ "$(docker inspect --format '{{.State.Running}}' "$feedback_id")" = true ]; then
        "$SERVER_FEEDBACK_ROOT/scripts/server-backup.sh" --env-file "$state_dir/active.env"
    else
        server_fail "feedback attivo non disponibile per il backup; verificare un backup recente e ripetere con --skip-backup"
    fi
fi

active_web_repository=$(server_env_value_from_file "$state_dir/active.env" WEB_IMAGE_REPOSITORY)
active_feedback_repository=$(server_env_value_from_file "$state_dir/active.env" FEEDBACK_IMAGE_REPOSITORY)
target_web_image=$active_web_repository:$target_release
target_feedback_image=$active_feedback_repository:$target_release
docker image inspect "$target_web_image" >/dev/null 2>&1 || server_fail "immagine rollback assente: $target_web_image"
docker image inspect "$target_feedback_image" >/dev/null 2>&1 || server_fail "immagine rollback assente: $target_feedback_image"
expected_web_image_id=$(awk -F= '$1 == "WEB_IMAGE_ID" { print $2; exit }' "$state_dir/rollback.images")
expected_feedback_image_id=$(awk -F= '$1 == "FEEDBACK_IMAGE_ID" { print $2; exit }' "$state_dir/rollback.images")
[ "$(docker image inspect --format '{{.Id}}' "$target_web_image")" = "$expected_web_image_id" ] || \
    server_fail "ID immagine Web non coerente con la release registrata"
[ "$(docker image inspect --format '{{.Id}}' "$target_feedback_image")" = "$expected_feedback_image_id" ] || \
    server_fail "ID immagine feedback non coerente con la release registrata"
[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$target_web_image")" = "$target_web_revision" ] || \
    server_fail "revisione immagine Web non coerente con rollback.env"
[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$target_feedback_image")" = "$target_feedback_revision" ] || \
    server_fail "revisione immagine feedback non coerente con rollback.env"

wait_timeout=$(server_env_value_from_file "$runtime_env" DEPLOY_WAIT_TIMEOUT)
wait_timeout=${wait_timeout:-240}
server_docker_compose --env-file "$runtime_env" -f "$SERVER_COMPOSE_FILE" up \
    --detach --no-build --force-recreate --remove-orphans --wait --wait-timeout "$wait_timeout"
"$script_dir/server-smoke.sh" --env-file "$runtime_env"

cp "$state_dir/active.env" "$state_dir/active-before-rollback.env.tmp"
chmod 600 "$state_dir/active-before-rollback.env.tmp"
cp "$state_dir/active.images" "$state_dir/active-before-rollback.images.tmp"
chmod 600 "$state_dir/active-before-rollback.images.tmp"
cp "$runtime_env" "$state_dir/active.env.tmp"
chmod 600 "$state_dir/active.env.tmp"
cp "$state_dir/rollback.images" "$state_dir/active.images.tmp"
chmod 600 "$state_dir/active.images.tmp"
mv "$state_dir/active.env.tmp" "$state_dir/active.env"
mv "$state_dir/active-before-rollback.env.tmp" "$state_dir/rollback.env"
mv "$state_dir/active.images.tmp" "$state_dir/active.images"
mv "$state_dir/active-before-rollback.images.tmp" "$state_dir/rollback.images"

printf '%s\n' \
    "Rollback applicativo concluso: $target_release" \
    "Il database feedback non e stato ripristinato o modificato dal rollback."
