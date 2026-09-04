# AEOS — adaptive evidence operating system

**Version:** 0.6.0
**Date:** 4 September 2026
**Status:** authoritative implementation specification for this repository  
**First vertical:** Wema  
**Proven source:** MultiAgentCommunication decision machinery at
`d99002a1903a56b5601d7ec3455e5dfa43028935`

## 1. Mission

AEOS turns trustworthy evidence and declared authority into the smallest useful next
decision, carries that decision to the right human only when human judgment is actually
required, executes only an explicitly authorized host operation, and learns from a
durable outcome receipt.

It exists to help a person with strong judgment but little operational experience run a
business without making her become a site administrator, analyst, campaign operator,
sales chaser, or AI supervisor. The system prepares and performs repeatable work. The
human contributes truth, taste, voice, relationship judgment, and consequential approval.

AEOS is a reusable kernel, not a second application. A vertical supplies its facts,
authority, user interface, effect implementations, and outcome measurements through
typed adapters.

## 2. Governing principles

1. **Evidence before recommendation.** Every material claim cites an immutable evidence
   item whose bytes, scope, currency, and provenance can be verified.
2. **Authority before effect.** A recommendation is not permission. An effect runs only
   when the registered authority policy and any required human attestation both permit it.
3. **Bounded choice.** Deterministic code supplies the candidate set. A model may rank or
   explain eligible candidates; it may not invent a candidate, fact, authority, operation,
   recipient, audience, price, claim, or scope.
4. **Fail closed.** Missing, conflicting, stale, malformed, cross-tenant, over-budget, or
   unverified inputs produce a typed refusal or human question, never a guess.
5. **Digest-bound decisions.** A decision binds the exact evidence, subject revision,
   authority bundle, policy version, candidate set, and presented projection.
6. **Host-owned mutation.** The kernel emits a typed effect request. Only a vertical-owned
   executor may translate it into a database, provider, publication, outreach, or other
   external operation.
7. **Receipts over recollection.** Applying, verifying, closing, reopening, superseding,
   refusing, and failing are durable states supported by receipts.
8. **Drift reopens exactly what changed.** Material evidence, canon, policy, subject, or
   expected-postimage drift makes the affected decision stale; unrelated change does not.
9. **Privacy minimization.** Adapters send the minimum decision-relevant projection. Raw
   customer, caregiver, patient, credential, and private relationship data do not enter a
   shared graph or model prompt merely because the source system contains them.
10. **One human surface per vertical.** AEOS does not create a parallel task manager. Wema
    uses its existing five-card Today queue and authenticated Desk.
11. **Simple above, leveraged below.** The person sees one recommendation, ordinary-English
    reasons, the prepared work, its boundary, and a few meaningful responses—not internal
    scores, pipelines, schemas, graph terms, or software jargon.
12. **No abstraction without a live consumer.** The first consumers are the
    MultiAgentCommunication compatibility adapter and Wema article-decision adapter.

## 3. Scope and non-goals

AEOS provides:

- stable identities and canonical fingerprints;
- typed evidence, subject, authority, candidate, recommendation, attestation, effect,
  receipt, outcome, and decision-record contracts;
- source and currency validation;
- authority resolution and intensity policies;
- deterministic candidate eligibility and unique entailment;
- a bounded model-selection port with identity, citation, consensus, and spending checks;
- a decision lifecycle with idempotency, concurrency, supersession, drift, and reopening;
- host-neutral strict contracts, adapters, and only the runtime ports with live consumers;
- published JSON Schemas for interchange;
- compatibility and vertical adapters.

AEOS does not provide:

- an end-user UI, CRM, CMS, analytics collector, scheduler, mailer, social publisher, or
  payment system;
- a second model gateway when the host already has one;
- a graph as canonical authority, evidence storage, effect executor, or customer-data store;
- product-specific business facts, copy, playbooks, routes, database models, or effects;
- authority for a model to approve its own output;
- autonomous legal, clinical, privacy, commerce, outreach, spend, publish, delete, or
  irreversible decisions unless a host policy explicitly grants a narrow deterministic
  playbook that authority;
