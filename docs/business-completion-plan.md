# Complete AEOS through Wema

Owner-directed scope, 13 September 2026. Implementation is active; completion is unproven.
The [full goal](business-completion-goal.md) is the acceptance target. Delivery packets order
the work; they do not postpone applicable business capabilities to an unspecified later release.

## Master completion checklist

The requirement map currently contains **553 indexed IDs: 540 unassessed, seven with partial
source implementation and six with unverified workflows; none is accepted complete**. This
is the state of this reconciliation, not a claim that 540 features are missing. Existing
functionality and accepted evidence must be reused after their applicability is established.
The full applicability assessment remains a required work item, alongside implementation.

- [ ] Assess every indexed requirement and its referenced obligations: applicable, or an
  explicit product-specific exclusion. Name the existing implementation before adding code.
- [ ] Connect research, offers, playbooks, distribution, customer responses and measured learning.
- [ ] Complete leads, partnerships, sales, purchase fulfilment, renewals and recovery.
- [ ] Complete customer support from inquiry through grounded help, permitted action,
  confirmed outcome and follow-up. **Currently being implemented and tested.**
- [ ] Close operational monitoring: detection window, investigation, response and evidence
  that each condition has cleared; missing observations remain unknown.
- [ ] Connect financial and business performance to prepared decisions using trustworthy
  revenue, cost, conversion and contribution records.
- [ ] Connect repeated customer difficulties to improved help or a verified product fix,
  with appropriate customer follow-up and preserved privacy.
- [ ] Verify quality, authority, privacy, security and shared spending controls across all
  applicable consumers, including failures and recovery.
- [ ] Complete the simple Desk and CLI journeys: clear meaning and consequences, comments,
  disagreement, deferral and returning later. Measure actual representative user effort.
- [ ] Integrate reusable AEOS work into `/home/john/code/aeos`, preserve its other work,
  and make Wema consume the integrated version through its normal dependency pin.
- [ ] Complete applicable native checks and coverage, then compatible integration,
  deployment, recovery and installed workflow verification.

An applicable requirement is complete only when its defining behavior is implemented, a
named production caller uses it, successful and relevant refusal/recovery journeys have
acceptance evidence, required Desk/CLI instructions are maintained, and its integrated and
delivered disposition is verified. Where user comprehension is required, record the user's
actual explanation, confusion and completion time. Test counts and package publication alone
do not satisfy these conditions. Pending human decisions remain named dependencies; never
manufacture an approval or silently exclude its requirement.

The final check is a review of the entire map and referenced obligations: no unassessed,
partial, unverified or otherwise unresolved applicable requirement; no unspecified later
work; preserved existing behavior; verified repository integration and delivery. The current
support increment cannot complete the overall goal by itself.

## Scope and source authority

The broader source is `future_projects/aeos` at
`29a3652e85cf091beff3c7651b61fd4718d7c145`: its core requirements, eight-file requirement index,
business-layer decisions, business modules, marketing playbooks and build roadmap. The index
contains 553 distinct requirement IDs. This is an index size, not a count of missing features,
an implementation percentage or a claim that the index contains every acceptance obligation.
Tables, transition rules, canaries, later amendments and referenced contracts also bind.

The [requirement map](business-requirements.csv) preserves those IDs. Its initial unassessed
rows deliberately claim neither absence nor completion. Each row must acquire its Wema
applicability decision, actual producer/consumer, acceptance evidence and delivery disposition.
Read the complete defining requirement and its dependencies before deciding the row.

The present direction makes Wema the first full product demonstration. Historical PFV-first
sequencing and initial kernel-only scope do not cap this goal. Product-specific FDA, FOIA or
verdict-dossier operations need an explicit applicability decision; their existence in another
product profile is not a reason to add them to Wema. Missing implementation is never a reason
to declare an otherwise applicable requirement inapplicable.

Existing Wema behavior remains governed by its maintained canonical specifications. Resolve
differences between the broader design and the host explicitly in each implementation packet,
with the relevant specification amendment and evidence. A historical graph-based design may
map to Wema's authoritative native records where the required behavior and invariants are
preserved. Do not substitute a second source of truth or silently weaken a requirement.

User-visible progress stays in Wema's `docs/aeos-wema-remaining-work.md`, linked to this plan.
Earlier accepted CLI, mail maintenance and delivery records keep their original scope and
source identities. They are evidence to reuse, not proof of all business requirements.

