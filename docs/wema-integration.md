# Wema integration contract

**Contracts:** `wema.article@2`, `wema.review@1`
**Wema source inspected:** `76e7c0f4fb1df28a9b77a02e1743eec83cd5a249`

## Ownership

Wema owns every production fact and effect. AEOS is imported by Wema's API/worker as a
pinned package. The browser never calls AEOS and AEOS never receives a Wema session,
cookie, credential, database connection, provider token, raw customer record, or private
caregiving value.

| Concern | Owner |
| --- | --- |
| Authentication, role and capacity | Wema API |
| Article, revision, review and publication truth | Wema PostgreSQL models/services |
| Evidence projection and analytics policy | Wema worker/API |
| Candidate vocabulary and operation registry | Wema |
| Eligibility, bounded choice and recommendation | AEOS kernel |
| Today queue and founder presentation | Wema Desk/API |
| Human attestation and idempotency | Wema API/PostgreSQL |
| Effect authorization and execution | Wema worker/domain service |
| Receipt and outcome observation | Wema PostgreSQL/worker |

## Deployment-review intake

The public `/review` checklist may explicitly save one release-bound advisory packet to Wema.
Wema passes the exact packet kind, release, inventory and payload digests, closed choices, item IDs,
and bounded notes through `wema.review@1`. Reviewer identity is excluded from the AEOS packet.

This lane is deliberately deterministic and model-forbidden. One or more `needs_change` or
`not_sure` choices entail one `aeos_review_follow_up` action in the existing operator queue; an
all-clear review creates no action. The queue projection contains only the submission reference,
counts, release, packet kind, AEOS decision identity, and canonical digests. The review record—not
the queue—retains the short-lived text. Nothing in this intake approves a screen, publishes
content, executes an effect, or grants authority.

## Existing seams used verbatim

- Article detail and immutable revision: `apps/api/wema_api/articles/projections.py` and
  `articles/service.py::revise_article`.
- Article quality and review contracts: `apps/api/wema_api/articles/contracts.py` and
  `packages/marketing-contracts/wema_marketing_contracts/editorial.py`.
- Founder queue: `OwnedAction`, `apps/worker/wema_worker/actions.py::upsert_owned_action`,
  and `apps/api/wema_api/actions/selector.py::select_founder_today`.
- Desk rendering: `TodayScreen.tsx`, `Today.tsx`, and the existing article editor route.
- API write controls: authenticated session, CSRF, role/capacity, `If-Match`, and
  `Idempotency-Key` primitives already used by article revision/review/publication routes.
- Effects: Wema work items, outbox, kill switches, audit records and retry/recovery.
- Model calls: `packages/model-gateway`; no provider client exists in AEOS.

## Packet construction

The Wema worker reads one current `ContentArtifact` and `ContentVersion`, computes the
existing article quality projection, and fetches only policy-permitted aggregate outcomes.
It calls `build_wema_article_packet` with:

- exact article/version IDs, revision number and article digest;
- safe title, question, answer-first, description and article class;
- quality rule output and version;
- required/approved review capacities;
- permitted aggregate outcomes or `insufficient_evidence`;
- the current canon/authority bundle digest;
- exact Git, registry, analytics-policy and database-snapshot pins.

The adapter must reject or omit raw event rows, visitor histories, emails, message bodies,
caregiver/patient data, credentials and relationship notes. A packet is rebuilt from a
read-consistent database snapshot; mixed revisions are invalid.

## Candidate and effect

The first executable operation is:

```text
wema.article.create_revision
```

It accepts exactly `article_id`, `expected_digest`, and a prepared `draft`. Wema's executor:

1. verifies the AEOS release and adapter vocabulary versions;
2. locks the `ContentArtifact`;
3. rechecks its current version and exact digest;
4. verifies the founder attestation and current capacity;
5. validates `draft` with Wema's existing strict `ArticleDraft` model;
6. calls the existing `revise_article` service with the attesting actor ID;
7. records the ordinary article revision audit entry;
8. flushes the new immutable version but does not approve or publish it;
9. stores an AEOS effect receipt containing the new version ID/digest;
10. commits all local records in one database transaction.

The operation has the `content_revision` boundary, is Tier 1, is reversible through the
existing forward-only restoration operation, and produces
`new_unapproved_article_revision`. AEOS never calls `requestArticlePublication` or
`mergeArticlePublication` in v1. Those remain owner-only Tier 2 decisions with their own
exact digest and provider receipt.

## Today projection

`to_owned_action_values` maps one recommendation to the real `OwnedAction` columns:

- `module=marketing`
- `source_ref_type=content_article`
- `source_ref_id=<article id>`
- `decision_kind=aeos_article_revision`
- `requires_founder_judgment=true`
- `rank_class=compounding`
- references/digests only in `evidence`

The writer uses `upsert_owned_action` over unresolved rows, so refresh replaces evidence
instead of creating a duplicate. Wema must register `content_article -> desk_article_editor`
in `TODAY_SOURCE_SCREENS`; otherwise the current client correctly falls back to Actions and
the recommendation cannot be called end-to-end usable.

The card opens the real article editor. The recommendation detail shows one ordinary-English
reason, prepared change, expected benefit, uncertainty, effect boundary, and four answers:
Use this, Change it, Not now, and Snooze. Internal scores and engine terms remain absent.

## Persistence delta

Wema, not AEOS, owns the migration. The smallest durable model is append-only:

1. `aeos_decision_events` — append-only decision ID/revision lifecycle events, packet and
   candidate-set digests, selected candidate, adapter/vocabulary versions, explanation
   projection, dependency snapshot and timestamps.
2. `aeos_attestations` — actor, server-resolved capacity, decision/revision, recommendation,
   subject and projection digests, closed response, bounded note, snooze, idempotency hash.
3. `aeos_effect_receipts` — authorization, operation, request digest, state, result reference,
   postimage digest and safe diagnostic.
4. `aeos_outcomes` — receipt, registered metric/window, policy digest, aggregate result and
   evidence digest.

Uniqueness must distinguish transport replay from semantic decisions. The host locks the subject
before accepting an answer: the first valid answer becomes the durable attestation, an identical
semantic answer is a no-op even under a fresh transport key, and a concurrent different answer is
refused as a conflict. It cannot overwrite the accepted attestation or effect. Material subject
drift, rather than transport arrival order, is what opens a replacement recommendation.

## Refresh, drift and recovery

One registered worker job refreshes article decisions. It is off by default until deployment
verification succeeds. The job deduplicates by subject and input digest. Material subject,
evidence, canon, authority, candidate-contract or host-policy changes mark the prior decision
stale and create a linked revision. An unrelated code or database change does not.

Failures leave the previous decision and prepared output readable. A retry consumes the typed
failure. Provider or model failure creates no article revision. An indeterminate local effect
is reconciled against the current article/version and idempotency identity before retry.

## Required Wema verification

- Packet projection unit/privacy tests.
- PostgreSQL attestation replay, changed-body conflict and concurrent-answer tests.
- Worker action deduplication and stale/reopen tests.
- Operation-registry, kill-switch, capacity, digest, parameter and postimage red plants.
- Desk route and plain-language interaction tests.
- Real API/worker integration from packet through unapproved revision receipt.
- Browser proof that Today opens the real article and all four answers are usable on mobile.
- Serialized Wema `verify:arch`, `verify`, and `verify:ui` at the exact integration commit.