- a production dependency on MultiAgentCommunication's localhost coordination service;
- artificial translation of business decisions into validator rows or graph mutations.

## 4. System boundary

```text
Vertical facts, metrics, canon and policies
                 |
       vertical evidence adapter
                 v
        immutable DecisionPacket
                 |
       candidate + authority gates
                 |
      deterministic decision OR bounded ModelGateway choice
                 v
       explainable Recommendation
                 |
       vertical recommendation store
                 |
        vertical human surface
                 |
         HumanAttestation
                 v
          effect authorizer
                 |
        vertical effect executor
                 v
        EffectReceipt + outcomes
                 |
        vertical outcome adapter
                 v
          retain / revise / close / reopen
```

The kernel may run in a vertical worker process. A public AEOS network service remains deferred
until a second production vertical demonstrates that a process boundary is worth its
authentication, authorization, tenancy, deployment, availability, and incident-response cost.
The project-bound graph adapter introduced in 0.3 is a private derived-data dependency used from
that worker boundary; it is not an AEOS API and does not move effects out of the host.

## 5. Core vocabulary and contracts

All public contracts are strict, versioned, JSON-serializable, and reject unknown fields at
interchange boundaries. Internal Python types are immutable where practical.

### 5.1 Identity and fingerprint

`stable_fingerprint(value)` is the lowercase SHA-256 of canonical strict JSON: sorted keys,
compact separators, UTF-8, finite JSON values only, and no fallback string coercion. IDs use a
stable namespace plus the complete input identity. Display abbreviations never confer authority.

### 5.2 DecisionSubject

A subject is the thing about which a decision is being made, without assuming it is a graph
shape or validator finding:

- `subject_id`, `subject_kind`, `vertical_id`, `tenant_id`;
- `revision` and `content_digest`;
- safe `attributes` projection;
- `source_refs` back to host-owned records;
- `privacy_classification` and `allowed_uses`.

The WLG adapter maps validator units or graph shapes to subjects. The Wema adapter maps an
article revision, promotion opportunity, lead follow-up, offer, or other registered business
object to a subject.

### 5.3 EvidenceItem and DecisionPacket

An evidence item includes:

- stable evidence identity and canonical digest;
- vertical, tenant, subject and revision scope;
- source tier and source reference;
- observed/retrieved time, expiry or currency trigger;
- privacy classification and permitted uses;
- structured payload;
- optional research verification receipt.

A packet binds one subject, all evidence, the authority/canon bundle fingerprint, policy
version, allowed action vocabulary, source-head pins, creation time, and packet digest. The
recommendation and effect authorization bind the complete candidate-set digest. Cross-tenant,
cross-subject, stale, expired, noncanonical, unpinned, or
disallowed-use evidence is ineligible.

### 5.4 Authority

The preserved authority levels are:

- `deterministic` — entailed by validated current evidence and registered rules;
- `standard_default` — a current applicable standard provides the bounded default;
- `agent_judgment` — a qualified model or agent may choose among eligible candidates;
- `human_required` — a named capacity must decide.

An authority record has an identity, scope selector, layer, status, value, source anchor,
version, priority, activation interval, and supersession link. Resolution chooses the highest
active applicable layer and most specific selector. Same-rank conflicting values return a typed
conflict. Absence returns a typed authority gap.

An authority policy also declares the required intensity tier and boundary tags. A model cannot
alter either value.

### 5.5 Candidate and recommendation

A candidate contains:

- an ID from a registered adapter-owned candidate vocabulary;
- a plain action and expected benefit;
- cited evidence IDs and a structured entailment or eligibility proof;
- a typed host effect template, or no effect for advice-only decisions;
- reversibility, fanout, cost ceiling, boundary tags, and expected postcondition;
- the human capacity required, if any.

Eligibility requires canonical in-scope citations, a supported source tier, an allowed action,
a complete effect shape, allowed boundary tags, and a host static-gate pass. Candidate count is
not entailment. Automatic selection occurs only when exactly one candidate is independently
validated as entailed.

