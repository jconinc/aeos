#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 8 ]]; then
  echo "usage: bootstrap-project PROJECT ENV SECRET BUCKET VOLUME PORT REGION PRIVATE_IP" >&2
  exit 2
fi

PROJECT_ID=$1
ENVIRONMENT=$2
SECRET_ID=$3
BACKUP_BUCKET=$4
VOLUME_ID=$5
BOLT_PORT=$6
AWS_REGION_NAME=$7
PRIVATE_IP=$8
IMAGE="memgraph/memgraph:3.7.2"
CONTAINER="aeos-graph-${PROJECT_ID}"
ROOT_DIR="/srv/aeos/projects/${PROJECT_ID}"
CONFIG_DIR="/etc/aeos/projects"

[[ $PROJECT_ID =~ ^[a-z][a-z0-9-]{1,31}$ ]] || exit 2
[[ $ENVIRONMENT =~ ^[a-z][a-z0-9-]{1,31}$ ]] || exit 2
[[ $BOLT_PORT =~ ^[0-9]+$ ]] || exit 2
[[ $PRIVATE_IP =~ ^[0-9.]+$ ]] || exit 2

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl docker.io jq openssl unattended-upgrades unzip
if ! command -v aws >/dev/null 2>&1; then
  awscli_version=2.32.2
  awscli_sha256=572acdf73eec819a637dae60d165ae30c0eff1c94256e4b65a52033ee1d7c1f3
  awscli_root=$(mktemp -d /tmp/aeos-awscli.XXXXXX)
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-aarch64-${awscli_version}.zip" \
    -o "$awscli_root/awscliv2.zip"
  printf '%s  %s\n' "$awscli_sha256" "$awscli_root/awscliv2.zip" | sha256sum -c -
  unzip -q "$awscli_root/awscliv2.zip" -d "$awscli_root"
  "$awscli_root/aws/install" --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli
  rm -rf -- "$awscli_root"
fi
systemctl enable --now docker
systemctl disable --now ssh 2>/dev/null || true

install -d -m 0755 /etc/sysctl.d
printf 'vm.max_map_count=262144\n' > /etc/sysctl.d/90-aeos-memgraph.conf
sysctl --system >/dev/null

