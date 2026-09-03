#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_ID=${1:?project id required}
CONFIG_ROOT=/etc/aeos/memgraph
BACKUP_ROOT="/var/backups/aeos/memgraph/${PROJECT_ID}"
SERVICE_USER="aeos-mg-${PROJECT_ID}"
MGCONSOLE=/usr/bin/mgconsole
restore_root=$(mktemp -d "/var/lib/aeos/memgraph/restore-${PROJECT_ID}.XXXXXX")
restore_pid=""
cleanup() {
  [[ -n $restore_pid ]] && kill "$restore_pid" >/dev/null 2>&1 || true
  [[ -n $restore_pid ]] && wait "$restore_pid" >/dev/null 2>&1 || true
  [[ $restore_root == "/var/lib/aeos/memgraph/restore-${PROJECT_ID}."* ]] \
    && rm -rf -- "$restore_root"
}
trap cleanup EXIT
latest=$(find "$BACKUP_ROOT" -maxdepth 1 -type f ! -name '*.sha256' -printf '%T@ %p\n' \
  | sort -nr | head -1 | cut -d' ' -f2-)
[[ -n $latest ]] || { echo "no local recovery point exists" >&2; exit 1; }
[[ $(sha256sum "$latest" | awk '{print $1}') == "$(cat "$latest.sha256")" ]]
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" \
  "$restore_root/data/snapshots" "$restore_root/log"
install -m 0640 -o "$SERVICE_USER" -g "$SERVICE_USER" \
  "$latest" "$restore_root/data/snapshots/$(basename "$latest")"
port=$(sed -n 's/^--bolt-port=//p' "$CONFIG_ROOT/${PROJECT_ID}.conf")
restore_port=$((port + 10000))
username=$(cut -d: -f1 "$CONFIG_ROOT/${PROJECT_ID}.pass")
password=$(cut -d: -f2- "$CONFIG_ROOT/${PROJECT_ID}.pass")
runuser -u "$SERVICE_USER" -- env \
  "MEMGRAPH_PASSFILE=$CONFIG_ROOT/${PROJECT_ID}.pass" /usr/lib/memgraph/memgraph \
  --bolt-address=127.0.0.1 --bolt-port="$restore_port" \
  --bolt-cert-file="$CONFIG_ROOT/${PROJECT_ID}.cert.pem" \
  --bolt-key-file="$CONFIG_ROOT/${PROJECT_ID}.key.pem" \
  --data-directory="$restore_root/data" --log-file="$restore_root/log/memgraph.log" \
  --memory-limit=2048 --monitoring-port=$((restore_port + 1)) \
  --metrics-port=$((restore_port + 2)) --storage-snapshot-interval-sec=900 \
  --storage-wal-enabled=true --telemetry-enabled=false &
restore_pid=$!
query='MATCH (p:AEOSProject)-[:CURRENT_SNAPSHOT]->(s:AEOSSnapshot) RETURN s.generation, s.snapshot_digest;'
for _ in $(seq 1 30); do
  if restored=$(printf '%s\n' "$query" | "$MGCONSOLE" --host 127.0.0.1 \
    --port "$restore_port" --use-ssl=true --username "$username" \
    --password "$password" 2>/dev/null); then
    break
  fi
  sleep 1
done
current=$(printf '%s\n' "$query" | "$MGCONSOLE" --host 127.0.0.1 --port "$port" \
  --use-ssl=true --username "$username" --password "$password")
[[ -n ${restored:-} && "$restored" == "$current" ]]
grep -Eq '[0-9a-f]{64}' <<<"$restored"
echo "Local AEOS graph recovery endpoint matches current generation and digest"
