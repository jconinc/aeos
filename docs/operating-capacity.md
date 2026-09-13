# Operating capacity and solo operation

Recorded 13 September 2026 following John's PFV forecast discussion. Read this before
estimating support staffing, founder hours or revenue constrained by operational capacity.
This is planning guidance. The implementation specification and each host's current policy
continue to govern actions; this note grants no additional access, approval or autonomy.

## Planning baseline

Use solo operation as the starting assumption for John's PFV scenario. The broader AEOS
design records permanent solo operation in decision D-04 of
`future_projects/aeos/AEOS_BUSINESS_LAYER.md` (4 July 2026). That design intent is not proof
of any throughput or a substitute for the consuming product's current authority rules.

Evaluate the complete system: AEOS, the host's domain operations and records, its CLI and
model gateway, and the WLG execution pipeline. A kernel that delegates an effect to its host
has not thereby delegated it to an employee. Complex cases are candidates for stronger model
assistance with appropriate context, authorized tools and independently checked results.
They are not inherently human jobs. Conversely, record access and a stronger model do not
establish that every result is correct or that an external effect can be confirmed.

Do not assume a support hire at a customer-count or revenue threshold. Do not assign zero
owner time either. Keep measured workload, unmeasured assumptions and conditional stress
scenarios separate. An approval step may take owner time even when the system does all the
investigation and preparation; it does not imply a human must solve the whole ticket.

## Prevent the need for support

The customer's first path is a clear, complete product workflow. Apply the existing
[Product Design Canon](../../MultiAgentCommunication/docs/agent_context/product_design_canon_charter.md)
and its [engagement policy](../../MultiAgentCommunication/docs/agent_context/product_engagement_policy.md):
people should understand, complete, recover and undo without routine human rescue. Agents
should resolve design questions from existing evidence and the canon before asking the owner.
This applies existing guidance; it does not amend the canon or supersede product authority.

The PFV factory specs make the mechanisms concrete:

- [Presentation Help](../../PetFoodVerify-Context/specs/presentation_help.txt): explain the
  screen and unfamiliar fields in context; give actionable recovery; bind onboarding to a
  real completion action. An explanation or empty help field is not proof of understanding.
- [Presentation Psychology](../../PetFoodVerify-Context/specs/presentation_psychology.txt)
  and [Habit and Ease of Use](../../PetFoodVerify-Context/specs/habit.txt): control visible
  choices and steps, progressively reveal complexity, preserve input and provide appropriate
  progress feedback and recovery. Their structural budgets are not measured usability results.
- [Organic Growth](../../PetFoodVerify-Context/specs/organic_growth_ammendments.txt): enable
  useful, source-verifiable sharing after genuine value, with privacy and crisis suppression.
  This is not an additional viral multiplier on top of the same marketing playbook mechanism.
- [Instrumentation](../../PetFoodVerify-Context/specs/instrumentation.txt): observe funnel
  completion, contextual feedback, trustworthy comparisons and data readiness so repeated
  confusion can become a product improvement rather than permanent support labor.

Provide the shortest sufficient explanation at the point of need. A brief optional video or
walkthrough can demonstrate a task; keep a usable text alternative and avoid requiring a call,
video or lengthy help search before users can proceed or ask for help. Video production is
explicitly outside Presentation Help's scope: the spec does not establish that videos exist.
AEOS can assist where the interface and contextual help are insufficient; current authority
still governs its operations. The aim is successful customer progress, not maximizing bot use
or keeping support contact counts artificially low.

Model two separate effects: fewer users need assistance, and fewer assisted cases need owner
handling. Do not count the same avoided work once as better UX and again as AI deflection.
Measure task completion and abandonment as well as help use: no ticket can also mean the user
gave up. Keep time to first value, paid conversion, renewal and referrals as separate outcomes.
The Habit spec explicitly says its rules enforce product-hypothesis structure, not discovery
truth. Until behavior is observed, revenue improvements are sensitivities, not established
returns from having a canon or passing structural gates. Historical example copy does not
override current PFV requirements, particularly its records-not-advice restrictions.

## Implementation evidence at this review

Source inspection covered AEOS `9785300dd904ada1e7b6a1a59bc58b2e484c7247`, Wema
`ca44a76c5b5b69d2d0c84f1ff3f7d5503c51800d` and MultiAgentCommunication
`1c3f5dd0ec32af5e1d904f51dcfc3f3bf032ece4`. These are inspected revisions, not updated
compatibility pins or a claim about the installed version. Test source was read; no test,
live support workload or deployment was run for this note.
The MultiAgent pipeline files had working-tree edits during retention; their references below
were checked against the named committed versions. Those concurrent edits are not accepted or
modified by this review.

