#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_ID=${1:?project id required}
CONFIG_ROOT=/etc/aeos/memgraph
BACKUP_ROOT="/var/backups/aeos/memgraph/${PROJECT_ID}"
MGCONSOLE=/usr/bin/mgconsole
port=$(sed -n 's/^--bolt-port=//p' "$CONFIG_ROOT/${PROJECT_ID}.conf")
username=$(cut -d: -f1 "$CONFIG_ROOT/${PROJECT_ID}.pass")
password=$(cut -d: -f2- "$CONFIG_ROOT/${PROJECT_ID}.pass")
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$BACKUP_ROOT/${stamp}.cypherl"
temporary=$(mktemp "$BACKUP_ROOT/.${stamp}.XXXXXX")
cleanup() {
  [[ $temporary == "$BACKUP_ROOT/.${stamp}."* ]] && rm -f -- "$temporary"
}
trap cleanup EXIT
printf 'DUMP DATABASE;\n' | env FLAGS_password="$password" "$MGCONSOLE" \
  --fromenv=password --host 127.0.0.1 --port "$port" --use-ssl=true \
  --username "$username" --output-format=cypherl >"$temporary"
grep -q 'AEOSProject' "$temporary"
grep -q 'CURRENT_SNAPSHOT' "$temporary"
install -m 0400 -o root -g root "$temporary" "$target"
sha256sum "$target" | awk '{print $1}' > "$target.sha256"
chmod 0400 "$target.sha256"
find "$BACKUP_ROOT" -maxdepth 1 -type f -mtime +14 -delete
echo "Local AEOS graph recovery point created"
