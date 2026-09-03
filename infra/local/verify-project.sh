#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=${1:?project id required}
CONFIG_ROOT=/etc/aeos/memgraph
MGCONSOLE=/usr/bin/mgconsole
port=$(sed -n 's/^--bolt-port=//p' "$CONFIG_ROOT/${PROJECT_ID}.conf")
username=$(cut -d: -f1 "$CONFIG_ROOT/${PROJECT_ID}.pass")
password=$(cut -d: -f2- "$CONFIG_ROOT/${PROJECT_ID}.pass")
listener=$(ss -H -lnt "sport = :${port}")
grep -q "127.0.0.1:${port}" <<<"$listener"
if grep -Eq "(0\.0\.0\.0|\[::\]):${port}" <<<"$listener"; then
  echo "AEOS graph escaped the loopback boundary" >&2
  exit 1
fi
if printf 'RETURN 1;\n' | "$MGCONSOLE" --host 127.0.0.1 --port "$port" \
  --use-ssl=true >/dev/null 2>&1; then
  echo "anonymous AEOS graph access unexpectedly succeeded" >&2
  exit 1
fi
if printf 'RETURN 1;\n' | "$MGCONSOLE" --host 127.0.0.1 --port "$port" \
  --use-ssl=false --username "$username" --password "$password" >/dev/null 2>&1; then
  echo "unencrypted AEOS graph access unexpectedly succeeded" >&2
  exit 1
fi
version=$(printf 'SHOW VERSION;\n' | "$MGCONSOLE" --host 127.0.0.1 --port "$port" \
  --use-ssl=true --username "$username" --password "$password")
grep -q '3.7.2' <<<"$version"
systemctl is-active --quiet "aeos-memgraph@${PROJECT_ID}.service"
echo "Local AEOS graph loopback, TLS, authentication and version verified"
