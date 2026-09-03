# AEOS provenance and extraction inventory

**Inventory version:** 4
**Recorded:** 3 September 2026

## Source snapshots

| Source | Committed revision inspected | State qualification |
| --- | --- | --- |
| MultiAgentCommunication | `f8b76c9930e590983d1e0c5e232bd8817191db7f` | Working tree had extensive unrelated modifications. Only committed bytes at this revision are extraction authority until a later revision is explicitly pinned. |
| Wema | `76e7c0f4fb1df28a9b77a02e1743eec83cd5a249` | Clean `build/p0` tree when inventoried. Wema is the first consumer, not the source of generic kernel behavior. |

MultiAgentCommunication declares its Python package MIT in `pyproject.toml`. Extracted behavior
keeps source attribution in this inventory and in module headers. No credential, environment
file, project data, graph data, customer data, or generated operational artifact is copied.

## Classification

- **Extract:** behavior is project-neutral and should retain compatible semantics.
- **Invert:** behavior is reusable after replacing a WLG dependency with a typed port.
- **Adapter:** behavior remains source-system-specific and is mapped at the boundary.
- **Contract only:** retain the shape/invariant, not the implementation.
- **Exclude:** do not bring this machinery into AEOS.
- **New:** required by a named production consumer and not present generically in the source.

## MultiAgentCommunication inventory

| Source path | Behavior/evidence | Classification | AEOS destination or decision |
| --- | --- | --- | --- |
| `claude_coord/wlg/decision_engine/contracts.py` | Authority and lifecycle enums; stable request identity; serializable decision-type contract | Extract + adapt | Preserve authority/lifecycle values. Replace validator-specific request fields with generic subject/evidence identity in the public contract; WLG request shape remains in its adapter. Tighten fingerprint serialization to strict JSON. |
| `decision_engine/authority.py` | Immutable authority records, selector matching/specificity, layer precedence, conflict refusal | Extract | `aeos_kernel.authority`; selectors become extensible registered kinds while preserving WLG selector behavior in compatibility tests. |
| `decision_engine/authority_importer.py` | YAML/Markdown authority import with per-source provenance | Extract after hardening | Optional file-authority adapter. Import is not runtime authority until validated and activated. |
| `decision_engine/authority_store.py` | Strict record decoding plus graph-driver queries/upserts | Adapter | Decoding invariants may extract; driver queries remain MultiAgent-specific behind an authority repository port. |
| `decision_engine/boundaries.py` | Field-to-human-boundary registry | Extract concept | Generalize from graph fields to effect parameters/operations. Default product examples remain in WLG adapter data. |
| `decision_engine/candidate_resolvers.py` | Evidence-ranked unique selection; ambiguity, placeholder and name-only refusal | Extract | Generic candidate-resolution utility. Route/screen/entity/endpoint helpers remain WLG adapter functions. |
| `decision_engine/canon_decision.py` | Canon/evidence hashing, pin verification, eligibility, entailed auto-selection, bounded model selection, citation validation, reverse-order consensus, fail-closed escalations and decision record | Invert | This is the primary proven decision compiler. Replace `decision_planner` prompt/model shapes with AEOS's live model port and replace repair operations with strict host effect contracts. Envelope and pipeline runner remain WLG adapter concerns. |
| `decision_engine/coverage.py` | Required standard-category coverage and empty-set gaps | Extract concept | Generic registered-policy coverage; WLG category vocabulary remains adapter data. |
| `decision_engine/decision_types.py` | Closed registered decision types and duplicate refusal | Extract | Instance-owned registry; avoid mutable process-global test leakage. |
| `decision_engine/mutation.py` | Allowed write surfaces and human-boundary checks | Contract only + adapter | AEOS uses effect plans and host authorizers. WLG graph mutation ops remain adapter-owned. |
| `decision_engine/predicates.py` | Registered pure predicates and duplicate refusal | Extract utility | No WLG/product predicates in the generic default registry. |
| `decision_engine/records.py` | Stable decision record/draft identity | Extract concept | Superseded by the more general append-only `DecisionRecord`; compatibility mapper retains source shape. |
| `decision_engine/requests.py` | Validator-rule registry and gap-to-request mapping | Adapter | Entire vocabulary and validator semantics remain WLG-specific. |
| `decision_engine/requirement_corpus_pin.py` | Source corpus pin verification | Invert | Implement as generic source/currency verifier; retain WLG validation imports in adapter. |
| `decision_engine/standards.py` | Strict standard pack parsing, contexts, defaults and predicates | Extract | Rename graph obligations to generic obligations in the kernel; compatibility parser supports original packs. |
| `claude_coord/wlg/requirement_decision_proposal.py` | Proposal/review/correction/admission workflow with durable receipts | Contract only + adapter | Preserve bounded propose/review/correct/admit behavior and receipts; WLG requirement bodies, AC, transaction manager and judgment lane remain WLG-owned. |
| `pipeline/decision_planner*` | Prompt construction, output normalization, model choice types | Invert | Host-neutral `ModelGateway` request/result contract. MultiAgent and Wema use their existing provider layers. |
| `fix/repair_mutation_plan.py` | Typed graph ops, static patch gate and lowering | Adapter | WLG execution and static-gate adapter. Never make graph ops AEOS's business vocabulary. |
| `execution_receipt.py` and graph transaction machinery | Durable commit receipts but graph/temporal-driver coupled | Contract only | Extract receipt invariants and expected-postimage semantics. Exclude implementation and graph temporal types. |
| WLG task envelopes, claims, pipeline runners and graph stores | Scheduling, unit ownership, graph persistence, transaction chokepoint | Adapter/exclude | Remain MultiAgent application machinery. AEOS defines strict interchange contracts; the compatibility adapter maps to existing implementations without a speculative repository/executor abstraction. |
| FastAPI coordination/context service | Local personal service using `X-Agent-Id`, without production tenancy/auth boundary | Exclude | Must never be a Wema production dependency. No AEOS network service in the first release. |
| `docs/sync_review/graph_io.py` | Project-scoped graph I/O, deterministic IDs, transactional mode, snapshot/WAL awareness and an expiring project writer lock | Extract operating law; do not copy | AEOS uses immutable generations, one transactionally flipped current pointer and a project-bound adapter. It deliberately excludes analytical/turbo mode because advisory refresh durability matters more than bulk-import speed. |
| `claude_coord/wlg/graph/constraints.py` | Query-driven Memgraph indexes, single-property unique identities and project scope on every mutable graph identity | Extract operating law; adapt schema | AEOS uses deterministic single-property keys, fixed project predicates and only indexes justified by its small query registry. WLG labels and its large index surface remain upstream. |

