#!/usr/bin/env bash
set -euo pipefail
umask 077

PORT=${1:-7698}
[[ $PORT =~ ^[0-9]+$ ]] || exit 2
if ss -H -lnt "sport = :${PORT}" | grep -q .; then
  echo "integration port ${PORT} is already in use" >&2
  exit 1
fi
root=$(mktemp -d /tmp/aeos-memgraph-integration.XXXXXX)
pid=""
cleanup() {
  [[ -n $pid ]] && kill "$pid" >/dev/null 2>&1 || true
  [[ -n $pid ]] && wait "$pid" >/dev/null 2>&1 || true
  [[ $root == /tmp/aeos-memgraph-integration.* ]] && rm -rf -- "$root"
}
trap cleanup EXIT
install -d -m 0700 "$root/data" "$root/log" "$root/tls"
username=integration_runtime
password=$(openssl rand -hex 32)
printf '%s:%s\n' "$username" "$password" > "$root/user.pass"
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -subj /CN=localhost -addext subjectAltName=DNS:localhost,IP:127.0.0.1 \
  -keyout "$root/tls/key.pem" -out "$root/tls/cert.pem" >/dev/null 2>&1
MEMGRAPH_PASSFILE="$root/user.pass" /usr/lib/memgraph/memgraph \
  --bolt-address=127.0.0.1 --bolt-port="$PORT" \
  --bolt-cert-file="$root/tls/cert.pem" --bolt-key-file="$root/tls/key.pem" \
  --data-directory="$root/data" --log-file="$root/log/memgraph.log" \
  --memory-limit=2048 --metrics-port=$((PORT + 1000)) \
  --monitoring-port=$((PORT + 1001)) --storage-snapshot-interval-sec=300 \
  --storage-wal-enabled=true --telemetry-enabled=false &
pid=$!
for _ in $(seq 1 30); do
  if printf 'RETURN 1;\n' | /usr/bin/mgconsole --host 127.0.0.1 --port "$PORT" \
    --use-ssl=true --username "$username" --password "$password" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
kill -0 "$pid"
AEOS_MEMGRAPH_TEST_HOST=127.0.0.1 AEOS_MEMGRAPH_TEST_PORT="$PORT" \
AEOS_MEMGRAPH_TEST_USERNAME="$username" AEOS_MEMGRAPH_TEST_PASSWORD="$password" \
AEOS_MEMGRAPH_TEST_SSLMODE=1 PYTHONPATH=src \
  python3.12 -m pytest -q -m integration
