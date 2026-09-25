#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
env_file=${1:-"$project_dir/.env.server"}
case "$env_file" in
    /*) ;;
    *) env_file=$(pwd)/$env_file ;;
esac

"$script_dir/preflight-server.sh" "$env_file"

unset DEPLOY_STATE_DIR
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

state_dir=${DEPLOY_STATE_DIR:-"$project_dir/.deploy"}
current_file=$state_dir/current-release
previous_file=$state_dir/previous-release
current_revision_file=$state_dir/current-revision
previous_revision_file=$state_dir/previous-revision
current_image_id_file=$state_dir/current-image-id
previous_image_id_file=$state_dir/previous-image-id
umask 077
mkdir -p "$state_dir"
chmod 700 "$state_dir"
state_marker=$state_dir/.testlogica-api-state
if [ ! -e "$state_marker" ]; then
    : > "$state_marker"
    chmod 600 "$state_marker"
fi

previous_release=
previous_revision=
previous_image_id=
if [ -s "$current_file" ]; then
    IFS= read -r previous_release < "$current_file"
fi
if [ -s "$current_revision_file" ]; then
    IFS= read -r previous_revision < "$current_revision_file"
fi
if [ -s "$current_image_id_file" ]; then
    IFS= read -r previous_image_id < "$current_image_id_file"
fi
case "$previous_release" in
    "") ;;
    .*|-*|latest|*[!A-Za-z0-9_.-]*)
        printf 'Stato deployment API non valido in %s.\n' "$current_file" >&2
        exit 1
        ;;
esac

if [ "$previous_release" = "$RELEASE_TAG" ]; then
    printf 'Deploy API annullato: la release %s e gia registrata. Usare un tag nuovo.\n' "$RELEASE_TAG" >&2
    exit 1
fi

target_image=$API_IMAGE_REPOSITORY:$RELEASE_TAG
if docker image inspect -- "$target_image" >/dev/null 2>&1; then
    printf 'Deploy API annullato: il tag immutabile esiste gia localmente: %s. Usare un nuovo RELEASE_TAG.\n' \
        "$target_image" >&2
    exit 1
fi

if ! docker network inspect -- "$BACKEND_NETWORK_NAME" >/dev/null 2>&1; then
    docker network create --driver bridge --internal \
        --label it.testlogica.role=backend-network -- "$BACKEND_NETWORK_NAME" >/dev/null
fi
network_internal=$(docker network inspect --format '{{.Internal}}' -- "$BACKEND_NETWORK_NAME")
[ "$network_internal" = "true" ] || {
    printf 'Deploy API annullato: la rete %s non e internal.\n' "$BACKEND_NETWORK_NAME" >&2
    exit 1
}

run_compose_for_release() {
    target_release=$1
    shift
    if [ "${API_ENABLE_LOOPBACK:-0}" = "1" ]; then
        env RELEASE_TAG="$target_release" docker compose --env-file "$env_file" \
            -f "$project_dir/compose.server.yml" \
            -f "$project_dir/compose.server.loopback.yml" "$@"
    else
        env RELEASE_TAG="$target_release" docker compose --env-file "$env_file" \
            -f "$project_dir/compose.server.yml" "$@"
    fi
}

rollback_after_failure() {
    if [ -z "$previous_release" ]; then
        printf 'Nessuna release precedente registrata: rollback automatico non disponibile.\n' >&2
        return 1
    fi
    if ! docker image inspect -- "$API_IMAGE_REPOSITORY:$previous_release" >/dev/null 2>&1; then
        printf 'Immagine precedente non disponibile localmente: %s:%s\n' \
            "$API_IMAGE_REPOSITORY" "$previous_release" >&2
        return 1
    fi
    if [ -n "$previous_revision" ]; then
        stored_revision=$(docker image inspect --format \
            '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
            "$API_IMAGE_REPOSITORY:$previous_release")
        [ "$stored_revision" = "$previous_revision" ] || {
            printf 'Immagine precedente con revisione inattesa: %s\n' "$stored_revision" >&2
            return 1
        }
    fi
    if [ -n "$previous_image_id" ]; then
        stored_image_id=$(docker image inspect --format '{{.Id}}' \
            "$API_IMAGE_REPOSITORY:$previous_release")
        [ "$stored_image_id" = "$previous_image_id" ] || {
            printf 'Immagine precedente con ID inatteso: %s\n' "$stored_image_id" >&2
            return 1
        }
    fi
    printf 'Ripristino automatico della release API %s...\n' "$previous_release" >&2
    run_compose_for_release "$previous_release" up --detach --remove-orphans --no-build --wait \
        --wait-timeout "${DEPLOY_WAIT_TIMEOUT_SECONDS:-180}"
    "$script_dir/smoke-server.sh" "$env_file" "$previous_release"
}

recover_after_failure() {
    if rollback_after_failure; then
        return 0
    fi
    printf 'Arresto della release API non validata %s (fail closed)...\n' \
        "$RELEASE_TAG" >&2
    run_compose_for_release "$RELEASE_TAG" down --remove-orphans || true
    return 1
}

printf 'Build della release API %s...\n' "$RELEASE_TAG"
if [ "${DEPLOY_PULL_BASE_IMAGES:-1}" = "1" ]; then
    run_compose_for_release "$RELEASE_TAG" build --pull testlogica-api
else
    run_compose_for_release "$RELEASE_TAG" build testlogica-api
fi
built_revision=$(docker image inspect --format \
    '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$target_image")
[ "$built_revision" = "$RELEASE_REVISION" ] || {
    printf 'Deploy API annullato: label revisione inattesa nell immagine %s.\n' "$target_image" >&2
    exit 1
}
built_image_id=$(docker image inspect --format '{{.Id}}' "$target_image")

printf 'Avvio della release API %s...\n' "$RELEASE_TAG"
if ! run_compose_for_release "$RELEASE_TAG" up --detach --remove-orphans --no-build --wait \
    --wait-timeout "${DEPLOY_WAIT_TIMEOUT_SECONDS:-180}"; then
    recover_after_failure || true
    exit 1
fi

if ! "$script_dir/smoke-server.sh" "$env_file" "$RELEASE_TAG"; then
    recover_after_failure || true
    exit 1
fi

if [ -n "$previous_release" ]; then
    printf '%s\n' "$previous_release" > "$previous_file.tmp"
    mv "$previous_file.tmp" "$previous_file"
    if [ -n "$previous_revision" ]; then
        printf '%s\n' "$previous_revision" > "$previous_revision_file.tmp"
        mv "$previous_revision_file.tmp" "$previous_revision_file"
    fi
    if [ -n "$previous_image_id" ]; then
        printf '%s\n' "$previous_image_id" > "$previous_image_id_file.tmp"
        mv "$previous_image_id_file.tmp" "$previous_image_id_file"
    fi
fi
printf '%s\n' "$RELEASE_TAG" > "$current_file.tmp"
mv "$current_file.tmp" "$current_file"
printf '%s\n' "$RELEASE_REVISION" > "$current_revision_file.tmp"
mv "$current_revision_file.tmp" "$current_revision_file"
printf '%s\n' "$built_image_id" > "$current_image_id_file.tmp"
mv "$current_image_id_file.tmp" "$current_image_id_file"

printf 'Deploy API completato: release %s.\n' "$RELEASE_TAG"