A recommendation records the selected candidate or a typed refusal, its evidence citations,
ordinary-English explanation, rejected alternatives, uncertainties, boundary, expected result,
model-call identities where used, and the complete decision input digest.

### 5.6 Human attestation

An attestation binds:

- actor and current capacity;
- decision, recommendation, subject and presented-projection digests;
- decision revision;
- one response from the vertical's closed vocabulary;
- optional bounded note with the vertical's privacy warning;
- client idempotency key and decision time.

For Wema's first slice the projection is:

- **Use this** — authorize the exact prepared effect, subject to its intensity gates;
- **Change it** — record the note and create bounded revision work; do not execute;
- **Not now** — decline this revision and record a re-surface policy; do not execute;
- **Snooze** — defer until the selected permitted time; do not execute.

Transport replay and semantic decision identity are separate. Replaying one key with changed
bytes is a conflict. A new key containing the same semantic decision is a no-op. Concurrent
different decisions against one revision create a conflict; arrival order never decides.

### 5.7 Effect plan, authorization and receipt

An effect plan names a registered host operation and contains only validated parameters,
preconditions, expected postcondition, idempotency identity, boundary tags, cost ceiling,
reversibility, and compensation/rollback reference. Models may populate only schema-allowed
values and never name an unregistered operation.

The host authorizer rechecks current subject revision, policy, kill switches, actor capacity,
attestation, budget, credentials/provider readiness, and expected preimage immediately before
execution. The executor returns a durable receipt containing the host operation identity,
request digest, provider or database result identity, applied time, actual postimage or external
confirmation, status, and safe diagnostic. A local success response is insufficient for an
outward Tier 2 effect; confirmation must come from the affected system.

### 5.8 Outcome observation

Outcome evidence is host-supplied, aggregate where possible, policy-authorized, time-windowed,
and bound to the effect receipt. Lack of evidence remains `insufficient_evidence`; it is not
interpreted as success or failure. Distribution is not impact, activity is not a sale, and a
draft is not publication.

## 6. Decision intensity

Intensity is declared per decision class:

| Tier | Intended use | Required controls |
| --- | --- | --- |
| 0 | reversible advice or capture with low fanout | decision record, ledger, drift reopening |
| 1 | mechanically consumed internal change | Tier 0 + independent review/validation and expected postimage |
| 2 | outward, costly, legal, publish, delete, money, outreach, or irreversible effect | Tier 1 + exact human/capacity authority or previously granted bounded playbook, two-key where policy requires it, and external effect receipt |

Moving a decision class between tiers is a versioned authority-policy change, never a per-row
model judgment.

## 7. Lifecycle

The preserved decision statuses are:

`proposed -> accepted -> applying -> applied -> verified_closed`

Typed alternate states are `human_required`, `refused`, `apply_failed`, `verifier_failed`,
`stale`, and `superseded`.

Rules:

1. Every transition is compare-and-swap against the current decision revision.
2. `accepted` means authority is satisfied; it does not mean an effect occurred.
3. `applied` requires a valid effect receipt.
4. `verified_closed` requires the registered postcondition or outcome verifier.
5. Failure preserves the proposed work and diagnostic for retry or correction.
6. A retry must consume the previous typed failure and make a material corrective change.
7. Material input drift marks the decision `stale` and may create a new proposed revision.
8. A new accepted revision supersedes the old revision; history is append-only.
9. Advice-only decisions may close without an effect only when their registered postcondition
   explicitly permits that terminal.

## 8. Live ports and host contracts

The kernel defines only three runtime protocols, each consumed by the current decision engine:

- `TrustVerifier` verifies authority/source pins, current subject revision, and research receipts;
- `ModelGateway.choose(request) -> ModelDecision` is used only for bounded multi-candidate
  judgment; and
- `Clock.now()` makes currency and decision time deterministic in tests and host processes.

Everything else crosses the product boundary as a strict immutable data contract or an adapter
function: `DecisionPacket`, `Candidate`, `Recommendation`, `HumanAttestation`,
`AuthorizedEffect`, `EffectReceipt`, `OutcomeEvidence`, and `DecisionRecord`. Wema already has
transactional repositories, a worker, domain services, and outcome projections; wrapping those
in parallel AEOS repository/executor protocols would add abstractions with no live consumer.
MultiAgentCommunication likewise keeps its graph store, transaction gate, and receipt path.

