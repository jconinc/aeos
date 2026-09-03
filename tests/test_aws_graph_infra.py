"""Static red plants for the generic project-isolated AWS graph stack."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "aws"


def _read(name: str) -> str:
    return (INFRA / name).read_text(encoding="utf-8")


def test_stack_has_project_isolation_and_retained_encrypted_recovery() -> None:
    template = _read("project-graph.yaml")
    assert "SourceSecurityGroupId: !Ref WorkerSecurityGroupId" in template
    assert "AssociatePublicIpAddress: true" in template
    assert "DeletionPolicy: Retain" in template
    assert template.count("Encrypted: true") >= 2
    assert "VolumeType: gp3" in template
    assert "BlockPublicAcls: true" in template
    assert "aws:SecureTransport: false" in template
    assert "GenerateStringKey: password" in template
    assert "secretsmanager:GetSecretValue" in template
    assert "ProjectId:" in template
    assert "EnvironmentName:" in template
    assert "AEOS/GraphFleet" in template


def test_bootstrap_binds_only_private_bolt_with_tls_auth_and_durability() -> None:
    bootstrap = _read("bootstrap-project.sh")
    assert '-p "${PRIVATE_IP}:${BOLT_PORT}:7687"' in bootstrap
    assert "MEMGRAPH_PASSFILE=/run/secrets/user.pass" in bootstrap
    assert "--bolt-cert-file=" in bootstrap
    assert "--storage-mode=IN_MEMORY_TRANSACTIONAL" in bootstrap
    assert "--storage-wal-file-flush-every-n-tx=1" in bootstrap
    assert "--storage-snapshot-interval-sec=900" in bootstrap
    assert "--telemetry-enabled=false" in bootstrap
    assert "-p 3000:" not in bootstrap
    assert "-p 7444:" not in bootstrap


def test_verification_proves_negative_security_and_recovery_controls() -> None:
    verify = _read("verify-project.sh")
    restore = _read("restore-project.sh")
    assert "anonymous graph authentication unexpectedly succeeded" in verify
    assert "unencrypted graph connection unexpectedly succeeded" in verify
    assert "0\\.0\\.0\\.0" in verify
    assert "restore-check" in restore
    assert '"$restored" == "$current"' in restore
    assert "snapshot_digest" in restore


def test_deploy_sends_no_static_secret_to_the_host() -> None:
    deploy = _read("deploy-project.sh")
    assert "get-secret-value" in deploy
    assert "put-secret-value" in deploy
    assert "password=" not in deploy
    assert "aws_access_key" not in deploy.lower()
    assert "aws_secret" not in deploy.lower()