### Source test evidence to preserve

| Test source | Proven classes selected for compatibility |
| --- | --- |
| `claude_coord/tests/test_wlg_decision_engine.py` | standard-pack loading/coverage, stable request identity, typed registries and boundary refusal |
| `claude_coord/tests/test_canon_decision.py` | entailed selection, cardinality-not-entailment, evidence/citation/pin/identity validation, authority precedence/conflict, bounded model choice, order consensus, low confidence, cross-project/stale refusal, static-gate refusal and strict envelopes |
| `claude_coord/tests/test_canon_decision_pipeline.py` | real worker commit/readback, provider trace, no-mutation escalation, rollback, durable receipt, replay-zero, source-head and stale-revision refusal |
| `claude_coord/tests/test_intent_authority_lift_canon_decision.py` | exact plan compilation, cross-project refusal, receipt-bound retraction, bounded candidate enumeration and red plants |

The compatibility suite imports the committed source modules and selected committed fixture
helpers from the pinned checkout. It vendors no product fixture, operational database, project
graph, provider output, or mutable test artifact.

## Wema consumer inventory

| Wema source | Existing responsibility to reuse | AEOS integration |
| --- | --- | --- |
| `apps/api/wema_api/actions/selector.py` | Canonical founder Today selection, filtering, ranking, deduplication and five-card cap | Recommendation projection creates/updates an existing `OwnedAction`; AEOS creates no queue. |
| `apps/api/wema_api/routers/desk_actions.py` | Authenticated founder/operator action reads and claim/resolve/snooze/dismiss operations | Desk interaction stays here. Add only registered AEOS action/detail and attestation mappings required by the slice. |
| `apps/desk/src/screens/TodayScreen.tsx` and `Today.tsx` | Calm Today rendering, guidance and commands | Reuse presentation. Do not call AEOS from the browser. |
| `apps/api/wema_api/review.py` | Digest-bound meaningful review projection and recorded review events | Reuse digest/projection and anomaly patterns; generalize only where article decision attestation requires it. |
| `apps/api/wema_api/authority_decisions.py` and migration `0059` | Capacity-tagged founder/clinical authority decisions | Reuse or generalize storage for AEOS attestation; no parallel approval database. |
| `apps/desk/src/screens/articleEditor/` and article API/services | Real plain-language editing, preview, save, publish and revision workflow | Today recommendation deep-links here. AEOS does not build an editor. |
| `apps/worker/wema_worker/guidance_refresh.py` and guidance handlers | Reads Wema evidence and computes current commercial focus | First evidence/refresh host; adapt its safe projection rather than adding a second scheduler. |
| `apps/api/wema_api/guidance.py` | Safe guidance projected on Today actions | Recommendation explanation mapping. |
| `packages/model-gateway` | Provider-neutral model access, structured context, schema validation, lint, spend ceiling and fail-closed provider controls | Implements AEOS `ModelGateway`; AEOS contains no provider credentials or duplicate provider client. |
| Wema worker/domain/outbox/idempotency/kill-switch infrastructure | Authorized operations and operational recovery | Implements effect authorizer/executor and receipts. |
| Wema analytics/event/market-policy registries | Permitted aggregate observations and suppression/evidence floors | Implements outcome source. AEOS never silently activates collection. |
| Wema public review checklist and saved-feedback projection | Release-bound closed choices and bounded notes; explicitly advisory rather than approval | `wema.review@1` consumes the minimized projection without reviewer identity or model use and emits at most one operator follow-up. |

