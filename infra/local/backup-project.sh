#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_ID=${1:?project id required}
CONFIG_ROOT=/etc/aeos/memgraph
DATA_ROOT="/var/lib/aeos/memgraph/projects/${PROJECT_ID}"
BACKUP_ROOT="/var/backups/aeos/memgraph/${PROJECT_ID}"
MGCONSOLE=/usr/bin/mgconsole
port=$(sed -n 's/^--bolt-port=//p' "$CONFIG_ROOT/${PROJECT_ID}.conf")
username=$(cut -d: -f1 "$CONFIG_ROOT/${PROJECT_ID}.pass")
password=$(cut -d: -f2- "$CONFIG_ROOT/${PROJECT_ID}.pass")
printf 'CREATE SNAPSHOT;\n' | "$MGCONSOLE" --host 127.0.0.1 --port "$port" --use-ssl=true \
  --username "$username" --password "$password" >/dev/null
snapshot=$(find "$DATA_ROOT/snapshots" -maxdepth 1 -type f -printf '%T@ %p\n' \
  | sort -nr | head -1 | cut -d' ' -f2-)
[[ -n $snapshot && -s $snapshot ]] || { echo "snapshot was not created" >&2; exit 1; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$BACKUP_ROOT/${stamp}-$(basename "$snapshot")"
install -m 0400 -o root -g root "$snapshot" "$target"
sha256sum "$target" | awk '{print $1}' > "$target.sha256"
chmod 0400 "$target.sha256"
find "$BACKUP_ROOT" -maxdepth 1 -type f -mtime +14 -delete
echo "Local AEOS graph recovery point created"