## Architecture to preserve

### Parallel implementation and test cadence — John, 13 September

The full 553-ID map is divided without omissions or duplicate ownership: claude-2 owns
marketing/commercial/earned distribution/portfolio (195 IDs); claude-3 owns operational runtime,
monitoring/recovery/security/rules/legal boundaries (155); claude-0 owns reusable control-plane,
product/module/lifecycle/WLG interfaces (119); claude-4 owns support/model integration and the
combined private candidate (84). Shared-tip and host delivery remain coordinated with claude-3.
The exact assignments, defining sources, owned worktrees, interfaces and handoff requirements
are in `~/wema-coord/active/aeos-complete-business-2026-09-13/delegation/`.

Authors implement coherent slices and write acceptance controls, with cheap local syntax/lint/
type checks. John directs runtime suites to run after integration. Existing active frozen runs
may finish; retained accepted proof is reused on its actual inputs. Do not start three parallel
full chains or call deferred controls passing. The combined candidate uses the maintained
selector, cheap prerequisites and receipt reuse, then multiple native workers for independent
suites with one private PostgreSQL clone per worker and controlled resources. Test design must
avoid repeated migrations/setup, shared mutable fixtures, duplicated scenarios and clock sleeps.
Record worker count, setup/runtime, executed/reused evidence and diagnose overruns. Required
coverage, refusal/recovery controls and delivery checks remain unchanged.

| Responsibility | Implementation home |
| --- | --- |
| Reusable decision, evidence, quality, lifecycle and authority primitives | `aeos_kernel`, with a named host consumer for every addition |
| Wema facts, privacy, business state, effect authority and outcome truth | Existing Wema domain services and PostgreSQL records |
| Scheduled, long-running and retryable work | Existing Wema worker registry, scheduler and transactional outbox |
| Model access, permitted context, budgets and provider failures | Existing host model gateway; no second provider engine |
| Human work | Existing Desk screens and bounded flows, with prepared information and recoverable responses |
| Agent/operator access | Maintained CLI and the same native authorization and operations as Desk |
| Product development and verification | Existing development pipeline, selector, receipts and release tooling |

Keep Wema's public site and already-authorized work independent of optional advisory graph or
model availability. Begin with additive compatible changes, exact package pins and small host
adapters. Extract shared behavior after identifying its real consumer; a new service, framework,
queue, graph schema or abstraction must solve a concrete unmet requirement.

## Complete operating workflows

All rows below are in this goal. Source leads identify reusable capability; they are not
end-to-end acceptance verdicts.

| Workflow | Existing source leads | Remaining completion work and proof |
| --- | --- | --- |
| Research, offers, marketing and distribution | Wema commercial guidance, assistance, Reach, native channel handlers and playbooks | Trace applicable playbooks from current research and customer moment through prepared material, valid execution, observed results and next decision. Establish customer value and channel controls per actual audience/channel. |
| Leads, partnerships, sales and renewals | Native partner inquiries, organizations, onboarding, licences and renewal handlers | Verify complete follow-through, stage/next-action truth, delivery, expiry and renewal outcomes. Use Wema's actual offers, not an assumed subscription model. |
| Customer inquiries and recovery | Mailbox registry/sync, AEOS mail triage, Desk reply flow, reply loop, access/refund workers | Connect missing model drafting, verify current source/order facts and provider-context policy, follow the actual reply and recovery to completion, and handle failures without duplicate effects. |
| Operational monitoring and recovery | Worker metrics, observability declarations, outbox, mailbox health, commerce reconciliation, rubric calibration | Map every required condition to its measurement, detection window, response, responsible destination and clearing evidence; test missing observations and recovery. |
| Business and financial monitoring | Marketing aggregates, partner metrics, contribution and commerce reconciliation | Join trustworthy customer value, conversion, costs, contribution and follow-through signals to decisions, preserving scope and evidence floors. Missing or withheld data cannot mean zero or healthy. |
| Customer feedback to product improvement | Existing support records, help/content mechanisms, problem reports and WLG pipeline | Establish the exact feedback-to-requirement-to-verified-fix-to-customer/help path. Avoid copying private customer text into a shared graph or build task. |
| Quality, privacy, security and policy | Kernel gates and Wema role, approval, source, budget, registry and runtime controls | Reconcile all applicable controls with their native consumers, failure witnesses, alerts and recovery. Separately record policies requiring an owner decision. |
| Founder experience and workload | Desk Today/actions, existing reviews, notes, comments, deferral and CLI | Demonstrate clear tasks and responses in the real flows; retain work across return/refresh. Measure review and exception effort separately. A five-card display ceiling does not throttle the worker. |
| Reusable product operation | Kernel adapters, isolation and versioned contracts | Keep shared capabilities product-neutral, maintain Wema compatibility and define explicit product-profile substitutions. No requirement is complete from a symbol name alone. |

