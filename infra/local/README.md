# Local AEOS project graphs

This is the cost-minimizing default. It uses the already installed Memgraph binary but gives each
AEOS project its own loopback port, operating-system user, credential, data/log/backup directories,
systemd unit, resource ceiling, transaction-consistent graph-dump stream and restore rehearsal. It
never connects to or reuses MultiAgentCommunication's port 7687 or `/var/lib/memgraph` data.

Install Wema's graph:

```bash
sudo infra/local/install-project.sh wema 7697
```

The installer creates a mode-0600 client environment at
`~/.config/aeos/projects/wema.env` for the invoking user. It contains a generated local credential
and must never be committed. Load it only into the local AEOS runner.

Verify and rehearse recovery:

```bash
sudo /usr/local/libexec/aeos/verify-project.sh wema
sudo systemctl start aeos-memgraph-backup@wema.service
sudo /usr/local/libexec/aeos/restore-project.sh wema
```

The graph is advisory and rebuildable. A laptop/WSL shutdown pauses new AEOS recommendations; it
does not affect Wema public pages, Desk, sign-in, orders, mail, analytics collection, or already
authorized effects.

Run the real adapter suite only against its disposable sibling process:

```bash
infra/local/run-integration-instance.sh 7698
```

The script generates a one-run credential and certificate under a temporary directory, runs the
real transactional, replay, scoped-query and concurrent-writer tests, and removes that process and
directory on exit. It never writes integration fixtures into a project graph.