A new source, repository, executor, or outcome protocol may be introduced only when a second real
consumer needs a shared callable interface. Expected refusals remain typed data, while host
infrastructure faults remain distinguishable from semantic refusals.

## 9. Model use

Deterministic eligibility and entailed selection run before any model call. A model receives
only the safe packet projection and eligible candidates. It must return a schema-valid candidate
ID or typed escalation, rationale, covering citations, uncertainty, and transport identity.

For multiple candidates the initial implementation preserves the proven reverse-order consensus
check. Both calls must choose the same candidate and pass the same validation. Provider/model,
prompt digest, generation-parameter digest, attempt number, token usage, and retained structured
output are recorded. Spend and call-count ceilings are supplied by the host. A missing identity,
invented candidate, invalid citation, low confidence, order-sensitive choice, malformed output,
or exceeded budget fails closed.

### 9.1 Text-quality lane

A host that lets a model write words (not choose a candidate) gates them with the rubric
machinery extracted from the WLG pipeline, in the pipeline's own order — T0 context → generate →
T3 deterministic gate → T2 score → bounded repair → ratchet → T1 human audit:

- `Rubric` declares, per target kind and field, `Subcriterion`s with exact scoring prompts and
  `blocking` flags, a `FormatSpec` the deterministic gate enforces, `ScoredExample`s, and
  `EscalationRules` (defaults: composite floor 0.67, spot-check 5 % with 10–50 samples, 100
  artifacts per family, pause at 0.08 must-pass / 0.15 overall disagreement).
- `text_gate.sanitize` and `t3_check` reject unsafe or off-format text at no model cost; a host
  registers its own per-field `FieldHookRegistry` hooks beside them, and a raising hook is a
  finding.
- `scoring.build_scoring_prompt` renders the reviewer prompt from a host context; the host calls
  its own gateway under `AuthorityPolicy` ceilings and hands the JSON reply to `parse_scores`:
  any blocking FAIL fails, the non-blocking pass rate must reach the floor, and a missing,
  unrecognized or malformed verdict abstains. Escalation on abstention is the host's decision
  under `EscalationRules.escalate_on_abstain`.
- `RubricStatus` is the ladder: `draft` scores in shadow, `calibrating` scores everything,
  `frozen` samples, `degraded` routes to T1. `CalibrationState.check_promotion` is the only way
  from calibrating to frozen; a host records promotion as an explicit, reviewable change, never
  as a computed side effect.

The lane never selects a candidate, authorizes an effect, or sends anything: a passing text is
one input to a candidate, and the human attestation and effect authorization of §5.6–5.7 stand
unchanged above it.

## 10. Drift and reopening

The input identity is the canonical digest of the subject revision, evidence items, canon bundle,
authority policy, candidate set, adapter version, and relevant host policy/config pins. The host
supplies current values; the kernel recomputes them.

Drift classes are typed:

- `subject_changed`
- `evidence_changed_or_expired`
- `canon_changed`
- `authority_changed`
- `candidate_contract_changed`
- `host_policy_changed`
- `expected_postimage_mismatch`
- `outcome_window_elapsed`

Only a material dependency reopens a decision. Reopening creates a new revision linked to the old
record and retains the prior explanation, attestation, effect receipt, and outcome evidence.

## 11. Security and privacy

- AEOS trusts no caller-supplied tenant, actor, capacity, market, or authority claim without host
  verification.
- Adapters enforce tenant and subject scope both when constructing and consuming packets.
- Unknown fields, actions, operations, boundary tags, schemas, and versions are rejected.
- Secrets and credentials never enter packets, prompts, decisions, logs, or repositories.
- Free text is untrusted and cannot create operations or authority. Vertical adapters bound,
  classify, and redact it before storage or model use.