## Initial source findings

Inspected baselines: AEOS `5f7291dc1131b431fe2b9572e4f20ad90edc5a42` and Wema
`6088a85342d1ec72ea3602c63f84c0840577cc9b`. These are source observations, not a fresh installed
runtime test or a claim that later concurrent source has been reviewed.

- **Verified connection gap:** Wema's `run_reply_loop` has a definition/export and test callers,
  but no production caller in the inspected Python/TypeScript source. The documented
  `support_reply_draft`, `draft_support_reply` and `score_support_reply` integration is missing.
  The production configuration does not name an `inbound_correspondence` context. Adding a
  configuration label alone would not implement the feature.
- **Existing preparation and execution:** `previewMailReply` accepts permitted agent
  preparation; Desk offers edited reply review, deferral and sending through the existing native
  command. Current reply authority requires a human attestation. Existing source implements
  access recovery and attested refunds; their runtime activation must be checked separately.
- **Existing monitoring:** `metrics.py` reads dead work, oldest pending age, delivery failures
  and reconciliation drift; the worker main loop calls its publisher. The observability stack
  consumes the same declarations. Scheduler jobs cover mailbox sync, calibration, commerce,
  marketing, renewals and source/placement checks. These are reusable foundations, not evidence
  of full support-SLA, business-health or incident-loop coverage.
- **Unverified broader loop:** full repeated-inquiry to improved help/product to verified
  customer follow-up has not been demonstrated in this reconciliation. Treat it as unresolved,
  not as a proven absence of every constituent service.
- **Concurrent work to preserve:** the operational-mail lane recorded candidate `daa25904`
  in `active/mailbox-task-repair-2026-09-13/automatic-monitoring/README.md`. Its additional
  operations account, routing and native transport work is separately owned. Read its terminal
  source/evidence before joining; this goal must not duplicate its credential or host operations.
  Current playbook-form work is likewise a possible integration dependency, not permission to
  edit another worktree or repeat its tests.

## Delivery order and acceptance

The first support component is implemented in Wema `43a2d441` (13 September): the internal
gateway task/context registry, reply and scoring output/privacy boundaries, cost admission,
usage retention and the worker callable into the existing bounded loop. Native component
proof is 150 passing cases in six complete files, six affected prerequisites and two killed
registered mutations with passing controls; 50.667 seconds, two Python workers with exclusive
database clones. Original missing-task witnesses and the first changed-registry expectation
failure remain retained. No external provider, message, human decision or host operation ran.

This does **not** complete REQ-SUP-029. Durable worker registration, current message/rule/order
binding, persisted prompt and source provenance, concurrent spend accounting, a reviewed real
provider route, and Desk readback are the next work in this same support packet. The native
source selection currently reaches 416 Python files; the six-file component run is not its
completion or a release verdict. The original broad selection caused by Coord's untracked
task metadata also remains recorded, and the metadata stays at its original path. No selector
rule was changed. Existing operations-mail delivery `daa25904` is terminal in its own record
and must be preserved before this packet is delivered.

Retained component packet:
`~/wema-coord/evidence/aeos-complete-business-2026-09-13/43a2d441e4d13936bb16cfe5515b36b65a95b921/author/support-foundation-01/`.

The next component is Wema `b443e32f`, with test-only successor `53b2b0eb`. It preserves
operations-mail source `5c6b1225` through merge `fc493196`. The real support HTTP adapter,
fixed native rubric prompts and expiring route-review binding are implemented; the route
remains disabled and no approval or credential is supplied. Unknown response usage retains
an explicit conservative cost bound, and attempt values now carry prompt identity and that
cost distinction in memory. Their durable persistence remains required.

