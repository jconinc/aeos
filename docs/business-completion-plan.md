# Complete AEOS through Wema

Owner-directed scope, 13 September 2026. Implementation is active; completion is unproven.
The [full goal](business-completion-goal.md) is the acceptance target. Delivery packets order
the work; they do not postpone applicable business capabilities to an unspecified later release.

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

## Immediate next implementation packet

The first new feature packet is the missing support drafting connection. Inspect the existing
mailbox producer, model gateway task/context types, draft persistence, scoring repository and
Desk read path together. Reconcile inbound-message privacy and the exact provider requirements
in the same contract change. Implement and test with fictional provider and mail transports in
an owned private database. Connect the existing worker and UI; do not introduce another support
engine. Provider enablement is a separate deployment/configuration step with its actual evidence.

The complete goal remains active throughout this packet. Finishing it will not establish
completion of monitoring, other business workflows or the requirement map.
