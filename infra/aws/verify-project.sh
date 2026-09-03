#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=${1:?project id required}
source "/etc/aeos/projects/${PROJECT_ID}.env"
secret_json=$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION_NAME" --secret-id "$SECRET_ID" --query SecretString --output text)
username=$(jq -er '.username' <<<"$secret_json")
password=$(jq -er '.password' <<<"$secret_json")

listener=$(ss -H -lnt "sport = :${BOLT_PORT}")
grep -q "${PRIVATE_IP}:${BOLT_PORT}" <<<"$listener"
if grep -Eq "(0\.0\.0\.0|\[::\]):${BOLT_PORT}" <<<"$listener"; then
  echo "Bolt is listening beyond the instance private address" >&2
  exit 1
fi

if printf 'RETURN 1;\n' | docker exec -i "$CONTAINER" mgconsole \
  --host 127.0.0.1 --port 7687 --use-ssl=true >/dev/null 2>&1; then
  echo "anonymous graph authentication unexpectedly succeeded" >&2
  exit 1
fi
if printf 'RETURN 1;\n' | docker exec -i "$CONTAINER" mgconsole \
  --host 127.0.0.1 --port 7687 --use-ssl=false \
  --username "$username" --password "$password" >/dev/null 2>&1; then
  echo "unencrypted graph connection unexpectedly succeeded" >&2
  exit 1
fi
version=$(printf 'SHOW VERSION;\n' | docker exec -i "$CONTAINER" mgconsole \
  --host 127.0.0.1 --port 7687 --use-ssl=true \
  --username "$username" --password "$password")
grep -q '3.7.2' <<<"$version"
docker inspect -f '{{.State.Running}} {{.HostConfig.Memory}} {{.Config.Image}}' "$CONTAINER"
echo "AEOS project graph TLS, authentication, version and private listener verified"
