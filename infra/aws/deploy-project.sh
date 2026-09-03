#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_ID=${1:-wema}
ENVIRONMENT=${2:-production}
REGION=${AWS_REGION:-us-east-1}
PROFILE=${AWS_PROFILE:-personal}
VPC_ID=${AEOS_VPC_ID:-vpc-0c6160169add97eb5}
SUBNET_ID=${AEOS_SUBNET_ID:-subnet-0df3263b14d31688d}
WORKER_SG=${AEOS_WORKER_SECURITY_GROUP_ID:-sg-0717ef66acc24007a}
STACK="aeos-graph-${PROJECT_ID}-${ENVIRONMENT}"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
AWS=(aws --profile "$PROFILE" --region "$REGION")

[[ $PROJECT_ID =~ ^[a-z][a-z0-9-]{1,31}$ ]] || exit 2
[[ $ENVIRONMENT =~ ^[a-z][a-z0-9-]{1,31}$ ]] || exit 2
"${AWS[@]}" cloudformation validate-template \
  --template-body "file://${SCRIPT_DIR}/project-graph.yaml" >/dev/null
"${AWS[@]}" cloudformation deploy --stack-name "$STACK" \
  --template-file "$SCRIPT_DIR/project-graph.yaml" --capabilities CAPABILITY_IAM \
  --parameter-overrides "ProjectId=${PROJECT_ID}" "EnvironmentName=${ENVIRONMENT}" \
  "VpcId=${VPC_ID}" "SubnetId=${SUBNET_ID}" "WorkerSecurityGroupId=${WORKER_SG}" \
  --tags "aeos:project=${PROJECT_ID}" "aeos:environment=${ENVIRONMENT}"

outputs=$("${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs' --output json)
output() { jq -er --arg key "$1" '.[] | select(.OutputKey == $key) | .OutputValue' <<<"$outputs"; }
instance_id=$(output InstanceId)
private_ip=$(output PrivateIp)
secret_arn=$(output SecretArn)
secret_name=$(output SecretName)
backup_bucket=$(output BackupBucket)
volume_id=$(output DataVolumeId)
bolt_port=$(output BoltPort)

secret_file=$(mktemp)
updated_secret=$(mktemp)
parameters_file=$(mktemp)
trap 'rm -f "$secret_file" "$updated_secret" "$parameters_file"' EXIT
"${AWS[@]}" secretsmanager get-secret-value --secret-id "$secret_arn" \
  --query SecretString --output text > "$secret_file"
jq --arg host "$private_ip" '.host = $host' "$secret_file" > "$updated_secret"
"${AWS[@]}" secretsmanager put-secret-value --secret-id "$secret_arn" \
  --secret-string "file://${updated_secret}" >/dev/null

for _ in $(seq 1 40); do
  state=$("${AWS[@]}" ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=${instance_id}" \
    --query 'InstanceInformationList[0].PingStatus' --output text)
  [[ $state == Online ]] && break
  sleep 10
done
[[ ${state:-} == Online ]] || { echo "graph host did not become SSM-online" >&2; exit 1; }

commands=("install -d -m 0700 /opt/aeos/bootstrap")
for script in bootstrap-project.sh backup-project.sh monitor-project.sh verify-project.sh restore-project.sh; do
  encoded=$(base64 -w0 "$SCRIPT_DIR/$script")
  commands+=("printf '%s' '${encoded}' | base64 -d > '/opt/aeos/bootstrap/${script}'")
  commands+=("chmod 0700 '/opt/aeos/bootstrap/${script}'")
done
commands+=("/opt/aeos/bootstrap/bootstrap-project.sh '${PROJECT_ID}' '${ENVIRONMENT}' '${secret_name}' '${backup_bucket}' '${volume_id}' '${bolt_port}' '${REGION}' '${private_ip}'")
jq -n --argjson commands "$(printf '%s\n' "${commands[@]}" | jq -R . | jq -s .)" \
  '{commands: $commands}' > "$parameters_file"
command_id=$("${AWS[@]}" ssm send-command --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript --comment "Bootstrap isolated AEOS project graph" \
  --parameters "file://${parameters_file}" --query 'Command.CommandId' --output text)
"${AWS[@]}" ssm wait command-executed --command-id "$command_id" --instance-id "$instance_id"
status=$("${AWS[@]}" ssm get-command-invocation --command-id "$command_id" \
  --instance-id "$instance_id" --query Status --output text)
[[ $status == Success ]] || {
  "${AWS[@]}" ssm get-command-invocation --command-id "$command_id" \
    --instance-id "$instance_id" --query StandardErrorContent --output text
  exit 1
}
echo "AEOS graph stack ${STACK} is provisioned at private endpoint ${private_ip}:${bolt_port}"
echo "Secret ARN: ${secret_arn}"
echo "Instance: ${instance_id}; retained data volume: ${volume_id}; backup bucket: ${backup_bucket}"
