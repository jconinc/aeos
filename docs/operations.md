# Packaging, deployment, migration and rollback

## Build and verify

From the repository root:

```bash
make verify
make wheel
python3.12 -m zipfile -l dist/aeos_kernel-0.3.0-py3-none-any.whl
```

`make verify` runs Ruff, strict mypy, the complete coverage-gated suite, and the pinned
MultiAgent source-compatibility suite. The wheel inspection must show `py.typed`, the schema
bundle and every named v1 entry schema.

When the live MultiAgent checkout has advanced beyond the provenance pin, verify against a
detached worktree at the pinned commit by setting `AEOS_MULTIAGENT_SOURCE_ROOT`. Never move or
rewind the live checkout merely to satisfy the compatibility test.

## Release

1. Require a clean AEOS tree and exact committed source-provenance pins.
2. Run `make verify` on a quiet machine.
3. Build the wheel and record its SHA-256, Git commit, Python version, test count and coverage.
4. Install the exact wheel into the consuming repository's locked dependency process.
5. Keep the relevant integration writer/refresh switch off.
6. Run import, schema-load and read-only packet/recommendation smokes.
7. Run the consuming repository's unit, integration, architecture and browser gates.
8. Apply the host-owned migration with its normal backup and downgrade proof.
9. Enable one internal test subject, verify its decision, attestation, effect and receipt.
10. Enable the bounded production cohort and monitor typed failures/restarts.

No AEOS public network listener or DNS record is part of the 0.3 release line. Its Memgraph
dependency is private and worker-facing only.

## Memgraph project fleet

One project graph is one endpoint, one storage directory or volume, one access identity and one
backup stream. Never place two projects in one Community database and call a `project_id` filter
the isolation boundary. Multiple project instances may share a sufficiently sized host while
they are small, but their ports, systemd units, data paths, credentials and recovery artifacts
remain separate. Moving one project to its own host must require only endpoint configuration.

Required host configuration is supplied by the consuming worker's secret/configuration system,
never by repository files:

- `AEOS_GRAPH_ENABLED` — off by default and changed through the host's governed deployment path;
- `AEOS_GRAPH_HOST` and `AEOS_GRAPH_PORT` — one private project endpoint;
- `AEOS_GRAPH_USERNAME` and `AEOS_GRAPH_PASSWORD` — that endpoint's access identity;
- `AEOS_GRAPH_PROJECT_ID`, `AEOS_GRAPH_VERTICAL_ID`, `AEOS_GRAPH_TENANT_ID` — exact bound scope;
- `AEOS_GRAPH_SSLMODE` — required when the deployment termination model uses Bolt TLS.

Production instances use transactional storage, WAL, periodic snapshots, synchronous-enough WAL
flush for the agreed recovery point, snapshot retention, telemetry policy declared explicitly,
and an encrypted volume. Bind Bolt to a private address. Permit inbound Bolt only from the named
worker security group; do not expose Memgraph Lab, Bolt or a graph HTTP/MCP service publicly.

Before activation:

1. Prove endpoint identity and version from the intended worker network identity.
2. Run `MemgraphProjectStore.ensure_schema()` and record every resulting constraint/index.
3. Run the real integration suite against a disposable sibling endpoint, never production.
4. Publish Wema generation 1 from exact source pins; record snapshot and vocabulary digests.
5. Read the current snapshot and one known neighborhood through the fixed-query adapter.
6. Prove a different project-bound store cannot observe the Wema snapshot.
7. Stop or block the graph endpoint and prove Wema public/auth/order/effect paths remain healthy
   while graph-dependent decision refresh defers without a stale fallback.
8. Create a database snapshot, restore it into a separate endpoint, and compare current generation
   and snapshot digest before enabling scheduled refresh.

Monitor process health/restarts, resident memory and memory headroom, data-volume usage, WAL and
snapshot age, backup age, current-generation age, publish duration/failures, query duration and
worker deferrals. Alerts must fire before memory or disk exhaustion and when graph freshness
exceeds the vertical's declared decision window.

Graph credential rotation is project-local: create and activate the replacement access identity,
update the worker secret, reload the worker, prove a fixed read and publish on a disposable
generation, then revoke the old identity. Rotation must not require changing any other project.

### Graph rollback and recovery

Disable `AEOS_GRAPH_ENABLED` first. This stops new projection and graph-dependent decision refresh
without removing canonical data or reversing an effect. To roll back content, point the project
anchor to a retained complete generation in one transaction only after its source pins and digest
are revalidated. To recover infrastructure, restore the latest snapshot plus WAL into a new
private endpoint, compare the stored current digest to the release record, update the worker
secret/configuration, and re-enable. Never prune the last known-good generation or backup as part
of the same release that creates its successor.

## Rollback

1. Disable the consuming host's AEOS writer and refresh switches.
2. Stop new effect claims; allow an in-flight local transaction to finish or roll back.
3. Reconcile any indeterminate outward operation with the affected system before retry.
4. Restore the previous pinned AEOS wheel or remove the dependency if this was first adoption.
5. Keep append-only decisions, attestations, effects and outcomes readable; do not delete
   evidence merely to make the older application unaware of it.
6. Use the host's compensation operation for an already applied effect. Package rollback does
   not reverse a published, sent, spent, deleted or otherwise external event.
7. Run the host's rollback smoke and record the surviving version and data readability.

## Migration rule

AEOS publishes schemas and reference contracts only. Each host owns its database migrations,
backups, locking, retention, access control and downgrade. A migration must be additive for the
first release. Destructive consolidation waits until the old reader has been absent for one
verified release and recovery evidence proves the history remains available.

## Incident posture

- A malformed or stale packet produces no recommendation effect.
- A model/provider outage preserves deterministic paths and produces a typed refusal where
  judgment is required.
- A persistence outage leaves host data unchanged and the item retryable.
- A mismatch after authorization but before execution produces no effect.
- An indeterminate effect is reconciled, never blindly replayed.
- Repeated failures wake the host's named operator through its existing action/incident path;
  AEOS does not create a second operational queue.
