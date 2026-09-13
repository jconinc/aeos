# Complete AEOS business operation through Wema Desk

Owner: John. Adopted execution objective: 13 September 2026.

The objective below is preserved verbatim from the supplied attachment. The [execution plan](business-completion-plan.md) and existing Wema progress tracker record implementation; this goal is not a new approval or activation record.

Fully implement the applicable AEOS business capabilities and integrate them into Wema Desk, making Wema the first
  complete working product operated through AEOS. Cover customer acquisition, marketing, sales, customer support,
  fulfillment and recovery, monitoring, financial performance and continuous improvement. Preserve Wema’s existing
  functionality and simple user experience, using clean, economical engineering and efficient verification. No
  applicable capability should remain assigned to an unspecified “later.”

  The system should carry routine preparation, investigation, execution and follow-through. Liz and John should receive
  clear, prepared decisions and exceptions that require their involvement, with enough context to understand the task
  and its consequence without understanding the underlying software.

  Deliver this through the following principles:

  - One coherent Desk experience. Integrate into existing screens, cards and workflows wherever they fit. Each item
    explains what happened, why it matters, the recommended next step and what that action will do. Support comments,
    disagreement, deferral and returning later without losing work. Show additional detail when needed, while keeping
    the initial view focused. The limit on visible founder decisions must not limit background throughput.

  - Complete customer and business workflows. Connect research and playbooks to preparation, appropriate distribution,
    customer responses, commercial outcomes and learning. Connect customer difficulties to resolution, improved help and
    verified product fixes. Include the operational monitoring and recovery necessary to keep those workflows
    dependable.

  - Simple, elegant engineering. Reuse the existing AEOS kernel, Wema domain services, model gateway, CLI, persistence
    and pipeline. Give each responsibility a clear owner. Add abstractions only when a concrete consumer needs them.
    Prefer small, cohesive changes and explicit data flow; remove redundant machinery when doing so preserves behavior.

  - Use workers where they help. Run repeatable, scheduled, expensive or long-running work through the existing
    background workers. Use bounded concurrency for independent tasks, with clear retry, duplicate prevention,
    cancellation and recovery behavior. Keep customer interactions responsive. Use deterministic code for bookkeeping
    and established rules, and models for tasks that benefit from judgment or language understanding.

  - Automate responsibly. Prepare grounded answers and perform permitted routine actions. Review unnecessary manual
    steps as part of implementation, while preserving genuine human decisions and established privacy, clinical,
    financial and publication boundaries. Investigate failures before asking Liz or John to intervene.

  - Make tests fast and meaningful. Run cheap prerequisites first, select tests by actual affected behavior and reuse
    valid evidence for unchanged inputs. Use parallel test workers where independent, with isolated native databases and
    controlled resources. Measure slow tests and fix avoidable setup, repeated work and contention. Preserve meaningful
    success, refusal and recovery controls and required coverage.

  Completion is measured by:

  1. Full requirement coverage: every applicable requirement has an implementation, a named production consumer and
     acceptance evidence. Exclusions have an explicit applicability reason; unresolved work remains incomplete.

  2. Verified journeys: each workflow is demonstrated from trigger through action, outcome and follow-up, including
     relevant failure and recovery cases.

  3. Usable Desk integration: representative users can explain what a task means, act on it and understand the result
     without our narration. Record confusion, completion time and actual owner effort.

  4. Effective monitoring: each monitored condition has a detection window, response and clearing condition. Missing
     observations cannot be reported as healthy operation.

  5. Measured engineering efficiency: retain test selection reasons, executed versus reused evidence, worker
     configuration and elapsed time. Investigate overruns before repeating expensive runs.

  6. Safe delivery: deploy verified increments that preserve existing Wema behavior and records, with compatible
     upgrades, recovery evidence and maintained Desk/CLI instructions.

  The intended result is a complete operating system behind a calm, understandable Desk—substantial capability with a
  small human workload, clean code and fast, trustworthy feedback during development.