| Area | Implemented evidence | Limit of that evidence |
| --- | --- | --- |
| Decisions | `src/aeos_kernel/engine.py` verifies packets and eligible choices, resolves validated entailment, and checks model identity, citations, budgets and reverse-order agreement. `tests/test_engine.py` contains positive and refusal controls. | Bounded choice does not supply a missing business operation; agreement is not proof of factual correctness. |
| Reply quality | Wema's `packages/commercial-guidance/wema_commercial_guidance/reply_loop.py` implements checks, model scoring, bounded repair, template fallback and named escalation. Its `tests/test_reply_loop.py` contains repair and fallback controls. | This library has no production caller for `run_reply_loop` in the inspected Wema source. The automatic `support_reply_draft` handler remains described work in `docs/mailbox-management-spec.md` packets 8/9. Recheck the current source before carrying this gap forward. |
| Agent preparation | Wema's `apps/api/wema_api/routers/desk_mail.py` accepts authorized agent reply previews and marks their source as agent-prepared. | This is an existing preparation path, not an unattended draft worker or authority to send. |
| Customer recovery | Wema's `apps/worker/wema_worker/handlers/order_refund.py` and `mail_reply.py` implement attested refunds and replies; `test_desk_mail.py`, `test_mail_reply.py` and `test_mail_recovery_completion.py` cover authorization, duplicate handling and confirmed outcomes. | The current Wema policy requires a human attestation. PFV needs its own native integration and policy; a Wema adapter is not proof of PFV support readiness. |
| Graph and model integration | Wema's `apps/worker/wema_worker/local_aeos_runner.py` supplies its local model gateway to the growth decision path and retains decision evidence. | An operator-initiated subscription session is not evidence of unattended service availability. |
| Pipeline execution | MultiAgentCommunication's `claude_coord/wlg/decision_engine/canon_decision.py` and `wlg/pipeline/{generation,commit}.py` provide model judgment, generation and controlled commits. | Inspect the specific task's registered caller and result; these mechanisms alone do not prove a customer-ticket-to-shipped-fix workflow. |

## Classify what remains

For an unresolved task, record which of these explanations applies before assigning staff:

- **Integration:** the operation or model-assisted path exists but the consuming workflow is
  not connected. Identify the missing caller/adapter and an observable completion condition.
- **Authority:** current policy reserves the decision or confirmation for a person. Retain
  that boundary and count the person's review time. Do not call routine technical access a
  human judgment, and do not let model output become its own approval.
- **Evidence:** the available records cannot establish the needed fact. Obtain an authoritative
  read or ask the customer/provider. Waiting for an answer is elapsed time, not continuous
  founder labor. For example, Wema's mail worker stops on uncertain SMTP acceptance; without
  confirming evidence, another model call cannot establish whether a retry would duplicate mail.
- **Resolution quality:** the permitted automated attempts still fail the task's checks.
  Retain the reason and measure actual owner handling time. A retry should address the known
  failure; a recurring class may justify a small tool, context or workflow improvement.

The reply-drafting connection above is a recorded implementation follow-up, not a request to
start a new support engine. When that work is authorized, use the existing gateway, loop,
worker registration and receipt storage. Establish the native caller and focused end-to-end
success/failure controls before marking it connected. Preserve current send/refund authority.

## Measure owner workload

Use existing host records and receipts where available. For each task family, distinguish:

1. Incoming unique cases, including repeats and reopened cases without double counting.
2. Verified completions without owner handling; a drafted response is not a resolution.
3. Cases needing only a reserved approval, and actual active review minutes.
4. Cases needing investigation or repair by the owner, their reasons and active minutes.
5. Waiting on the customer/provider, unresolved age and breaches of the service promise.
6. Reopens, corrections, failed/duplicate effects and customer confirmation where applicable.

Count all founder work within the proposed hours: reviews, exceptions, relationships,
measurement, and technical supervision or repairs. If engineering or another service is
funded separately, disclose its labor and cost rather than hiding it outside the time budget.
Keep model/compute costs and runtime availability separate from human hours.

For a measured period:

`owner hours = (approval minutes + exception-handling minutes + other owner-work minutes) / 60`

Use mutually exclusive time categories. When forecasting from rates, show the task-family
denominator, observation window, approval rate, exception rate and active handling time.
Unknown inputs should be labeled unmeasured, not set to zero or presented as established
support-deflection rates. Until observations exist, publish clearly labeled workload
sensitivities without asserting a calibrated probability or proven solo capacity.

If workload persistently exceeds the owner's sustainable budget, first locate repeated
failures and test bounded automation or a reduced cadence. Paid help remains a possible
owner choice supported by evidence, not the presumed operating model. More automation
capacity does not independently increase customer demand, conversion or retention.
