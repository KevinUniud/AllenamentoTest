#!/bin/sh

set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
feedback_root=$(CDPATH= cd "$script_dir/.." && pwd)
web_root=$(CDPATH= cd "$feedback_root/../Webpage_Logica" 2>/dev/null && pwd || :)
env_file=${SERVER_ENV_FILE:-$web_root/.env.server}

while [ "$#" -gt 0 ]; do
    case $1 in
        --env-file)
            [ "$#" -ge 2 ] || { printf '%s\n' "Errore: manca il percorso dopo --env-file" >&2; exit 2; }
            env_file=$2
            shift 2
            ;;
        *)
            printf '%s\n' "Uso: $0 [--env-file FILE]" >&2
            exit 2
            ;;
    esac
done

fail() {
    printf '%s\n' "Errore: $*" >&2
    exit 1
}

[ "$(id -u)" -ne 0 ] || fail "eseguire il backup come utente normale, senza sudo"
[ -n "$web_root" ] && [ -f "$web_root/compose.server.yml" ] || \
    fail "repository fratello Webpage_Logica o compose.server.yml non trovato"
[ -f "$env_file" ] && [ -r "$env_file" ] && [ ! -L "$env_file" ] || \
    fail "file ambiente non valido: $env_file"
[ "$(stat -c %u "$env_file")" = "$(id -u)" ] || \
    fail "il file ambiente deve appartenere all'utente di deployment"
case $(stat -c %a "$env_file") in
    400|440|600|640) ;;
    *) fail "il file ambiente deve avere permessi 0600 o, al massimo, 0640" ;;
esac
command -v docker >/dev/null 2>&1 || fail "docker non trovato"
command -v realpath >/dev/null 2>&1 || fail "realpath non trovato"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum non trovato"
command -v df >/dev/null 2>&1 || fail "df non trovato"
command -v du >/dev/null 2>&1 || fail "du non trovato"

compose() (
    for environment_source in "$web_root/.env.server.example" "$env_file"; do
        [ -f "$environment_source" ] || continue
        environment_keys=$(awk -F= '
            /^[A-Za-z_][A-Za-z0-9_]*=/ { print $1 }
        ' "$environment_source")
        for environment_key in $environment_keys; do
            unset "$environment_key"
        done
    done
    unset COMPOSE_FILE COMPOSE_ENV_FILES COMPOSE_PROFILES COMPOSE_PATH_SEPARATOR
    docker compose --env-file "$env_file" -f "$web_root/compose.server.yml" "$@"
)

env_value() {
    key=$1
    if ! environment_output=$(compose config --environment); then
        fail "impossibile leggere la configurazione Compose da $env_file"
    fi
    printf '%s\n' "$environment_output" | awk -v key="$key" \
        'index($0, key "=") == 1 { print substr($0, length(key) + 2); exit }'
}

compose config --quiet
container_id=$(compose ps -q feedback)
[ -n "$container_id" ] || fail "servizio feedback non avviato"
[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" = true ] || \
    fail "servizio feedback non in esecuzione"

data_setting=$(env_value FEEDBACK_DATA_DIR)
case $data_setting in
    /*) data_dir=$(realpath -m -s -- "$data_setting") ;;
    *) fail "FEEDBACK_DATA_DIR deve essere un percorso assoluto e persistente" ;;
esac
[ "$data_dir" = "$(realpath -m -- "$data_setting")" ] || \
    fail "FEEDBACK_DATA_DIR non puo attraversare collegamenti simbolici"
case $data_dir in
    /|"$feedback_root"|"$feedback_root"/*|"$web_root"|"$web_root"/*)
        fail "FEEDBACK_DATA_DIR deve stare fuori dalle directory release"
        ;;
esac
[ -d "$data_dir" ] && [ ! -L "$data_dir" ] || fail "directory dati feedback non valida: $data_dir"
configured_uid=$(env_value FEEDBACK_UID)
configured_gid=$(env_value FEEDBACK_GID)
FEEDBACK_DATA_DIR=$data_dir FEEDBACK_UID=$configured_uid FEEDBACK_GID=$configured_gid \
    "$feedback_root/scripts/prepare-data.sh" --check

minimum_free_bytes=$(env_value FEEDBACK_MIN_FREE_BYTES)
case $minimum_free_bytes in
    ""|*[!0-9]*) fail "FEEDBACK_MIN_FREE_BYTES non valido" ;;
esac
source_kib=$(du -sk "$data_dir/receipts" | awk '{print $1}')
available_kib=$(df -Pk "$data_dir" | awk 'NR > 1 { available = $4 } END { print available }')
minimum_free_kib=$(( (minimum_free_bytes + 1023) / 1024 ))
required_kib=$((source_kib + minimum_free_kib))
[ "$available_kib" -ge "$required_kib" ] || \
    fail "spazio insufficiente per un backup consistente e la riserva minima: disponibili ${available_kib} KiB, richiesti ${required_kib} KiB"

release_tag=$(env_value RELEASE_TAG)
case $release_tag in
    ""|latest|replace-*|.*|-*|*[!A-Za-z0-9_.-]*) fail "RELEASE_TAG non valido" ;;
esac
timestamp=$(date -u '+%Y%m%dT%H%M%SZ')
filename=feedback-$timestamp-$release_tag.sqlite3
container_path=/app/data/backups/$filename

compose exec -T feedback python -m feedback_service.admin backup "$container_path"

host_path=$data_dir/backups/$filename
[ -f "$host_path" ] && [ ! -L "$host_path" ] || fail "backup host non trovato: $host_path"
[ "$(stat -c %u "$host_path")" = "$(id -u)" ] || fail "backup non posseduto dall'utente host"
[ "$(stat -c %g "$host_path")" = "$(id -g)" ] || fail "gruppo del backup inatteso"
[ "$(stat -c %a "$host_path")" = 600 ] || fail "il backup deve avere permessi 0600"

umask 077
checksum_tmp=$host_path.sha256.tmp.$$
cleanup() {
    rm -f "$checksum_tmp"
}
trap cleanup 0 HUP INT TERM
(
    cd "$(dirname "$host_path")"
    sha256sum "$filename"
) > "$checksum_tmp"
chmod 600 "$checksum_tmp"
mv "$checksum_tmp" "$host_path.sha256"
trap - 0 HUP INT TERM

remaining_kib=$(df -Pk "$data_dir" | awk 'NR > 1 { available = $4 } END { print available }')
[ "$remaining_kib" -ge "$minimum_free_kib" ] || \
    fail "il backup e stato creato ma lo spazio libero e sceso sotto FEEDBACK_MIN_FREE_BYTES"

printf '%s\n' \
    "Backup feedback verificato: $host_path" \
    "Checksum: $host_path.sha256" \
    "Copiare entrambi su uno storage cifrato esterno al server."