clean_volume=${VOLUME_ID//-/}
device=""
for candidate in \
  "/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${clean_volume}" \
  /dev/xvdf /dev/sdf; do
  if [[ -b $candidate ]]; then
    device=$(readlink -f "$candidate")
    break
  fi
done
if [[ -z $device ]]; then
  echo "the retained graph data volume is not attached" >&2
  exit 1
fi
root_device=$(findmnt -n -o SOURCE /)
if [[ $device == "$root_device" ]]; then
  echo "refusing to format the root device" >&2
  exit 1
fi
if ! blkid "$device" >/dev/null 2>&1; then
  mkfs.ext4 -F -L "aeos-${PROJECT_ID}" "$device" >/dev/null
fi
install -d -m 0755 "$ROOT_DIR"
uuid=$(blkid -s UUID -o value "$device")
if ! grep -q "UUID=${uuid}" /etc/fstab; then
  printf 'UUID=%s %s ext4 defaults,nofail,nodev,nosuid 0 2\n' "$uuid" "$ROOT_DIR" >> /etc/fstab
fi
mountpoint -q "$ROOT_DIR" || mount "$ROOT_DIR"
install -d -m 0750 "$ROOT_DIR/data" "$ROOT_DIR/log" "$ROOT_DIR/tls"

secret_json=$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION_NAME" --secret-id "$SECRET_ID" --query SecretString --output text)
username=$(jq -er '.username' <<<"$secret_json")
password=$(jq -er '.password' <<<"$secret_json")
secret_host=$(jq -er '.host' <<<"$secret_json")
[[ $secret_host == "$PRIVATE_IP" ]] || { echo "graph secret host does not match instance" >&2; exit 1; }

printf '%s:%s\n' "$username" "$password" > "$ROOT_DIR/user.pass"
chmod 0400 "$ROOT_DIR/user.pass"
if [[ ! -s $ROOT_DIR/tls/cert.pem || ! -s $ROOT_DIR/tls/key.pem ]]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 397 \
    -subj "/CN=${PRIVATE_IP}" -addext "subjectAltName=IP:${PRIVATE_IP}" \
    -keyout "$ROOT_DIR/tls/key.pem" -out "$ROOT_DIR/tls/cert.pem" >/dev/null 2>&1
fi

docker pull "$IMAGE" >/dev/null
memgraph_uid=$(docker run --rm --entrypoint sh "$IMAGE" -c 'id -u memgraph 2>/dev/null || id -u')
memgraph_gid=$(docker run --rm --entrypoint sh "$IMAGE" -c 'id -g memgraph 2>/dev/null || id -g')
chown -R "$memgraph_uid:$memgraph_gid" "$ROOT_DIR/data" "$ROOT_DIR/log" "$ROOT_DIR/tls"
chown "$memgraph_uid:$memgraph_gid" "$ROOT_DIR/user.pass"
chmod 0400 "$ROOT_DIR/tls/key.pem" "$ROOT_DIR/user.pass"

if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  systemctl stop "aeos-graph-${PROJECT_ID}.service" 2>/dev/null || true
  docker rm -f "$CONTAINER" >/dev/null
fi
docker create --name "$CONTAINER" --restart=no \
  --memory=12g --memory-swap=12g --cpus=2 \
  --security-opt=no-new-privileges:true \
  --log-opt=max-size=50m --log-opt=max-file=5 \
  -p "${PRIVATE_IP}:${BOLT_PORT}:7687" \
  -v "$ROOT_DIR/data:/var/lib/memgraph" \
  -v "$ROOT_DIR/log:/var/log/memgraph" \
  -v "$ROOT_DIR/tls:/etc/memgraph/ssl:ro" \
  -v "$ROOT_DIR/user.pass:/run/secrets/user.pass:ro" \
  -e MEMGRAPH_PASSFILE=/run/secrets/user.pass \
  "$IMAGE" \
  --bolt-cert-file=/etc/memgraph/ssl/cert.pem \
  --bolt-key-file=/etc/memgraph/ssl/key.pem \
  --log-failed-queries=true --log-min-duration-ms=1000 \
  --memory-limit=10240 --memory-warning-threshold=2048 \
  --query-execution-timeout-sec=30 --storage-mode=IN_MEMORY_TRANSACTIONAL \
  --storage-snapshot-interval-sec=900 --storage-snapshot-on-exit=true \
  --storage-snapshot-retention-count=24 --storage-wal-enabled=true \
  --storage-wal-file-flush-every-n-tx=1 --strict-flag-check=true \
  --telemetry-enabled=false >/dev/null

install -d -m 0750 "$CONFIG_DIR" /var/lib/aeos
cat > "$CONFIG_DIR/${PROJECT_ID}.env" <<EOF
PROJECT_ID=${PROJECT_ID}
ENVIRONMENT=${ENVIRONMENT}
SECRET_ID=${SECRET_ID}
BACKUP_BUCKET=${BACKUP_BUCKET}
AWS_REGION_NAME=${AWS_REGION_NAME}
CONTAINER=${CONTAINER}
ROOT_DIR=${ROOT_DIR}
PRIVATE_IP=${PRIVATE_IP}
BOLT_PORT=${BOLT_PORT}
EOF
chmod 0640 "$CONFIG_DIR/${PROJECT_ID}.env"

cat > "/etc/systemd/system/aeos-graph-${PROJECT_ID}.service" <<EOF
[Unit]
Description=AEOS ${PROJECT_ID} project graph
After=docker.service network-online.target
Requires=docker.service
[Service]
ExecStart=/usr/bin/docker start -a ${CONTAINER}
ExecStop=/usr/bin/docker stop --time 60 ${CONTAINER}
Restart=always
RestartSec=5
TimeoutStopSec=75
[Install]
WantedBy=multi-user.target
EOF

for task in backup monitor; do
  cat > "/etc/systemd/system/aeos-graph-${PROJECT_ID}-${task}.service" <<EOF
[Unit]
Description=AEOS ${PROJECT_ID} graph ${task}
After=aeos-graph-${PROJECT_ID}.service
[Service]
Type=oneshot
ExecStart=/opt/aeos/bootstrap/${task}-project.sh ${PROJECT_ID}
EOF
done
cat > "/etc/systemd/system/aeos-graph-${PROJECT_ID}-backup.timer" <<EOF
[Unit]
Description=Daily AEOS ${PROJECT_ID} graph recovery point
[Timer]
OnCalendar=*-*-* 03:20:00 UTC
Persistent=true
RandomizedDelaySec=900
[Install]
WantedBy=timers.target
EOF
cat > "/etc/systemd/system/aeos-graph-${PROJECT_ID}-monitor.timer" <<EOF
[Unit]
Description=AEOS ${PROJECT_ID} graph health metrics
[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now "aeos-graph-${PROJECT_ID}.service"
systemctl enable --now "aeos-graph-${PROJECT_ID}-backup.timer"
systemctl enable --now "aeos-graph-${PROJECT_ID}-monitor.timer"
echo "AEOS project graph bootstrap complete"
