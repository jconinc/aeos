# Changelog

## 0.1.1 — 2026-09-01

- Remove speculative repository, source, executor, and outcome protocols that had no live
  consumer. Hosts continue to implement those boundaries through the strict data contracts and
  their existing transaction/domain services; the runtime port module now contains only the
  verifier, model gateway, and clock that the engine consumes.
- Correct the Wema persistence and concurrent-answer integration contract to match the production
  host: append-only `aeos_decision_events`, subject locking, semantic replay, and conflict refusal.

## 0.1.0 — 2026-09-01

- Establish the authoritative AEOS specification and extraction provenance.
- Extract strict identity, authority resolution, evidence validation, unique candidate
  resolution, entailed selection, bounded model consensus, lifecycle, drift, effect
  authorization, receipt, and outcome contracts.
- Publish the v1 Python API, type marker, and JSON Schema bundle.
- Add MultiAgentCommunication compatibility and Wema article-decision adapters.
- Prove the kernel with deterministic, adversarial, drift, schema, source-compatibility,
  and adapter tests.