- The kernel does not make raw cross-customer data available for optimization.
- External research is provisional until citation and currency verification succeeds.
- Effect execution rechecks kill switches and provider readiness at the last responsible moment.
- Logs and receipts use safe identifiers and diagnostics; hosts retain sensitive detail under
  their existing access and retention controls.

## 12. MultiAgentCommunication compatibility adapter

The adapter must preserve existing WLG behavior while moving reusable contracts behind AEOS:

- validator gap or decision unit -> `DecisionSubject`;
- WLG evidence/canon pins -> AEOS evidence and authority bundle;
- existing `DecisionCandidate` and `RepairOp` -> candidate and host effect template;
- AEOS recommendation -> existing `CanonDecision` record;
- WLG transaction gate -> vertical execution of an `AuthorizedEffect` contract;
- WLG durable receipt -> AEOS effect receipt.

Graph stores, graph queries, validator row keys, `row_absent`, repair ops, task envelopes, pipeline
claims, and WLG transaction implementations remain in this adapter. Compatibility is proven by
running selected existing known-answer and red-plant tests against the adapter, not by matching
class names alone.

Extraction is additive to MultiAgentCommunication. Its dirty working tree is never used as an
implicit source snapshot; the provenance inventory pins committed bytes or records an explicit
later source commit.

## 13. Wema adapter and first production slice

### 13.1 Ownership

AEOS runs inside or beside the Wema worker through a pinned Python dependency. Wema remains the
system of record and owns authentication, authorization, sessions, CSRF, database transactions,
idempotency, model provider access, analytics policy, Desk presentation, domain operations,
outbox, provider calls, and operational recovery.

The Desk never acts as the evidence API. It displays Wema's projection and posts the founder's
answer to the authenticated Wema API.

### 13.2 Article evidence packet v1

Wema supplies only registered, policy-permitted fields needed for the decision, including where
available:

- article and revision IDs, state, digest, title, summary, question/intent and safe body-quality
  features;
- editor SEO/AEO/accessibility/claim-analysis results with their rule versions;
- publication and update dates;
- aggregate discovery, engagement, referral, share-kit, subscription or conversion observations
  that Wema's active analytics policy permits;
- current content slot, audience, voice/copy doctrine and commercial guidance authority;
- internal-link inventory, source/citation state and approved playbook candidates;
- explicit missing-evidence markers.

The adapter excludes raw visitor histories, caregiver or patient content, email addresses,
private replies, credentials, and relationship notes. Relationship-sensitive work uses a separate
more restricted decision class and is outside article packet v1.

The secondary `wema.review@1` intake consumes an exact deployed-review release, inventory digest,
closed checklist choices, item IDs, and bounded notes. It excludes reviewer identity. Public text
is internal, decision-only evidence and is never eligible for model use. A change or not-sure
choice deterministically entails one advisory operator follow-up in Wema's existing queue; an
all-clear packet creates no work. Review feedback never supplies approval or effect authority.

### 13.3 Article candidate vocabulary v1

The initial closed vocabulary may include only host-backed operations such as:

- improve one existing revision in the editor;
- prepare one missing answer section;
- add or repair approved internal links;
- prepare metadata/search/social preview corrections;
- prepare a channel-native share kit through an approved playbook;
- request a new founder voice/promise decision;
- wait for more evidence.

The exact vocabulary is admitted only after mapping each entry to an existing Wema operation and
static gate. AEOS does not publish directly in v1. Publication remains Wema Tier 2 and uses its
existing authenticated workflow and authority.

### 13.4 Founder experience

The existing Wema Today selector remains the only founder queue and preserves its five-card cap.
An AEOS article recommendation becomes or updates one `OwnedAction`; repeated refreshes do not
create duplicates. The card states:

- the outcome in ordinary English;
- why this is the best next use of attention;
- what was prepared;
- what evidence supports it and what remains uncertain;
- what will and will not happen;
- one recommended response.

Opening it deep-links to the real article editor or a bounded existing flow. The founder selects
Use this, Change it, Not now, or Snooze. She is never asked to interpret SEO scores, operate a
pipeline, chase a lead list, or approve unseen content.

### 13.5 Execution and learning

