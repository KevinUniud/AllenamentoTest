#!/bin/sh

set -eu

usage() {
    printf '%s\n' \
        "Uso: $0 [--check | --write-env]" \
        "" \
        "  senza opzioni  prepara e verifica ./data, poi suggerisce UID/GID" \
        "  --check        verifica directory e UID/GID senza modificarli" \
        "  --write-env    prepara le directory e aggiorna UID/GID in .env"
}

mode=prepare
case ${1-} in
    "") ;;
    --check) mode=check ;;
    --write-env) mode=write_env ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
if [ "$#" -gt 1 ]; then
    usage >&2
    exit 2
fi

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
project_dir=$(CDPATH= cd "$script_dir/.." && pwd)
env_file=$project_dir/.env

read_env_value() {
    key=$1
    if [ ! -f "$env_file" ] || [ -L "$env_file" ]; then
        return
    fi
    awk -v key="$key" '
        index($0, key "=") == 1 { value = substr($0, length(key) + 2) }
        END { if (value != "") print value }
    ' "$env_file"
}

configured_data_dir=${FEEDBACK_DATA_DIR-}
if [ -z "$configured_data_dir" ]; then
    configured_data_dir=$(read_env_value FEEDBACK_DATA_DIR)
fi
configured_data_dir=${configured_data_dir:-./data}
case $configured_data_dir in
    *'
'*|*''*)
        printf '%s\n' "Errore: FEEDBACK_DATA_DIR contiene caratteri non validi." >&2
        exit 1
        ;;
esac
if ! command -v realpath >/dev/null 2>&1; then
    printf '%s\n' "Errore: realpath e richiesto per validare FEEDBACK_DATA_DIR." >&2
    exit 1
