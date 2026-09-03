#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_ID=${1:?project id required}
source "/etc/aeos/projects/${PROJECT_ID}.env"
metric_value=0
report_metric() {
  aws cloudwatch put-metric-data --region "$AWS_REGION_NAME" \
    --namespace AEOS/GraphFleet \
    --dimensions "ProjectId=${PROJECT_ID},Environment=${ENVIRONMENT}" \
    --metric-name BackupSucceeded --unit Count --value "$metric_value" >/dev/null || true
}
trap report_metric EXIT

secret_json=$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION_NAME" --secret-id "$SECRET_ID" --query SecretString --output text)
username=$(jq -er '.username' <<<"$secret_json")
password=$(jq -er '.password' <<<"$secret_json")
printf 'CREATE SNAPSHOT;\n' | docker exec -i "$CONTAINER" mgconsole \
  --host 127.0.0.1 --port 7687 --use-ssl=true \
  --username "$username" --password "$password" >/dev/null

snapshot=$(find "$ROOT_DIR/data/snapshots" -maxdepth 1 -type f -printf '%T@ %p\n' \
  | sort -nr | head -1 | cut -d' ' -f2-)
[[ -n $snapshot && -s $snapshot ]] || { echo "snapshot was not created" >&2; exit 1; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
name=$(basename "$snapshot")
key="projects/${PROJECT_ID}/${stamp}/${name}"
checksum_file=$(mktemp)
trap 'rm -f "$checksum_file"; report_metric' EXIT
sha256sum "$snapshot" | awk '{print $1}' > "$checksum_file"
aws s3 cp "$snapshot" "s3://${BACKUP_BUCKET}/${key}" \
  --region "$AWS_REGION_NAME" --sse AES256 --only-show-errors
aws s3 cp "$checksum_file" "s3://${BACKUP_BUCKET}/${key}.sha256" \
  --region "$AWS_REGION_NAME" --sse AES256 --only-show-errors
date -u +%s > "/var/lib/aeos/${PROJECT_ID}-last-backup-epoch"
metric_value=1
echo "AEOS project graph recovery point uploaded"