Wema records the digest-bound, capacity-bound attestation and authorizes the registered operation.
Its workers execute the operation using existing outbox, idempotency, kill-switch, provider and
recovery mechanisms. The receipt links back to the AEOS decision. Later policy-permitted aggregate
outcomes become evidence. AEOS then retains, revises, closes, or reopens the decision; it does not
declare that distribution, clicks, or time spent prove usefulness or revenue.

### 13.6 Daily growth adapter

The second Wema advisory slice consumes the complete versioned Reach route catalogue, the
catalogue's deterministic rank and availability prerequisite, independently verified cumulative
route outcomes, current safe state of each named research source, and one exact project-local
graph snapshot. It maps every eligible route to an advice-only candidate, while the governed first
rank is the sole entailed candidate. The recommendation retains alternatives for John's detail
view and creates or updates at most one operator-owned preparation action in Wema's existing queue.

This slice never imports a prospect identity, address, reply, private community content, follower
list, caregiver story, or provider credential. It cannot contact, post, spend, approve, or select
words on the founder's behalf. Research and preparation remain John's work. Only after Wema has
rendered an exact destination-and-words package does the existing founder Today approval appear.
An unavailable source remains unavailable; it cannot be inferred as zero or replaced by another
source. A stale or unreconstructable graph context refuses the recommendation rather than reusing
yesterday's choice.

### 13.7 Mailbox triage adapter

The third Wema slice decides what one inbound business message gets — a refund and a reply, a
reply, a privacy request, or a person reading it in the mailbox — from closed values only: the
mailbox registry's policy for that mailbox, the message's class and routing facts as the host's
sync recorded them, and the matched order's state. The projections refuse an address, a line
break or an unregistered value; no subject, body, sender or name has a field to travel in.

The registry's recommended action is the single entailed candidate while its named facts hold,
the fallback is entailed when they do not, a risky message always entails reading it, and "read it
in the mailbox" is always offered and never entailed. Sending a reply and refunding an order are
outward effects with the boundary tags `outbound_mail` and `payment`; the host registers them,
a person attests every one in this slice, and a refund carries the order amount as its cost
ceiling. The recommendation becomes or updates one card in Wema's existing queue with the
decision identity in its evidence; the reply text a person approves is the host's, drafted and
gated under the text-quality lane of §9.1, and never part of the packet.

## 14. Schema and compatibility policy

- Python package: `aeos-kernel` with import namespace `aeos_kernel`.
- Semantic versioning applies to the Python API and interchange contracts.
- Published schema IDs include major versions, for example
  `https://aeos.local/schemas/v2/decision-packet.schema.json`. V1 resources remain published for
  historical readers; v2 is the current writer contract.
- Readers reject unknown major versions. Additive optional fields may be introduced in a minor
  release. Changed meaning or required fields require a new major schema.
- Canonical serialization recipes are part of the contract and have known-answer vectors.
- Adapters declare `adapter_id`, `adapter_version`, supported schema versions, candidate vocabulary
  versions, and effect vocabulary versions.

## 15. Verification strategy

Required suites:

1. **Deterministic:** fingerprints, identities, selector specificity, authority precedence,
   candidate eligibility, entailed selection, lifecycle transitions and idempotency.
2. **Adversarial/red-plant:** fabricated citations, stale/forged pins, cross-tenant evidence,
   invented actions/effects, human-boundary bypass, changed replay bodies, conflicting decisions,
   budget bypass, provider-identity mismatch and postimage mismatch.
3. **Drift:** material dependency changes reopen; irrelevant changes do not.
4. **MultiAgent compatibility:** selected source known-answer and red-plant fixtures produce the
   same decision/refusal and compatible receipt.
5. **Wema contract:** real Wema packet projections validate; article advice maps to one
   deduplicated Today action, records an attestation, executes only an authorized registered
   operation and stores its receipt; deployment-review advice maps to at most one model-forbidden
   operator follow-up and cannot authorize an effect.
6. **End to end:** a versioned article recommendation travels from Wema evidence through AEOS,
   Today and the authenticated operation to a measured outcome and a close/revise/reopen result.

