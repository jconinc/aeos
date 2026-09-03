#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=${1:?project id required}
source "/etc/aeos/projects/${PROJECT_ID}.env"
now=$(date -u +%s)
up=0
if [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true) == true ]]; then
  up=1
fi
disk_used=$(df -P "$ROOT_DIR" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')
memory_used=$(docker stats --no-stream --format '{{.MemPerc}}' "$CONTAINER" 2>/dev/null \
  | tr -d '%' || true)
memory_used=${memory_used:-100}
snapshot_epoch=$(find "$ROOT_DIR/data/snapshots" -maxdepth 1 -type f -printf '%T@\n' \
  2>/dev/null | sort -nr | head -1 | cut -d. -f1)
backup_epoch=$(cat "/var/lib/aeos/${PROJECT_ID}-last-backup-epoch" 2>/dev/null || echo 0)
snapshot_age=$((snapshot_epoch > 0 ? now - snapshot_epoch : 2147483647))
backup_age=$((backup_epoch > 0 ? now - backup_epoch : 2147483647))
dimensions="ProjectId=${PROJECT_ID},Environment=${ENVIRONMENT}"
aws cloudwatch put-metric-data --region "$AWS_REGION_NAME" --namespace AEOS/GraphFleet \
  --dimensions "$dimensions" --metric-data \
  "MetricName=ProcessUp,Value=${up},Unit=Count" \
  "MetricName=DataVolumeUsed,Value=${disk_used},Unit=Percent" \
  "MetricName=ContainerMemoryUsed,Value=${memory_used},Unit=Percent" \
  "MetricName=SnapshotAge,Value=${snapshot_age},Unit=Seconds" \
  "MetricName=BackupAge,Value=${backup_age},Unit=Seconds" >/dev/null