## Genuinely new AEOS behavior

| New contract | Why it is necessary | First live consumer |
| --- | --- | --- |
| Generic `DecisionSubject` | Existing public request shape assumes a validator row and `row_absent` success | Wema article revision; WLG unit mapper |
| Generic effect plan/authorizer/receipt contracts | Existing compiler emits graph repair ops | Wema registered article operation; WLG repair-op adapter |
| Human attestation port | Existing WLG engine escalates but does not provide Wema's in-product founder response contract | Wema authenticated Desk/API review |
| Outcome observation port | Existing graph verifier proves structural postconditions, not business outcomes over time | Wema policy-permitted article analytics |
| Privacy/use metadata on evidence | WLG project scoping alone is insufficient for customer-bearing production systems | Wema article evidence adapter |
| Host-neutral tenant boundary | WLG's current service is personal/local | Wema API/worker |
| Immutable project graph snapshot | Growing cross-content and cross-playbook relationships need a reproducible derived read model without moving authority or effects into a graph | Wema content/advisory projection |
| Project-bound Memgraph adapter | Community single-database filtering is not sufficient isolation for a reusable multi-project product | One isolated Wema endpoint; later projects receive separate endpoints and volumes |
| Generic AWS project-graph stack | A reusable engine needs repeatable project isolation, recovery and alarms rather than a hand-built Wema host | Wema production graph; future projects instantiate the same parameterized stack |
| Local project service and subscription-assisted runner boundary | The first operator already has capable local hardware and interactive agent subscriptions; recurring infrastructure/model spend is unjustified before measured return | Wema's loopback-only AEOS graph and local decision runs |

## Explicitly unresolved at inventory version 2

- The exact committed MultiAgent revision from which extraction will be copied may advance; every
  change must update the pin and diff the affected source modules/tests.
- A real analytics policy/profile must be active before outcome-driven optimization can claim
  production evidence. `insufficient_evidence` remains a valid first outcome.