Tests must exercise PostgreSQL and the actual Wema API/worker boundary where persistence behavior
is claimed. Pure in-memory tests cannot prove production integration. Existing Wema and
MultiAgent tests remain authoritative for behavior owned by those systems.

## 16. Packaging, deployment and rollback

The initial deployment is a pinned package imported by the Wema API/worker. No AEOS daemon or
public endpoint is introduced. The private 0.3 graph fleet uses one isolated Memgraph endpoint,
credential and data volume per project; Wema is the first project. Package artifacts include
source, schemas, type information, changelog and provenance manifest. Wema pins an exact release
and records it in deployment evidence.

Database migrations live with the system that owns the data. AEOS publishes contracts and
reference migrations but never silently migrates a host database. Rollback disables the AEOS
writer/refresh job through a Wema kill switch, restores the previous pinned package, and leaves
append-only decisions, attestations and receipts readable. Already executed outward effects use
their host-defined compensation path; package rollback does not pretend to reverse the world.

## 17. Delivery sequence

1. Pin and inventory source behavior and source tests.
2. Extract strict JSON fingerprinting, core enums/contracts, authority resolution, evidence
   validation, candidate eligibility and fail-closed result types.
3. Add generic subject/effect/receipt contracts and only consumed runtime ports; keep WLG
   concepts in the compatibility adapter.
4. Publish versioned schemas and known-answer fixtures.
5. Prove the MultiAgent compatibility adapter against committed source fixtures.
6. Implement Wema article packet and result adapters without changing Desk semantics.
7. Add Wema persistence and worker integration behind an off-by-default kill switch.
8. Project one recommendation into existing Today and record the founder attestation.
9. Execute one already registered article operation and record/verify the receipt.
10. Consume one real or explicitly insufficient outcome window and exercise close/revise/reopen.
11. Run both repositories' relevant gates, deployment smoke tests and rollback drill.
12. Publish the safe Wema advisory projection to its isolated Memgraph endpoint, prove a real
    fixed-query read, and prove loss of that endpoint cannot authorize or execute an effect.

## 18. Definition of done

AEOS is complete for this goal only when:

- this repository is independently versioned and publishes a stable typed package and current v2
  schemas while preserving the historical v1 resources;
- the provenance inventory accounts for every extracted or deliberately excluded source behavior;
- MultiAgentCommunication runs through a compatible adapter with selected original tests green;
- Wema uses AEOS through API/worker adapters and not through the Desk or localhost coordinator;
- security, privacy, authority, spend, human-review and irreversible-effect boundaries have
  executable fail-closed tests;
- every abstraction has a named live consumer;
- the real article-decision loop works end to end with durable decisions, attestations, effects,
  receipts and outcome evidence;
- deterministic, adversarial, drift, compatibility, integration and end-to-end suites pass;
- packaging, deployment, migration, kill-switch, rollback and recovery evidence is current;
- every remaining external human or provider dependency is stated with an exact next action.

## 19. Project-isolated advisory graph foundation

This section is the operator-directed 0.3 amendment and supersedes only the earlier statements
that no graph service or credential would exist in the first deployment. The rest of the
authority, privacy, host-effect and no-public-service boundaries remain unchanged.

### 19.1 Purpose and ownership

AEOS uses a graph to derive relationships that become more valuable as content, audiences,
questions, channels, playbooks, decisions and measured outcomes grow. It is an advisory read
model: every graph snapshot is rebuilt from exact, pinned source-system revisions. PostgreSQL and
the host's governed files remain authoritative for evidence, decisions, attestations, effects,
receipts, customer records and publication state. A graph write cannot approve, publish, contact,
charge, delete or otherwise create a host effect.

Wema is the first consumer, not a special case in the kernel. Product vocabularies and projections
belong in adapters. The kernel accepts only a closed adapter-owned node, edge and property
vocabulary and exposes only registered, parameterized queries. It accepts no caller-authored
Cypher.

### 19.2 Isolation model for many projects

