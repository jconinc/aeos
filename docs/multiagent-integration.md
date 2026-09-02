# MultiAgentCommunication compatibility contract

**Adapter:** `multiagent.wlg@3`
**Pinned source:** `f8b76c9930e590983d1e0c5e232bd8817191db7f`

The adapter is additive. It does not move graph storage, task claims, pipeline scheduling,
static patch gates, mutation lowering, transactions, or graph receipts into AEOS.

## Mapping

| WLG | AEOS | Owner after extraction |
| --- | --- | --- |
| project ID | tenant ID | WLG adapter |
| decision unit/shape set | decision subject | WLG adapter |
| graph revision | subject revision/current-revision verifier | WLG adapter |
| WLG evidence item | evidence item | shared contract; WLG supplies data |
| canon/source pins | authority bundle and source pins | shared verification; WLG loaders |
| `DecisionCandidate` | candidate | shared eligibility; WLG candidate producer |
| `RepairMutationPlan` | effect parameters | WLG adapter |
| static patch gate | effect authorizer | WLG implementation |
| graph transaction | effect executor | WLG implementation |
| durable graph receipt | effect receipt mapper | WLG implementation |
| `CanonDecision` | recommendation projection | compatibility mapper |

## Preserved behavior

The source-compatibility suite imports the actual pinned committed modules and compares:

- authority and lifecycle enum values;
- canonical fingerprint known answers for strict JSON inputs;
- evidence-ranked unique candidate resolution, including ambiguity, cross-domain,
  name-only and placeholder refusals;
- path, field, lifecycle and wildcard rule selector behavior.

The read-only shadow suite imports and executes the actual pinned
`claude_coord/tests/test_canon_decision.py` fixture helpers. It compares deterministic selection,
authority-tier precedence and conflict, citation and candidate red plants, low confidence,
reverse-order acceptance and disagreement, cross-project and stale evidence, static-gate
admission/refusal, and source-head drift across the selected decision/refusal, citations,
escalation class, typed effect and expected receipt.

Adapter v3 preserves each evidence item's native project/revision rather than laundering it into
the packet scope. It also refuses a WLG candidate unless the host's real candidate-bound static
gate passed and binds that gate's full repair-contract digest into the typed effect. The WLG host
must re-run its commit gate immediately before execution.

The committed PostgreSQL pipeline, lifecycle/replay, graph receipt and receipt-bound retraction
fixture identities are pinned in `docs/multiagent-shadow-parity-v2.json`. Their generic invariants
run in AEOS; their graph, database, task claim and transaction machinery deliberately remains in
MultiAgentCommunication and is not imported or simulated here.

## Adoption sequence

1. Publish and pin an AEOS wheel.
2. Add a WLG adapter module that converts its native types at the existing canon-decision
   compiler boundary.
3. Run both old and AEOS compilers in read-only shadow mode on a known-answer corpus; persist
   a parity report, never duplicate effects.
4. Refuse adoption if selected candidate/refusal, evidence citations, escalation class,
   typed plan, or receipt expectation differs without an approved contract change.
5. Switch the decision compiler behind one configuration entry.
6. Retain the legacy path for one release as rollback, then remove it after parity and
   survival evidence are current.
