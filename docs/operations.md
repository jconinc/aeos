# Packaging, deployment, migration and rollback

## Build and verify

From the repository root:

```bash
make verify
make wheel
python3.12 -m zipfile -l dist/aeos_kernel-0.2.2-py3-none-any.whl
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

No AEOS network listener, DNS record, security group, credential, database or graph service is
part of the 0.2 release line.

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
