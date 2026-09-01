# MultiAgentCommunication compatibility contract

**Adapter:** `multiagent.wlg@1`  
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

The fuller migration must additionally replay selected `test_canon_decision.py` fixtures
through the adapter for evidence/citation/pin failures, entailed selection, model consensus,
static-gate refusal and decision projection. PostgreSQL pipeline/receipt tests remain in
MultiAgentCommunication because its database and transaction path own those claims.

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

