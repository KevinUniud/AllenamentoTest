#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
env_file=${1:-"$project_dir/.env.server"}
requested_release=${2:-}
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

if [ -z "$requested_release" ] && [ -s "$previous_file" ]; then
    IFS= read -r requested_release < "$previous_file"
fi
case "$requested_release" in
    ""|.*|-*|latest|*[!A-Za-z0-9_.-]*)
        printf 'Rollback API: specificare un tag valido o eseguire prima almeno due deploy gestiti.\n' >&2
        exit 1
        ;;
esac

docker image inspect -- "$API_IMAGE_REPOSITORY:$requested_release" >/dev/null 2>&1 || {
    printf 'Rollback API: immagine locale assente: %s:%s\n' \
        "$API_IMAGE_REPOSITORY" "$requested_release" >&2
    exit 1
}

current_release=
current_revision=
current_image_id=
if [ -s "$current_file" ]; then
    IFS= read -r current_release < "$current_file"
fi
if [ -s "$current_revision_file" ]; then
    IFS= read -r current_revision < "$current_revision_file"
fi
if [ -s "$current_image_id_file" ]; then
    IFS= read -r current_image_id < "$current_image_id_file"
fi

requested_revision=
requested_image_id=
if [ -s "$previous_file" ] && [ -s "$previous_revision_file" ]; then
    IFS= read -r recorded_previous < "$previous_file"
    if [ "$recorded_previous" = "$requested_release" ]; then
        IFS= read -r requested_revision < "$previous_revision_file"
        if [ -s "$previous_image_id_file" ]; then
            IFS= read -r requested_image_id < "$previous_image_id_file"
        fi
    fi
fi
image_id=$(docker image inspect --format '{{.Id}}' "$API_IMAGE_REPOSITORY:$requested_release")
[ -z "$requested_image_id" ] || [ "$image_id" = "$requested_image_id" ] || {
    printf 'Rollback API: ID immagine non coerente con lo stato registrato.\n' >&2
    exit 1
}
image_revision=$(docker image inspect --format \
    '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    "$API_IMAGE_REPOSITORY:$requested_release")
case $image_revision in
    ""|unknown|"<no value>")
        printf 'Rollback API: label revisione assente per %s:%s.\n' \
            "$API_IMAGE_REPOSITORY" "$requested_release" >&2
        exit 1
        ;;
esac
[ -z "$requested_revision" ] || [ "$image_revision" = "$requested_revision" ] || {
    printf 'Rollback API: revisione immagine non coerente con lo stato registrato.\n' >&2
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

printf 'Rollback API verso la release %s...\n' "$requested_release"
run_compose_for_release "$requested_release" up --detach --remove-orphans --no-build --wait \
    --wait-timeout "${DEPLOY_WAIT_TIMEOUT_SECONDS:-180}"
"$script_dir/smoke-server.sh" "$env_file" "$requested_release"

umask 077
mkdir -p "$state_dir"
if [ -n "$current_release" ] && [ "$current_release" != "$requested_release" ]; then
    printf '%s\n' "$current_release" > "$previous_file.tmp"
    mv "$previous_file.tmp" "$previous_file"
    if [ -n "$current_revision" ]; then
        printf '%s\n' "$current_revision" > "$previous_revision_file.tmp"
        mv "$previous_revision_file.tmp" "$previous_revision_file"
    fi
    if [ -n "$current_image_id" ]; then
        printf '%s\n' "$current_image_id" > "$previous_image_id_file.tmp"
        mv "$previous_image_id_file.tmp" "$previous_image_id_file"
    fi
fi
printf '%s\n' "$requested_release" > "$current_file.tmp"
mv "$current_file.tmp" "$current_file"
printf '%s\n' "$image_revision" > "$current_revision_file.tmp"
mv "$current_revision_file.tmp" "$current_revision_file"
printf '%s\n' "$image_id" > "$current_image_id_file.tmp"
mv "$current_image_id_file.tmp" "$current_image_id_file"

printf 'Rollback API completato: release %s.\n' "$requested_release"
