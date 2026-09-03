"""Static red plants for AEOS's local, project-isolated graph services."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "infra" / "local"


def _read(name: str) -> str:
    return (LOCAL / name).read_text(encoding="utf-8")


def test_service_is_project_scoped_and_sandboxed() -> None:
    service = _read("aeos-memgraph@.service")
    assert "User=aeos-mg-%i" in service
    assert "Group=aeos-mg-%i" in service
    assert "Environment=MEMGRAPH_PASSFILE=/etc/aeos/memgraph/%i.pass" in service
    assert "ReadWritePaths=/var/lib/aeos/memgraph/projects/%i" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service


def test_installer_creates_no_preallocated_volume_or_static_secret() -> None:
    installer = _read("install-project.sh")
    assert "openssl rand -hex 32" in installer
    assert "AEOS_GRAPH_HOST=127.0.0.1" in installer
    assert "chmod 0600" in installer
    assert "fallocate" not in installer
    assert "truncate" not in installer
    assert "aws " not in installer.lower()


def test_project_config_is_loopback_tls_transactional_and_bounded() -> None:
    installer = _read("install-project.sh")
    assert "--bolt-address=127.0.0.1" in installer
    assert "--bolt-cert-file=" in installer
    assert "--auth-password-permit-null=false" in installer
    assert "--storage-mode=IN_MEMORY_TRANSACTIONAL" in installer
    assert "--storage-wal-file-flush-every-n-tx=1" in installer
    assert "--storage-snapshot-interval-sec=900" in installer
    assert "--telemetry-enabled=false" in installer


def test_security_and_recovery_checks_can_fail() -> None:
    verify = _read("verify-project.sh")
    backup = _read("backup-project.sh")
    restore = _read("restore-project.sh")
    assert "anonymous AEOS graph access unexpectedly succeeded" in verify
    assert "unencrypted AEOS graph access unexpectedly succeeded" in verify
    assert '"$restored" == "$current"' in restore
    assert "snapshot_digest" in restore
    assert 'chown "$SERVICE_USER:$SERVICE_USER" "$restore_root"' in restore
    assert 'chmod 0750 "$restore_root"' in restore
    assert "recovery endpoint did not become ready" in restore
    assert '"$restore_root/log/process.log"' in restore
    assert "DUMP DATABASE" in backup
    assert "CURRENT_SNAPSHOT" in backup
    assert 'name \'*.cypherl\'' in restore
    assert '<"$latest"' in restore
    assert "--fromenv=password" in backup
    assert "--fromenv=password" in restore
    assert "--fromenv=password" in verify
    assert "--password" not in backup
    assert "--password" not in restore
    assert "--password" not in verify


def test_backup_service_cannot_write_project_data() -> None:
    service = _read("aeos-memgraph-backup@.service")
    assert "ReadWritePaths=/var/backups/aeos/memgraph/%i" in service
    assert "/var/lib/aeos/memgraph/projects/%i" not in service


def test_integration_suite_uses_a_disposable_sibling() -> None:
    runner = _read("run-integration-instance.sh")
    assert "mktemp -d /tmp/aeos-memgraph-integration" in runner
    assert "AEOS_MEMGRAPH_TEST_SSLMODE=1" in runner
    assert "python3.12 -m pytest -q -m integration" in runner
    assert "rm -rf -- \"$root\"" in runner
