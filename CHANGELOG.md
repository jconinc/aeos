# Changelog

## 0.3.1 — 2026-09-03

- Bound each project's online graph history to the current immutable generation and its two
  immediate predecessors after an atomic publication, with real Memgraph evidence through five
  generations.
- Keep longer recovery in transaction-consistent daily dumps so graph growth follows useful
  current data instead of accumulating complete copies forever.

## 0.3.0 — 2026-09-03

- Add strict project-neutral graph vocabulary, node, relationship and immutable snapshot
  contracts with a published JSON Schema and privacy-classification boundary.
- Add a project-bound Memgraph adapter with fixed Cypher, per-object scope stamping, atomic
  current-generation publication, deterministic idempotent receipts and bounded neighborhood
  reads.
- Establish one private Memgraph endpoint, encrypted data volume and access identity per project
  as the production isolation model; Wema is the first project and the graph remains a derived
  advisory read model.
- Add opt-in real Memgraph evidence for schema creation, two-project isolation, replay,
  traversal and concurrent-writer conflict behavior.

## 0.2.2 — 2026-09-03

- Add a model-forbidden Wema deployment-review adapter that turns exact release-bound closed
  choices and bounded notes into one deterministic advisory follow-up in the existing Desk queue.
- Keep reviewer identity and review text out of the queue projection; retain only references,
  counts, AEOS decision identity, and canonical digests.

## 0.2.0 — 2026-09-02

- Publish v2 schemas and a deliberately breaking fail-closed Python contract while retaining the
  v1 schema resources for historical readers.
- Bind effect authorization to the exact current packet, recommendation, candidate-set,
  projection, subject, authority bundle, policy, source pins, adapter, operation version and
  contract, actor capacity, attestation, host controls, cost, and fanout ceiling.
- Require external affected-system confirmation for registered outward operations and add exact
  receipt verification.
- Deep-freeze nested public JSON values and reject unknown authority scopes, selectors, layers,
  statuses, privacy uses, model identities, contexts, generation settings, and malformed or
  noncanonical outcome evidence.
- Record model prompt/context/provider/model/generation identity, cost and token usage under the
  host-approved call reservation.
- Strengthen append-only lifecycle evidence, monotonic time, receipt requirements, drift reopen,
  and historical reference preservation.
- Add read-only shadow parity against four actual pinned `test_canon_decision.py` fixture classes;
  graph storage, services, scheduling, static gates, transactions and effect execution remain in
  MultiAgentCommunication.

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