Native component evidence is 200 Python cases across seven complete files: the final pass
executes 48 cases and reuses the other 152 on six authenticated receipts. The prior source
pass executed 181 and reused ten; these are overlapping unions, not additive totals. The
25 registry controls and selected gateway mutation pass. Native filtered coverage proves
all 180 statements and 38 branches of the three new provider/prompt/review modules; the
worker callable is 39/39 and 2/2. The last test-only pass takes 27.064 seconds. Original
registry assertion failures and the offline-fake selection refusal witness are retained.
The full source selection now reaches 418 Python files and remains incomplete. No full
application/package coverage, release acceptance, real provider call or automatic reply is
inferred. Packet: `~/wema-coord/evidence/aeos-complete-business-2026-09-13/53b2b0eb199044c0d17bf018eb7599cd702501c9/author/support-http-01/`.

1. **Reconcile requirements and existing work.** Preserve the exact goal, inspect each existing
   requirement and its native consumers, and add omitted obligations from tables and referenced
   contracts using their source anchors. Record behavior differences requiring amendments. Use
   one map and the existing progress tracker; this is engineering evidence, not a new Desk UI.
2. **Complete inquiry preparation and resolution.** Wire the existing model gateway and reply
   loop through a native worker with controlled inbound context, current facts and retained
   draft/scoring evidence. Prove relevant privacy, provider failure, fallback, replay, changed
   source and Desk response paths. Keep current send authority until a deliberate policy change
   is adopted; review routine manual steps rather than assuming all must remain human forever.
3. **Complete monitoring and permitted recovery.** Reuse actual signal emitters and native
   actions. Cover overdue inquiries, missing outcomes, stale sources, quality/cost failures and
   operational faults. Prove detect → investigate → permitted response/escalation → verified
   clearing, including failures of the monitor itself. Do not invent a universal health score
   before its decision and failure semantics are specified.
4. **Close commercial, marketing and improvement loops.** Connect remaining applicable
   playbooks, sales/renewal follow-through, financial outcomes, repeat-issue analysis, help and
   development tasks. Deliver each coherent workflow when verified; do not wait for the entire
   programme to deploy a finished independent slice.
5. **Demonstrate complete operation.** Perform requirement-by-requirement final acceptance,
   realistic user sessions and intended-environment verification. Account for unresolved human
   inputs honestly. No generated receipt, model assertion or fabricated business event may
   stand in for an actual required observation or approval.

Steps may overlap where their inputs are independent. Dependencies determine the order, not
an arbitrary requirement to rebuild all infrastructure before customer-facing work can land.

## Efficient verification and engineering

- Establish a failing or refusal witness for actual behavioral gaps, then run cheap affected
  prerequisites and the maintained selector. Preserve existing coverage and business controls.
- Use bounded test workers, each with its own PostgreSQL 16 clone and isolated installation.
  Choose concurrency from measured resource use and other active lanes, not a fixed maximum.
- Reuse authenticated receipts for unchanged inputs. Name source, command, expected duration
  and evidence path before heavy work; diagnose overruns or repeated boundary failures before
  rerunning. Complete applicable release checks; a merge alone is not a reason for a full rerun.
- Keep runtime concurrency separate from test concurrency. Runtime jobs need durable outcomes,
  deduplication, bounded retries, cancellation and clear failure ownership. Model calls do not
  replace deterministic bookkeeping.
- Read rendered tasks for meaning and use focused browser checks for actual flow changes.
  Usability evidence records what users understood, their confusion and active time; an agent
  cannot supply Liz's experience or approval.
- A delivered workflow has code, native consumer, appropriate tests, actual installation and
  outcome evidence. Measure response quality, completion, corrections/reopens, owner minutes
  and cost; define evaluation thresholds before interpreting the results.

## Durable support spending and provenance component — 13 September

Wema `5335d4d6` plus accounting correction `589cfbee` adds a small native PostgreSQL
reservation around the existing gateway call. It uses the current work lease, exact request
and context, four durable call slots and one aggregate lock for daily/monthly support caps.
Unknown submission keeps the full exposure; known usage can settle it once. An unfinished
or uncertain call stops further slots, and a reclaimed work item cannot replay a recorded
call. Input/prompt/cost provenance now has storage, with serialized report appends and no
format-only model acceptance. Legacy rows remain unbound; linear 0107 is provisional until
integration orders the other lanes' unlanded migrations.

