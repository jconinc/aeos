#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_ID=${1:?project id required}
source "/etc/aeos/projects/${PROJECT_ID}.env"
restore_root=$(mktemp -d "${ROOT_DIR}/restore-check.XXXXXX")
restore_container="${CONTAINER}-restore-check"
cleanup() {
  docker rm -f "$restore_container" >/dev/null 2>&1 || true
  [[ $restore_root == "${ROOT_DIR}/restore-check."* ]] && rm -rf -- "$restore_root"
}
trap cleanup EXIT

latest_key=$(aws s3 ls "s3://${BACKUP_BUCKET}/projects/${PROJECT_ID}/" \
  --region "$AWS_REGION_NAME" --recursive \
  | awk '$4 !~ /\.sha256$/ {key=$4} END {print key}')
[[ -n $latest_key ]] || { echo "no graph recovery point exists" >&2; exit 1; }
install -d -m 0750 "$restore_root/snapshots" "$restore_root/log"
snapshot="$restore_root/snapshots/$(basename "$latest_key")"
aws s3 cp "s3://${BACKUP_BUCKET}/${latest_key}" "$snapshot" \
  --region "$AWS_REGION_NAME" --only-show-errors
remote_checksum=$(aws s3 cp "s3://${BACKUP_BUCKET}/${latest_key}.sha256" - \
  --region "$AWS_REGION_NAME" --only-show-errors)
[[ $(sha256sum "$snapshot" | awk '{print $1}') == "$remote_checksum" ]]

image=$(docker inspect -f '{{.Config.Image}}' "$CONTAINER")
memgraph_uid=$(docker run --rm --entrypoint sh "$image" -c 'id -u memgraph 2>/dev/null || id -u')
memgraph_gid=$(docker run --rm --entrypoint sh "$image" -c 'id -g memgraph 2>/dev/null || id -g')
chown -R "$memgraph_uid:$memgraph_gid" "$restore_root"
docker run -d --name "$restore_container" --memory=3g --memory-swap=3g --cpus=1 \
  --security-opt=no-new-privileges:true -p 127.0.0.1:17687:7687 \
  -v "$restore_root:/var/lib/memgraph" \
  -v "$ROOT_DIR/tls:/etc/memgraph/ssl:ro" \
  -v "$ROOT_DIR/user.pass:/run/secrets/user.pass:ro" \
  -e MEMGRAPH_PASSFILE=/run/secrets/user.pass "$image" \
  --bolt-cert-file=/etc/memgraph/ssl/cert.pem \
  --bolt-key-file=/etc/memgraph/ssl/key.pem \
  --storage-mode=IN_MEMORY_TRANSACTIONAL --storage-snapshot-interval-sec=900 \
  --storage-wal-enabled=true --telemetry-enabled=false >/dev/null

secret_json=$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION_NAME" --secret-id "$SECRET_ID" --query SecretString --output text)
username=$(jq -er '.username' <<<"$secret_json")
password=$(jq -er '.password' <<<"$secret_json")
query='MATCH (p:AEOSProject)-[:CURRENT_SNAPSHOT]->(s:AEOSSnapshot) RETURN s.generation, s.snapshot_digest;'
for _ in $(seq 1 30); do
  if restored=$(printf '%s\n' "$query" | docker exec -i "$restore_container" mgconsole \
    --host 127.0.0.1 --port 7687 --use-ssl=true \
    --username "$username" --password "$password" 2>/dev/null); then
    break
  fi
  sleep 1
done
current=$(printf '%s\n' "$query" | docker exec -i "$CONTAINER" mgconsole \
  --host 127.0.0.1 --port 7687 --use-ssl=true \
  --username "$username" --password "$password")
[[ -n ${restored:-} && "$restored" == "$current" ]]
grep -Eq '[0-9a-f]{64}' <<<"$restored"
echo "AEOS project graph recovery endpoint matches the current generation and digest"
