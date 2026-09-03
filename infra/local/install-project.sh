#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $EUID -ne 0 || $# -lt 2 || $# -gt 5 ]]; then
  echo "usage: sudo install-project.sh PROJECT BOLT_PORT [MEMORY_MIB METRICS_PORT MONITOR_PORT]" >&2
  exit 2
fi
PROJECT_ID=$1
BOLT_PORT=$2
MEMORY_MIB=${3:-10240}
METRICS_PORT=${4:-9197}
MONITOR_PORT=${5:-7454}
[[ $PROJECT_ID =~ ^[a-z][a-z0-9-]{1,31}$ ]] || exit 2
for value in "$BOLT_PORT" "$MEMORY_MIB" "$METRICS_PORT" "$MONITOR_PORT"; do
  [[ $value =~ ^[0-9]+$ ]] || exit 2
done
if ss -H -lnt "sport = :${BOLT_PORT}" | grep -q . \
  && ! systemctl is-active --quiet "aeos-memgraph@${PROJECT_ID}.service"; then
  echo "port ${BOLT_PORT} is already in use" >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SERVICE_USER="aeos-mg-${PROJECT_ID}"
CONFIG_ROOT=/etc/aeos/memgraph
DATA_ROOT="/var/lib/aeos/memgraph/projects/${PROJECT_ID}"
LOG_ROOT="/var/log/aeos/memgraph/${PROJECT_ID}"
BACKUP_ROOT="/var/backups/aeos/memgraph/${PROJECT_ID}"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -m 0750 -o root -g "$SERVICE_USER" "$CONFIG_ROOT"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" \
  "$DATA_ROOT" "$LOG_ROOT"
install -d -m 0700 -o root -g root "$BACKUP_ROOT" /usr/local/libexec/aeos

passfile="$CONFIG_ROOT/${PROJECT_ID}.pass"
if [[ ! -s $passfile ]]; then
  printf '%s_runtime:%s\n' "$PROJECT_ID" "$(openssl rand -hex 32)" > "$passfile"
fi
chown root:"$SERVICE_USER" "$passfile"
chmod 0640 "$passfile"
certfile="$CONFIG_ROOT/${PROJECT_ID}.cert.pem"
keyfile="$CONFIG_ROOT/${PROJECT_ID}.key.pem"
if [[ ! -s $certfile || ! -s $keyfile ]]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 397 \
    -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
    -keyout "$keyfile" -out "$certfile" >/dev/null 2>&1
fi
chown root:"$SERVICE_USER" "$certfile" "$keyfile"
chmod 0640 "$certfile" "$keyfile"

cat > "$CONFIG_ROOT/${PROJECT_ID}.conf" <<EOF
--auth-password-permit-null=false
--bolt-address=127.0.0.1
--bolt-port=${BOLT_PORT}
--bolt-cert-file=${certfile}
--bolt-key-file=${keyfile}
--data-directory=${DATA_ROOT}
--log-file=${LOG_ROOT}/memgraph.log
--log-failed-queries=true
--log-min-duration-ms=1000
--memory-limit=${MEMORY_MIB}
--memory-warning-threshold=2048
--metrics-address=127.0.0.1
--metrics-port=${METRICS_PORT}
--monitoring-address=127.0.0.1
--monitoring-port=${MONITOR_PORT}
--password-encryption-algorithm=bcrypt
--query-execution-timeout-sec=30
--storage-mode=IN_MEMORY_TRANSACTIONAL
--storage-snapshot-interval-sec=900
--storage-snapshot-on-exit=true
--storage-snapshot-retention-count=24
--storage-wal-enabled=true
--storage-wal-file-flush-every-n-tx=1
--strict-flag-check=true
--telemetry-enabled=false
EOF
chown root:"$SERVICE_USER" "$CONFIG_ROOT/${PROJECT_ID}.conf"
chmod 0640 "$CONFIG_ROOT/${PROJECT_ID}.conf"

install -m 0755 "$SCRIPT_DIR/backup-project.sh" /usr/local/libexec/aeos/backup-project.sh
install -m 0755 "$SCRIPT_DIR/verify-project.sh" /usr/local/libexec/aeos/verify-project.sh
install -m 0755 "$SCRIPT_DIR/restore-project.sh" /usr/local/libexec/aeos/restore-project.sh
install -m 0644 "$SCRIPT_DIR/aeos-memgraph@.service" /etc/systemd/system/aeos-memgraph@.service
install -m 0644 "$SCRIPT_DIR/aeos-memgraph-backup@.service" \
  /etc/systemd/system/aeos-memgraph-backup@.service
install -m 0644 "$SCRIPT_DIR/aeos-memgraph-backup@.timer" \
  /etc/systemd/system/aeos-memgraph-backup@.timer

caller=${SUDO_USER:-}
if [[ -n $caller && $caller != root ]]; then
  caller_home=$(getent passwd "$caller" | cut -d: -f6)
  client_root="$caller_home/.config/aeos/projects"
  install -d -m 0700 -o "$caller" -g "$caller" "$client_root"
  password=$(cut -d: -f2- "$passfile")
  cat > "$client_root/${PROJECT_ID}.env" <<EOF
AEOS_GRAPH_ENABLED=true
AEOS_GRAPH_HOST=127.0.0.1
AEOS_GRAPH_PORT=${BOLT_PORT}
AEOS_GRAPH_USERNAME=${PROJECT_ID}_runtime
AEOS_GRAPH_PASSWORD=${password}
AEOS_GRAPH_SSLMODE=require
AEOS_GRAPH_PROJECT_ID=${PROJECT_ID}
AEOS_GRAPH_VERTICAL_ID=article_decision
AEOS_GRAPH_TENANT_ID=${PROJECT_ID}_local
EOF
  chown "$caller:$caller" "$client_root/${PROJECT_ID}.env"
  chmod 0600 "$client_root/${PROJECT_ID}.env"
fi

systemctl daemon-reload
systemctl enable --now "aeos-memgraph@${PROJECT_ID}.service"
systemctl enable --now "aeos-memgraph-backup@${PROJECT_ID}.timer"
/usr/local/libexec/aeos/verify-project.sh "$PROJECT_ID"
echo "AEOS ${PROJECT_ID} graph installed locally on 127.0.0.1:${BOLT_PORT}"