- The Wema founder decision-engine proposal and canon are proposal/ratification-dependent in Wema;
  AEOS may implement neutral capability without claiming those Wema authorities are approved.

## Extraction evidence at AEOS 0.2.1

| Claim | Evidence |
| --- | --- |
| Source fingerprint and enum compatibility | `tests/test_multiagent_source_compatibility.py::test_source_enum_and_fingerprint_values_are_preserved` against the pinned checkout |
| Unique candidate resolution compatibility | Source-comparison test plus AEOS ambiguity, cross-domain, placeholder and name-only red plants |
| WLG selector compatibility | Source-comparison test for path, field, lifecycle and wildcard rule selectors |
| Pinned canon-decision shadow parity | Thirteen actual committed `test_canon_decision.py` fixture classes run through `tests/test_multiagent_shadow_parity.py`, comparing decision/refusal, citations, escalation, typed effect and receipt expectation |
| Authority parity | Actual source `AuthorityRecord` precedence/conflict known answers plus source-tier precedence and same-tier conflict fixtures |
| Static-gate parity | Actual source static gate accepts a digest-bound candidate; a source-rejected candidate cannot enter the AEOS candidate set; the host must re-gate before execution |
| Lifecycle, drift and receipt provenance | Exact committed pipeline/retraction fixture functions are pinned by name; generic CAS, replay, stale/drift, receipt and compensation invariants run in AEOS while graph/database/task machinery remains excluded |
| Project-neutral decision compiler | Deterministic, cardinality-not-entailment, authority precedence, citation, cross-scope, stale, model-consensus, budget and boundary tests in `test_engine.py` and `test_contract_red_plants.py` |
| Host-owned effect boundary | Registered-operation, exact attestation, capacity, digest, kill-switch, provider, parameter, boundary and cost red plants |
| Wema consumer shape | Article packet, immutable-revision effect and exact `OwnedAction` column tests in `test_adapters.py` |
| Published package contract | V1 historical and v2 current JSON Schema resources, schema strictness tests, strict mypy, wheel content inspection and `py.typed` marker |

Release evidence is recorded only after the complete quiet `make verify`, reproducible wheel
inspection and exact consumer repin. This inventory does not claim MultiAgent graph transaction
adoption; Wema persistence and deployment evidence remains owned and verified in Wema.

The 0.2.1 pre-release verification ran 88 complete kernel tests at 91.13% combined line/branch
coverage, plus 16 pinned-source compatibility tests; Ruff and strict mypy were clean.

## Additive evidence at AEOS 0.2.2

The Wema deployment-review adapter is new host-consumer behavior, not an extraction from
MultiAgentCommunication. Adapter tests bind its exact release/inventory/payload identities, prove
that reviewer identity is absent, prove that public notes are ineligible for model use, and prove
that attention yields one advisory `OwnedAction` projection while an all-clear yields none.

## Additive evidence at AEOS 0.3.0

The graph foundation adapts proven operating laws from the pinned MultiAgent source rather than
copying its product graph. AEOS owns a much smaller project-neutral contract: closed vocabularies,
public/internal-only nodes, immutable source-pinned generations and fixed reads. WLG shape kinds,
queries, repair mutations, locks, validators and graph data remain upstream.

`tests/test_graph.py` proves the contract and fail-closed adapter behavior without a database.
`tests/test_memgraph_integration.py` is the opt-in affected-system witness: on an isolated
Memgraph 3.7.2 instance it creates the real schema, publishes two scoped projects, proves
idempotent replay and neighborhood reads, and forces two same-generation writers to establish
that exactly one transaction commits. Release evidence must name the Memgraph version and port or
endpoint class used; a mocked green never substitutes for this suite.

## Additive evidence at AEOS 0.3.1

Online snapshot history is bounded to the current graph generation and its two immediate
predecessors. The real Memgraph integration witness publishes through generation five and proves
that generations one and two, including their contained entities and relationships, are removed
while generations three through five remain. Daily transaction-consistent dumps retain the
separate disaster-recovery boundary without turning every immutable online generation into
permanent storage cost.
