# Changelog

## Unreleased — policy-lane candidate on 0.8.2, 2026-09-27

- Add the canonical product policy manifest (PB-195): one strict parser, closed schema,
  seventeen authority sections, canonical bytes and digest vectors, exact service grants and
  reader compatibility. The legacy `ProductManifest` is reached through an adapter that adds
  no value.
- Add the paid-term fence with one shared normalizer, bounded URL decoding, register
  validation and the eight flag rows. Results carry reason codes and digests only.
- Authorize policy commands through `resolve_authority` with exact grants; absent, stale,
  revoked, conflicting and wrong-class grants refuse.
- Keep a decimal-string coverage minimum as a real release bar, and block when the minimum
  cannot be read instead of dropping the check.
- Review round 1: split claim templates and FCRA posture into a product/legal section; require
  an authority class for every command except `propose_manifest`, whose proposal approves
  nothing, including revocation and the new `withdraw_latest_service_grant_set`; accept a register only as its own signed bytes named by
  the manifest, including an approved empty register; decode scheme-less provider URLs and
  percent-encoded provider text; refuse an unparseable URL without quoting it; compare the
  coverage minimum exactly.
- Review round 2: a grant-withdrawing revocation needs both the whole-manifest grant and the
  security/role withdrawal grant; `evaluate_paid_fence` takes the typed manifest and reads its
  flags, register bindings and forbidden phrases only from it, refusing a manifest that
  disagrees with its own bytes; provider URLs inside brackets or quotes, URLs encoded whole,
  and mapping keys are inspected; no refusal chains an exception that quotes the input.
- Review round 3: a punycode name part is read as its Unicode name wherever it sits in provider
  text (`URL:https://xn--…`, `ref=xn--…`); a URL that starts inside a token is parsed as a URL;
  a punycode name part that cannot be decoded refuses as unstable without quoting it. Review round 4: provider text is also inspected in its NFKC form, so a full-width punycode name part or URL is read exactly like its ASCII twin. Review round 5: each percent-decoding round starts from the NFKC form, so a full-width percent escape is decoded like its ASCII twin. Review round 6: the NFKC step never counts as one of the four decoding rounds.
- The distribution version stays 0.8.2 in this lane. Root chooses and publishes the reviewed
  version and updates the Wema pin.

## 0.8.2 — candidate, 2026-09-23

- Give an enforcing refusal precedence over an approval request, then a hold (PB-99).
  Approval resumes the previewed payload, so it must not mask a refusal that it will not re-run.
- Retain all rule reasons, observing results, gaps, non-applicable results and family defaults.
  The host still checks every enforcing result before an effect; no new severity API is added.
- Preserve 0.8.1 opaque support-reference validation. Package publication and Wema deployment
  require their separate verified artifact and consumer evidence.

## 0.8.1 — candidate, 2026-09-14

- Accept exact namespaced canonical UUID support references even when a UUID group contains
  only decimal digits. These native opaque identities no longer trigger the customer-number
  detector used for shared text.
- Limit the exception to the support-reference field and its bounded ASCII grammar. Malformed,
  embedded, suffixed and sensitive references refuse; general shared-text and summary privacy
  checks remain unchanged. References are never normalized or encoded.
- Preserve native row identity and source digests through the Wema observation adapter.
  Matching reference syntax does not establish row existence or grant source authority.
- Keep runtime, distribution and current specification identity at 0.8.1. The patch changes no
  interchange schema, host authority, provider effect or activation setting; normal consuming
  application installation and release verification remain separate.

## 0.8.0 — candidate, 2026-09-14

- Add the reusable business control plane: product and module registration, bounded moves and
  approvals, gates and stop rules, scheduled admission, release-readiness evidence, operational
  rails, and privacy-bound improvement records.
- Bind those contracts to a named Wema product projection and worker entry point while keeping
  Wema's native Desk, persistence, model gateway and effect authority in charge of product facts
  and outward actions.
- Keep incomplete coverage, missing validation, unregistered modules, absent rails and pending
  human decisions visible as blocking gaps. Package publication does not grant host activation
  or establish completion of a consuming product.
- Correct the runtime version to agree with 0.8.0 package metadata and check that agreement
  against the build configuration. Earlier local 0.8.0 wheels reported 0.7.2 at runtime.

## 0.7.2 — candidate, 2026-09-13

- Give Wema access resend its own human-attested compound operation, bound to the exact
  message, fulfilled order and host-computed current access source. Generic reply authority
  cannot authorize access recovery. The mailbox adapter advances to version 2; ordinary
  reply/refund operation shapes remain unchanged. This source contract still requires its
  Wema native execution and packaged consumer proof before release.

## 0.7.1 — candidate, 2026-09-05

- Retain validated model-call identities and safe structured outputs on refusal, including
  reverse-order disagreement and an invalid later choice. Refusal never becomes consensus or
  effect authority; Wema owns durable journaling and recovery.
- Add boundary witnesses for immutable retained state, malformed graph/review identities,
  current source and permission checks, incomplete model authority and unsupported receipts.
- Include the changelog, authoritative specification and provenance inventory in the wheel as
  well as source distributions. Preserve all historical v1 and current v2 schema resources.
- Keep the upstream compatibility pin and all outward-effect policies unchanged. Candidate
  packaging is not a Wema deployment or approval record.

## 0.7.0 — 2026-09-04

- Support bounded host-model choice within Wema's exact current graph candidate pool while
  retaining the compatible deterministic ranked-first adapter mode. The kernel enforces
  evidence citations, provider identity, cost and reverse-order consensus; the CLI remains
  host-owned and effects remain separately authorized.

## 0.6.0 — 2026-09-04

- Add the Wema mailbox-triage adapter `wema.mail_triage@1`: closed projections of a mailbox's
  registry policy, a routed message and a matched order; one entailed candidate from the
  registry's recommendation and its facts; outward send and refund effects named for the host
  to register and a person to attest; one operator-queue card per message with the decision
  identity in its evidence and no message text anywhere.

## 0.5.0 — 2026-09-04

- Extract the WLG text-quality lane: `aeos_kernel.rubric` (rubric contract, status lifecycle,
  escalation thresholds, calibration promotion), `aeos_kernel.text_gate` (deterministic
  sanitize and format gate), `aeos_kernel.scoring` (reviewer prompt and verdict parser without a
  provider) and `aeos_kernel.field_hooks` (instance-owned per-field hook registry that fails
  closed on a raising hook).
- Advance the certified MultiAgentCommunication source pin to `d99002a19` after proving the nine
  decision files byte-identical, and pin the four extracted modules with known-answer
  compatibility tests run against a clean detached checkout.
- First named consumer: Wema mailbox management (support-reply rubrics, voice gate and the
  founder-tap calibration signal).

## 0.4.1 — 2026-09-03

- Advance the certified MultiAgentCommunication source pin after proving the nine decision and
  known-answer files are byte-identical and rerunning the full compatibility suite in a clean
  detached checkout.

## 0.4.0 — 2026-09-03

- Add a Wema daily-growth adapter that consumes the complete safe Reach route portfolio,
  aggregate outcomes, independent research-source states, and a pinned local graph snapshot.
- Select exactly one governed route while retaining cited alternatives and projecting advice
  into Wema's existing operator queue without contact, publication, approval, spend, or effects.

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