The production unit is a **project graph**, not one shared Community-edition database with a
`project_id` filter as its only wall. Each project receives its own private Memgraph endpoint,
encrypted data volume and credential. Projects may initially share a hardened private host, but
not a Bolt port, storage directory, credential or backup set. A later Enterprise deployment may
provide equivalent isolated databases and fine-grained access control without changing the AEOS
graph contract.

For the first vertical, that host is the operator's local workstation. This is intentional: the
advisory graph and subscription-backed agent work stay local, while Wema production remains
graph-independent. A local outage pauses new recommendations and nothing else. Remote graph or
metered model infrastructure is introduced only after measured workload, availability or revenue
shows that its recurring cost can create more value than it consumes.

Every project, snapshot, entity and relationship is also stamped with `project_id`, `vertical_id`
and `tenant_id` as defense in depth. The store is bound to those values at construction and rejects
cross-scope snapshots before opening a connection. Fixed reads repeat the scope predicates.

### 19.3 Immutable snapshot protocol

A projection publishes one immutable graph generation containing:

- a strict graph schema version and closed-vocabulary digest;
- exact source-head pins;
- stable entity and relationship identities;
- content digests and safe public/internal properties;
- evidence references for each relationship;
- project, vertical and tenant scope; and
- a reproducible snapshot digest.

The digest excludes the observational `built_at` timestamp so a retry from identical sources can
reproduce the same identity. Publication creates the complete new generation and flips one
`CURRENT_SNAPSHOT` edge in the same transaction. Identical replay is a no-op with the same receipt
identity. A changed snapshot must advance the generation. Concurrent writers touch the same
project anchor; Memgraph transaction conflict aborts a loser rather than admitting two current
generations. The host retries from current source pins.

The active project policy retains the current generation and its two immediate predecessors.
Publication prunes older generations only after the new current pointer is established inside
the same transaction. Daily transaction-consistent dumps provide recovery beyond that bounded
online rollback window. A reader sees only the current complete generation, never a half-written
refresh, and storage growth does not multiply the complete graph without bound.

### 19.4 Privacy and model boundary

Only `public` or `internal` graph nodes are admissible. Raw review prose, email addresses, visitor
histories, lead or customer identity, caregiver/patient content, credentials, private
relationship notes, and anything classified `restricted` or `prohibited` stay out. Aggregate
outcomes enter only when the host's active analytics policy permits them. A graph neighborhood is
evidence for candidate preparation, never authority for a model or effect.

### 19.5 Availability and operations

The graph is absent from public-page, sign-in, checkout, fulfillment and synchronous effect paths.
If it is unavailable, graph-dependent decision preparation defers with a typed retryable failure;
public delivery and already-authorized host operations continue from canonical data. No code may
silently fall back to stale graph content for an effect decision.

Production Memgraph runs in transactional mode with WAL and periodic snapshots on encrypted
storage. Bolt is reachable only from named worker security groups or equivalent private network
identities; no public listener or public graph console is allowed. Each project has independent
health, storage, memory, query-latency, refresh-age and backup/restore evidence. Capacity alerts
trigger before the host or volume is exhausted. Backup restoration into a separate endpoint and
snapshot-digest comparison are required before graph activation is called production-ready.

The first production implementation is `infra/local`: one systemd service and operating-system
user per project, loopback-only Bolt, a generated per-project credential, separate grow-as-used
data/log/backup directories, transactional WAL and snapshots, and a disposable restore endpoint.
MultiAgentCommunication's graph is neither a dependency nor a shared database. `infra/aws` is a
later costed deployment option, not the active topology. Community authentication supplies the
project-local user/password boundary; because Community does not provide fine-grained roles,
network and process isolation remain mandatory rather than optional.

### 19.6 Graph definition of done

The foundation is production-ready only when the schema and fixed queries pass unit and real
Memgraph integration tests; two isolated test projects cannot observe or mutate each other;
idempotent replay, changed-generation, concurrent-writer, crash/rollback and unavailable-graph
cases are proven; Wema's first safe projection and real decision read are measured end to end;
monitoring, backup, restore and credential rotation are rehearsed; and the host remains able to
run with graph decision refresh disabled.