fi
case $configured_data_dir in
    /*) data_candidate=$configured_data_dir ;;
    *) data_candidate=$project_dir/$configured_data_dir ;;
esac
data_dir=$(realpath -m -s -- "$data_candidate")
physical_data_dir=$(realpath -m -- "$data_candidate")
if [ "$data_dir" != "$physical_data_dir" ]; then
    printf '%s\n' \
        "Errore: FEEDBACK_DATA_DIR non puo attraversare collegamenti simbolici: $configured_data_dir" >&2
    exit 1
fi
if [ "$data_dir" = / ] || [ "$data_dir" = "$project_dir" ]; then
    printf '%s\n' "Errore: FEEDBACK_DATA_DIR indica un percorso troppo ampio." >&2
    exit 1
fi
data_marker=$data_dir/.testlogica-feedback-data
host_uid=$(id -u)
host_gid=$(id -g)

case $host_uid:$host_gid in
    *[!0-9:]*)
        printf '%s\n' "Errore: id -u/id -g non hanno restituito valori numerici." >&2
        exit 1
        ;;
esac
if [ "$host_uid" -eq 0 ] || [ "$host_gid" -eq 0 ]; then
    printf '%s\n' \
        "Errore: esegui questo script come utente host normale, senza sudo." >&2
    exit 1
fi

if [ -e "$data_dir" ] || [ -L "$data_dir" ]; then
    if [ ! -d "$data_dir" ] || [ -L "$data_dir" ]; then
        printf '%s\n' "Errore: $data_dir non e una directory dati valida." >&2
        exit 1
    fi
    if [ -e "$data_marker" ] || [ -L "$data_marker" ]; then
        if [ ! -d "$data_marker" ] || [ -L "$data_marker" ]; then
            printf '%s\n' "Errore: marker dati feedback non valido: $data_marker" >&2
            exit 1
        fi
    elif find "$data_dir" -mindepth 1 -maxdepth 1 \
        ! -name .gitkeep \
        ! -name receipts \
        ! -name charts \
        ! -name backups \
        -print | grep -q .; then
        printf '%s\n' \
            "Errore: FEEDBACK_DATA_DIR contiene elementi estranei e non verra modificata: $data_dir" >&2
        exit 1
    fi
fi

if [ "$mode" != check ]; then
    umask 077
    mkdir -p "$data_dir"
    if [ ! -d "$data_marker" ]; then
        mkdir "$data_marker"
    fi
    mkdir -p "$data_dir/receipts" "$data_dir/charts"
    chmod 700 "$data_dir" "$data_marker" "$data_dir/receipts" "$data_dir/charts"
fi

for directory in "$data_dir" "$data_dir/receipts" "$data_dir/charts"; do
    if [ ! -d "$directory" ] || [ -L "$directory" ]; then
        printf '%s\n' "Errore: directory dati non valida: $directory" >&2
        exit 1
    fi
    if [ ! -w "$directory" ] || [ ! -x "$directory" ]; then
        printf '%s\n' "Errore: directory non scrivibile dall'utente host: $directory" >&2
        exit 1
    fi
done

if find "$data_dir" -xdev -type l -print | grep -q .; then
    printf '%s\n' \
        "Errore: $data_dir contiene collegamenti simbolici; rimuoverli prima dell'avvio." >&2
    exit 1
fi
foreign_entry=$(find "$data_dir" -xdev \( ! -uid "$host_uid" -o ! -gid "$host_gid" \) -print -quit)
if [ -n "$foreign_entry" ]; then
    printf '%s\n' \
        "Errore: elemento non posseduto dall'utente host: $foreign_entry" \
        "I dati devono restare gestibili senza permessi amministrativi." >&2
    exit 1
fi
if [ "$mode" != check ]; then
    find "$data_dir" -xdev -type d -exec chmod 0700 {} +
    find "$data_dir" -xdev -type f -exec chmod 0600 {} +
fi
public_entry=$(find "$data_dir" -xdev -perm /077 -print -quit)
if [ -n "$public_entry" ]; then
    printf '%s\n' "Errore: elemento dati accessibile da gruppo/altri: $public_entry" >&2
    exit 1
fi
readonly_file=$(find "$data_dir" -xdev -type f ! -perm -u+w -print -quit)
if [ -n "$readonly_file" ]; then
    printf '%s\n' "Errore: file dati non scrivibile dall'utente host: $readonly_file" >&2
    exit 1
fi
unusable_directory=$(find "$data_dir" -xdev -type d \
    \( ! -perm -u+w -o ! -perm -u+x \) -print -quit)
if [ -n "$unusable_directory" ]; then
    printf '%s\n' "Errore: directory dati non gestibile dall'utente host: $unusable_directory" >&2
    exit 1
fi

selinux_is_active() {
    if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled 2>/dev/null; then
        return 0
    fi
    if command -v getenforce >/dev/null 2>&1; then
        enforcement=$(getenforce 2>/dev/null || :)
        case $enforcement in
            Enforcing|Permissive) return 0 ;;
        esac
    fi
    context=$(stat -c '%C' -- "$data_dir" 2>/dev/null || :)
    case $context in
        *:*:*:*) return 0 ;;
    esac
    return 1
}

selinux_contexts_are_valid() {
    context_list=$(mktemp "${TMPDIR:-/tmp}/testlogica-feedback-context.XXXXXX")
    if ! find "$data_dir" -xdev -exec stat -c '%C' -- {} + > "$context_list"; then
        rm -f "$context_list"
        return 1
    fi
    if grep -Ev ':container_file_t(:|$)' "$context_list" >/dev/null; then
        rm -f "$context_list"
        return 1
    fi
    rm -f "$context_list"
    return 0
}

if selinux_is_active; then
    if ! selinux_contexts_are_valid; then
        if [ "$mode" = check ]; then
            printf '%s\n' \
                "Errore: il contesto SELinux di $data_dir non e container_file_t." \
                "Esegui '$0' come utente normale per applicarlo senza sudo." >&2
            exit 1
        fi
        if ! command -v chcon >/dev/null 2>&1; then
            printf '%s\n' \
                "Errore: SELinux e attivo ma chcon non e disponibile." >&2
            exit 1
        fi
        if ! chcon -R -t container_file_t "$data_dir"; then
            printf '%s\n' \
                "Errore: impossibile applicare container_file_t a $data_dir senza privilegi." >&2
            exit 1
        fi
        if ! selinux_contexts_are_valid; then
            printf '%s\n' \
                "Errore: il relabel SELinux di $data_dir non e stato applicato completamente." >&2
            exit 1
        fi
    fi
    printf '%s\n' "Contesto SELinux pronto: container_file_t."
fi

probe=$data_dir/.feedback-write-test.$$
cleanup_probe() {
    rm -f "$probe"
}
trap cleanup_probe 0 HUP INT TERM
(umask 077 && : > "$probe")
rm -f "$probe"
trap - 0 HUP INT TERM

write_ids() {
    if [ -L "$env_file" ]; then
        printf '%s\n' "Errore: $env_file non può essere un collegamento simbolico." >&2
        exit 1
    fi
    temporary_env=$env_file.tmp.$$
    cleanup_env() {
        rm -f "$temporary_env"
    }
    trap cleanup_env 0 HUP INT TERM
    if [ -f "$env_file" ]; then
        awk -v uid="$host_uid" -v gid="$host_gid" -v data_dir="$configured_data_dir" '
            BEGIN { uid_written = 0; gid_written = 0; data_dir_written = 0 }
            /^FEEDBACK_UID=/ {
                if (!uid_written) print "FEEDBACK_UID=" uid
                uid_written = 1
                next
            }
            /^FEEDBACK_GID=/ {
                if (!gid_written) print "FEEDBACK_GID=" gid
                gid_written = 1
                next
            }
            /^FEEDBACK_DATA_DIR=/ {
                if (!data_dir_written) print "FEEDBACK_DATA_DIR=" data_dir
                data_dir_written = 1
                next
            }
            { print }
            END {
                if (!uid_written) print "FEEDBACK_UID=" uid
                if (!gid_written) print "FEEDBACK_GID=" gid
                if (!data_dir_written) print "FEEDBACK_DATA_DIR=" data_dir
            }
        ' "$env_file" > "$temporary_env"
    else
        printf 'FEEDBACK_UID=%s\nFEEDBACK_GID=%s\nFEEDBACK_DATA_DIR=%s\n' \
            "$host_uid" "$host_gid" "$configured_data_dir" > "$temporary_env"
    fi
    chmod 600 "$temporary_env"
    mv "$temporary_env" "$env_file"
    trap - 0 HUP INT TERM
}

if [ "$mode" = write_env ]; then
    write_ids
    configured_uid=$host_uid
    configured_gid=$host_gid
else
    configured_uid=${FEEDBACK_UID-}
    configured_gid=${FEEDBACK_GID-}
    if [ -z "$configured_uid" ]; then
        configured_uid=$(read_env_value FEEDBACK_UID)
    fi
    if [ -z "$configured_gid" ]; then
        configured_gid=$(read_env_value FEEDBACK_GID)
    fi
    configured_uid=${configured_uid:-1000}
    configured_gid=${configured_gid:-1000}
fi

case $configured_uid:$configured_gid in
    *[!0-9:]*|0:*|*:0)
        printf '%s\n' "Errore: FEEDBACK_UID e FEEDBACK_GID devono essere interi positivi." >&2
        exit 1
        ;;
esac

if [ "$configured_uid" != "$host_uid" ] || [ "$configured_gid" != "$host_gid" ]; then
    printf '%s\n' \
        "UID/GID configurati: $configured_uid:$configured_gid" \
        "UID/GID dell'utente host: $host_uid:$host_gid" \
        "Esegui '$0 --write-env' per allinearli senza sudo." >&2
    exit 1
fi

printf '%s\n' \
    "Directory dati pronta: $data_dir" \
    "Processo container: UID $host_uid, GID $host_gid"
if [ "$mode" = prepare ]; then
    printf '%s\n' \
        "Per salvare gli ID in .env: $0 --write-env" \
        "Oppure esporta FEEDBACK_UID=$host_uid FEEDBACK_GID=$host_gid."
elif [ "$mode" = write_env ]; then
    printf '%s\n' "UID/GID aggiornati in $env_file."
fi