Five native files pass 178 cases, with authenticated receipts/coverage, one killed selected
mutation and five positive controls. The final run took 50.020 seconds with two exclusive
PostgreSQL workers. The earlier pass reused 62 gateway cases; the final helper correction
changed the five files' actual native input closures and all five executed. Native schema
parity, architecture, lint and Python/TypeScript checks pass. Original launcher refusals and
the 34-pass/one-fail uncertain-cost witness are retained. Wema's record-only successor is
`02531150`. This component is not completion of the 440-file native selection, group coverage,
production handler, current-source adoption, reservation retention or release requirements.
The existing Marketing/research/provider cost consumers still need explicit shared-cap
integration; the support aggregate alone is not a global all-business cap.

## Immediate next implementation packet

The first new feature packet is the missing support drafting connection. Inspect the existing
mailbox producer, model gateway task/context types, draft persistence, scoring repository and
Desk read path together. Reconcile inbound-message privacy and the exact provider requirements
in the same contract change. Implement and test with fictional provider and mail transports in
an owned private database. Connect the existing worker and UI; do not introduce another support
engine. Provider enablement is a separate deployment/configuration step with its actual evidence.

The complete goal remains active throughout this packet. Finishing it will not establish
completion of monitoring, other business workflows or the requirement map.


## 13 September support consumer — partial local proof

Wema `01af4cc15a8392fc6df9dff6794d16cb80492306` connects mailbox indexing to the real
registered preparation worker, approved native template/order context, bounded gateway,
durable budget and reports, and the existing Desk review/send consumers. The source checks
survive replay; edited words lose the original model scores. Retention preserves current
spending and recoverable work. Provisional 0108 follows this lane's 0107 unchanged; integration
owns final numbering and the independently prepared migration chains.

Ten focused native files account for 255 passes: 131 executed and 124 reused in 58.7 seconds
with two private PostgreSQL workers. All ten receipts and coverage objects authenticate.
Original collection/fingerprint/edited-score failures remain, including a test-only shared
suppression interference corrected by isolating sender fixtures. No real model, message,
credential, approval or host action was used. Earlier HTTP and budget seals keep their source
identities; the counts are not added across overlapping runs.

This is not full support or business acceptance. Remaining immediate work: recovery/example
and migration refusal controls and coverage, clear Desk stale-draft handling and refresh,
source checks before compound effects, the missing access-delivery consumer behind the
existing resend-and-reply action, and maintained operator/provider configuration. The native
selector requests all Python suites because of the worker environment input, plus its 66
prerequisites and remaining consumers; no waiver is inferred from the focused proof. Finish
those requirements and compatible installed verification before calling the increment
released. Actual approved provider/help material and human usability evidence remain separate
from implementation proof. Continue the full requirement map and other business workflows;
REQ-SUP-029 stays source_partial and no requirement is marked accepted complete.

## Current private integration — 13 September, 19:10 UTC

The preceding chronological source checkpoints remain attributed to their original commits.
Current implementation is broader: private Wema `4be1e3dd` includes reply outcomes, ordinary
reply follow-through, support observations, first-response monitoring and shared model/setup
admission. Setup admission advances queued to running with its first durable reservation and
retains unresolved exposure; its worker transaction split remains explicitly incomplete. The
14 new scoped-admission controls are authored, unexecuted; lint/types/native lock/diff pass.

Private kernel `26b1bd9` joins claude-0's exact `ce19620` rule/finite-capacity source and
claude-3's `79912bb` operational evidence helper, preserving the completion map and earlier
source fixes. Three affected kernel contract files pass 80 cases in 0.643 seconds wall time;
whole-tree lint and strict kernel types pass. This is bounded kernel proof, without a full
coverage, pinned-upstream, real graph, Wema-runtime or release claim. No version, published
artifact, installed Wema dependency or shared/host tip changed.

Next joined dependencies: claude-0's native control-plane/rail readers, claude-3's exact
`c487ef5e` native monitoring consumers and the normal combined AEOS artifact/pin. Global
registrations, provisional migrations/schema profile and generated contracts must agree before
Wema runtime verification. P1-P6 is now reported through `14b6fcf6` and remains an ordered
commercial migration block; preserve its original partial-gate results. Commercial's broader
assignment is still dispatched, not silently counted complete. Complete all applicable
remaining workflows and acceptance evidence through these named owners; none is deferred to
an unspecified later project.
