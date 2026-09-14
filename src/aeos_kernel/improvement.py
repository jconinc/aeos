"""From a repeated customer difficulty to a verified fix, without carrying the customer along.

What travels into the build pipeline is a count and a reason code, plus opaque references
back to the records that stay where they are. The customer's own words never do: a support
message belongs in the support system, not in a task description or a shared graph.

The other rule here is what counts as solved. A created task, a merged change or a model
saying so proves the work happened, not that the difficulty went away. The issue stays open
until a fresh observation in the same scope says the problem stopped recurring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required, thaw_json, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError

# Shapes that should never reach a shared task description. Each is a thing a person is,
# not a thing a product does.
_IDENTIFIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("a telephone number", re.compile(r"(?:\+\d[\d\s().-]{7,}\d)")),
    ("a long digit sequence", re.compile(r"\b\d{9,}\b")),
    ("a quoted message", re.compile(r"[\"“][^\"”]{40,}[\"”]")),
)


class DifficultyKind(StrEnum):
    """What kind of trouble the customer hit. A closed set, so it can be counted."""

    CANNOT_COMPLETE_TASK = "cannot_complete_task"
    WRONG_RESULT = "wrong_result"
    UNCLEAR_INSTRUCTION = "unclear_instruction"
    MISSING_CAPABILITY = "missing_capability"
    ACCESS_OR_ACCOUNT = "access_or_account"
    BILLING_OR_ORDER = "billing_or_order"
    PERFORMANCE_OR_ERROR = "performance_or_error"


class ObservationCoverage(StrEnum):
    """How much of the window the producer actually read.

    This is what separates two identical zeros. A zero from a reading that covered the whole
    window means the trouble stopped. A zero from a reading that covered only what an index
    held, or a bounded subset of it, means nothing was found where the producer looked — and
    the difference decides whether anyone may be told their problem is fixed.
    """

    #: Every record in the window was read.
    COMPLETE = "complete"
    #: Only what the index holds was read; unindexed records were not consulted.
    INDEXED_ONLY = "indexed_only"
    #: A bounded subset was read, by limit, sampling or time.
    PARTIAL = "partial"

    @property
    def is_complete(self) -> bool:
        return self is ObservationCoverage.COMPLETE


class SummaryAuthority(StrEnum):
    """Who wrote the one-line summary, which decides how far it may be trusted.

    There is no value for customer-authored text. A customer's words are not summarized into
    a shared record at all; the record carries a count, a reason code and a reference back to
    where those words already live under their own rules.
    """

    #: No summary. The reason code and counts stand alone, which is always sufficient.
    ABSENT = "absent"
    #: One phrase the producer chose from a registered set. Nothing was composed, so nothing
    #: can have leaked into it.
    CLOSED_VOCABULARY = "closed_vocabulary"
    #: An agent composed it from aggregate facts. The identifier check is a backstop against
    #: an obvious mistake, never a certificate that the text is safe: the producer's own
    #: source and retention rules are what make that true.
    AGENT_AUTHORED = "agent_authored"


class ImprovementKind(StrEnum):
    HELP_CONTENT = "help_content"
    PRODUCT_FIX = "product_fix"
    PRODUCT_CHANGE = "product_change"


class ResolutionState(StrEnum):
    """Where one difficulty stands. Unknown is a real answer, distinct from resolved."""

    OPEN = "open"
    WORK_IN_PROGRESS = "work_in_progress"
    SHIPPED_UNVERIFIED = "shipped_unverified"
    #: Occurrences fell materially and people are still hitting it. This is a measurement
    #: about the population, and it is not grounds for telling anyone their problem is fixed.
    IMPROVED_NOT_RESOLVED = "improved_not_resolved"
    #: Occurrences reached zero across a complete measured window.
    VERIFIED_RESOLVED = "verified_resolved"
    UNKNOWN = "unknown"


def privacy_violations(text: str) -> tuple[str, ...]:
    """Identifier shapes found in text bound for a shared surface."""

    return tuple(label for label, pattern in _IDENTIFIER_PATTERNS if pattern.search(text))


def assert_shareable(text: str, field_name: str) -> str:
    """Refuse text carrying an obvious identifier or a quoted passage.

    This is a backstop, not a certification. It recognizes four shapes; text it accepts has
    only been found free of those, which is why a summary must also declare who wrote it
    (:class:`SummaryAuthority`). Nothing here makes customer-authored text safe to share,
    and no value of that enum admits any.
    """

    found = privacy_violations(text)
    if found:
        raise ContractError(
            f"{field_name} contains {found[0]}; a shared improvement record carries counts, "
            "reason codes and opaque references, never customer content"
        )
    return text


# References have their own closed syntax; a free-text identifier detector must not
# reinterpret a native UUID's decimal groups as a telephone/customer number. No value
# is normalized or encoded, and recognizing syntax does not establish source authority.
_SUPPORT_UUID_REFERENCE = re.compile(
    r"[a-z][a-z0-9_]{0,63}:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_SUPPORT_SIMPLE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def _support_reference(reference: str) -> str:
    """Preserve a native namespaced UUID or a bounded legacy opaque token exactly.

    The host supplies these handles from its own authorized records. Matching this grammar
    neither proves that a record exists nor permits a producer to wrap customer content in
    UUID-shaped text. Ordinary summaries retain the unchanged identifier backstop.
    """

    if _SUPPORT_UUID_REFERENCE.fullmatch(reference):
        return reference
    assert_shareable(reference, "support reference")
    if not _SUPPORT_SIMPLE_REFERENCE.fullmatch(reference):
        raise ContractError(
            "support reference must be an opaque token or a namespaced canonical UUID"
        )
    return reference


def assert_summary_admissible(
    *,
    summary: str,
    authority: SummaryAuthority,
    registered_phrases: frozenset[str] = frozenset(),
    max_length: int = 200,
) -> str:
    """Admit a summary on the strength of who wrote it, not on a pattern search.

    A closed-vocabulary summary must be one of the producer's registered phrases; composition
    is what creates the risk, so a record that composes nothing carries none. An
    agent-authored summary is bounded and passes the backstop check, and the caller remains
    responsible for it under its own source rules.
    """

    if authority is SummaryAuthority.ABSENT:
        if summary:
            raise ContractError("a summary marked absent must be empty")
        return ""
    required(summary, "operator_summary")
    if len(summary) > max_length:
        raise ContractError(
            f"operator_summary is {len(summary)} characters; at most {max_length} are "
            "admissible, because a line long enough to quote somebody is long enough to "
            "carry what they said"
        )
    if authority is SummaryAuthority.CLOSED_VOCABULARY:
        if summary not in registered_phrases:
            raise ContractError(
                "a closed-vocabulary summary must be one of the producer's registered "
                "phrases; free text cannot enter through this value"
            )
        return summary
    return assert_shareable(summary, "operator_summary")


@dataclass(frozen=True, slots=True)
class DifficultyObservation:
    """One aggregate of the same trouble, seen in one window.

    ``support_refs`` are opaque handles the support system can resolve. Nothing here can be
    read back into a person without that system's own authorization.
    """

    cluster_key: str
    product_slug: str
    difficulty_kind: DifficultyKind
    surface: str
    occurrence_count: int
    #: ``None`` where the producer's records cannot distinguish customers. That is the honest
    #: answer for a mailbox that keeps no sender identity, and retaining one to fill this
    #: field would be a worse outcome than leaving it unknown.
    distinct_customer_count: int | None
    window_started_at: datetime
    window_ended_at: datetime
    support_refs: tuple[str, ...] = ()
    operator_summary: str = ""
    summary_authority: SummaryAuthority = SummaryAuthority.ABSENT
    registered_phrases: tuple[str, ...] = ()
    #: How much of the window this reading covered. A producer reading an index that does not
    #: hold every record says so here rather than letting a count stand as the whole truth.
    coverage: ObservationCoverage = ObservationCoverage.COMPLETE
    #: The producer's own digest of what it read, so the same window can be recognized again.
    source_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("cluster_key", "product_slug", "surface"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.difficulty_kind, DifficultyKind):
            raise ContractError("difficulty kind is not recognized")
        if self.occurrence_count <= 0:
            raise ContractError("an observation counts at least one occurrence")
        if self.distinct_customer_count is not None:
            if self.distinct_customer_count <= 0:
                raise ContractError(
                    "a known distinct-customer count is at least one; use None for unknown"
                )
            if self.distinct_customer_count > self.occurrence_count:
                raise ContractError("distinct customers cannot exceed occurrences")
        utc(self.window_started_at, "window_started_at")
        utc(self.window_ended_at, "window_ended_at")
        if self.window_ended_at < self.window_started_at:
            raise ContractError("an observation window cannot end before it starts")
        if len(set(self.support_refs)) != len(self.support_refs):
            raise ContractError("support references must be unique")
        for reference in self.support_refs:
            required(reference, "support reference")
            _support_reference(reference)
        if not isinstance(self.summary_authority, SummaryAuthority):
            raise ContractError("summary authority is not recognized")
        if not isinstance(self.coverage, ObservationCoverage):
            raise ContractError("observation coverage is not recognized")
        if self.source_digest:
            digest(self.source_digest, "source_digest")
        if len(set(self.registered_phrases)) != len(self.registered_phrases):
            raise ContractError("registered phrases must be unique")
        assert_summary_admissible(
            summary=self.operator_summary,
            authority=self.summary_authority,
            registered_phrases=frozenset(self.registered_phrases),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "cluster_key": self.cluster_key,
            "product_slug": self.product_slug,
            "difficulty_kind": self.difficulty_kind.value,
            "surface": self.surface,
            "occurrence_count": self.occurrence_count,
            "distinct_customer_count": self.distinct_customer_count,
            "window_started_at": self.window_started_at.isoformat(),
            "window_ended_at": self.window_ended_at.isoformat(),
            "support_refs": list(self.support_refs),
            "operator_summary": self.operator_summary,
            "summary_authority": self.summary_authority.value,
            "coverage": self.coverage.value,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True, slots=True)
class RecurrenceThreshold:
    """When a difficulty is worth changing the product over.

    ``minimum_distinct_customers`` may be ``None``, which means this threshold asks only how
    often the trouble happened. Set it to a number and an observation that cannot count
    customers never satisfies it: an unknown count is not a low one, and it is not a high one
    either, so a threshold that depends on it stays unmet rather than guessing in either
    direction.
    """

    minimum_occurrences: int = 3
    minimum_distinct_customers: int | None = 2

    def __post_init__(self) -> None:
        if self.minimum_occurrences <= 0:
            raise ContractError("a recurrence threshold counts at least one occurrence")
        if self.minimum_distinct_customers is not None and self.minimum_distinct_customers <= 0:
            raise ContractError(
                "a distinct-customer threshold is at least one; use None to ask only about "
                "how often the trouble happened"
            )

    @classmethod
    def by_occurrences(cls, minimum_occurrences: int = 3) -> RecurrenceThreshold:
        """A threshold for a producer whose records cannot distinguish customers."""

        return cls(minimum_occurrences=minimum_occurrences, minimum_distinct_customers=None)

    def unmet_reason(self, observation: DifficultyObservation) -> str:
        """Why this observation does not meet the threshold, or ``""`` when it does."""

        if observation.occurrence_count < self.minimum_occurrences:
            return (
                f"{observation.occurrence_count} occurrence(s); "
                f"{self.minimum_occurrences} are needed before this is a pattern"
            )
        if self.minimum_distinct_customers is None:
            return ""
        if observation.distinct_customer_count is None:
            return (
                "this threshold asks how many distinct customers hit it, and the producer "
                "cannot count that without retaining an identity it does not keep"
            )
        if observation.distinct_customer_count < self.minimum_distinct_customers:
            return (
                f"{observation.distinct_customer_count} distinct customer(s); "
                f"{self.minimum_distinct_customers} are needed"
            )
        return ""

    def met_by(self, observation: DifficultyObservation) -> bool:
        return not self.unmet_reason(observation)


@dataclass(frozen=True, slots=True)
class ImprovementRequest:
    """The safe hand-off into the existing requirement and task pipeline."""

    request_id: str
    cluster_key: str
    product_slug: str
    improvement_kind: ImprovementKind
    title: str
    problem_statement: str
    requirement_ref: str
    raised_at: datetime
    observation_digest: str
    external_task_ref: str = ""
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "cluster_key",
            "product_slug",
            "title",
            "problem_statement",
            "requirement_ref",
        ):
            required(str(getattr(self, name)), name)
        if not isinstance(self.improvement_kind, ImprovementKind):
            raise ContractError("improvement kind is not recognized")
        utc(self.raised_at, "raised_at")
        digest(self.observation_digest, "observation_digest")
        assert_shareable(self.title, "improvement title")
        assert_shareable(self.problem_statement, "problem_statement")
        if self.external_task_ref:
            required(self.external_task_ref, "external_task_ref")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ContractError("improvement evidence references must be unique")

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "cluster_key": self.cluster_key,
            "product_slug": self.product_slug,
            "improvement_kind": self.improvement_kind.value,
            "title": self.title,
            "problem_statement": self.problem_statement,
            "requirement_ref": self.requirement_ref,
            "raised_at": self.raised_at.isoformat(),
            "observation_digest": self.observation_digest,
            "external_task_ref": self.external_task_ref,
            "evidence_refs": list(self.evidence_refs),
        }


def raise_improvement(
    *,
    observation: DifficultyObservation,
    threshold: RecurrenceThreshold,
    improvement_kind: ImprovementKind,
    title: str,
    problem_statement: str,
    requirement_ref: str,
    raised_at: datetime,
) -> ImprovementRequest | None:
    """Turn a recurring difficulty into a request, or decline because it has not recurred.

    Returns ``None`` when the threshold is not met — one report is a report, not yet a
    pattern, and the record stays in support where it can still be answered.
    """

    if not threshold.met_by(observation):
        return None
    observation_digest = stable_fingerprint(observation.as_dict())
    identity = stable_fingerprint(
        {"cluster": observation.cluster_key, "at": raised_at.isoformat()}
    )
    return ImprovementRequest(
        request_id=f"improvement_{identity[:24]}",
        cluster_key=observation.cluster_key,
        product_slug=observation.product_slug,
        improvement_kind=improvement_kind,
        title=title,
        problem_statement=problem_statement,
        requirement_ref=requirement_ref,
        raised_at=raised_at,
        observation_digest=observation_digest,
    )


@dataclass(frozen=True, slots=True)
class ShippedChange:
    """The exact release that carried the improvement."""

    request_id: str
    release_ref: str
    verification_ref: str
    shipped_at: datetime
    change_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("request_id", "release_ref", "verification_ref"):
            required(str(getattr(self, name)), name)
        utc(self.shipped_at, "shipped_at")
        if len(set(self.change_refs)) != len(self.change_refs):
            raise ContractError("change references must be unique")


@dataclass(frozen=True, slots=True)
class ResolutionAssessment:
    """Whether the difficulty actually stopped, and how that was established."""

    cluster_key: str
    state: ResolutionState
    reason: str
    before_rate_per_week: float | None = None
    after_rate_per_week: float | None = None
    observation_window_complete: bool = False

    def __post_init__(self) -> None:
        required(self.cluster_key, "cluster_key")
        required(self.reason, "resolution reason")
        if not isinstance(self.state, ResolutionState):
            raise ContractError("resolution state is not recognized")
        for name in ("before_rate_per_week", "after_rate_per_week"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ContractError(f"{name} must be nonnegative")

    @property
    def customer_follow_up_permitted(self) -> bool:
        """Only tell a customer it is fixed once an observation says it is."""

        return self.state is ResolutionState.VERIFIED_RESOLVED


def assess_resolution(
    *,
    cluster_key: str,
    request: ImprovementRequest | None,
    shipped: ShippedChange | None,
    before_rate_per_week: float | None,
    after_rate_per_week: float | None,
    observation_window_complete: bool,
    after_coverage: ObservationCoverage = ObservationCoverage.COMPLETE,
    improvement_ratio: float = 0.5,
) -> ResolutionAssessment:
    """Decide what may be claimed. A shipped change alone claims nothing about the customer.

    The identities are bound rather than trusted: a request for another difficulty, or a
    release raised against a different request, is refused instead of quietly producing an
    assessment about work that was never connected to this trouble.

    Resolution means a measured zero across a complete window, read by a reading that
    covered that window. A zero from an index that does not hold every record is "nothing was
    found where we looked", which is not the same sentence. A halving is a real result about
    the population and is reported as one, but people are still hitting the problem, so it is
    not grounds for telling any of them theirs is fixed.
    """

    required(cluster_key, "cluster_key")
    if not isinstance(after_coverage, ObservationCoverage):
        raise ContractError("observation coverage is not recognized")
    if not 0 < improvement_ratio <= 1:
        raise ContractError("improvement ratio must fall in (0, 1]")
    if request is not None and request.cluster_key != cluster_key:
        raise ContractError(
            f"improvement {request.request_id} was raised for {request.cluster_key!r}, not "
            f"{cluster_key!r}; an assessment cannot borrow another difficulty's work"
        )
    if shipped is not None:
        if request is None:
            raise ContractError(
                "a shipped change cannot be assessed without the improvement it was raised "
                "against"
            )
        if shipped.request_id != request.request_id:
            raise ContractError(
                f"release {shipped.release_ref} was shipped for {shipped.request_id}, not "
                f"{request.request_id}; it says nothing about this difficulty"
            )
    if request is None:
        return ResolutionAssessment(
            cluster_key=cluster_key,
            state=ResolutionState.OPEN,
            reason="no improvement has been raised for this difficulty",
        )
    if shipped is None:
        return ResolutionAssessment(
            cluster_key=cluster_key,
            state=ResolutionState.WORK_IN_PROGRESS,
            reason=(
                f"{request.request_id} is raised against {request.requirement_ref}; nothing has "
                "shipped yet, so the difficulty is unchanged"
            ),
        )
    if not observation_window_complete:
        return ResolutionAssessment(
            cluster_key=cluster_key,
            state=ResolutionState.SHIPPED_UNVERIFIED,
            reason=(
                f"{shipped.release_ref} shipped and passed {shipped.verification_ref}, but the "
                "observation window has not closed; whether customers stopped hitting this is "
                "not yet known"
            ),
            before_rate_per_week=before_rate_per_week,
            after_rate_per_week=after_rate_per_week,
        )
    if before_rate_per_week is None or after_rate_per_week is None:
        return ResolutionAssessment(
            cluster_key=cluster_key,
            state=ResolutionState.UNKNOWN,
            reason=(
                "the before or after rate was not measured; a missing observation is unknown, "
                "not zero"
            ),
            before_rate_per_week=before_rate_per_week,
            after_rate_per_week=after_rate_per_week,
            observation_window_complete=True,
        )
    if before_rate_per_week == 0:
        return ResolutionAssessment(
            cluster_key=cluster_key,
            state=ResolutionState.UNKNOWN,
            reason="the difficulty was not occurring before the change, so nothing can be shown",
            before_rate_per_week=before_rate_per_week,
            after_rate_per_week=after_rate_per_week,
            observation_window_complete=True,
        )
    if after_rate_per_week == 0 and not after_coverage.is_complete:
        return ResolutionAssessment(
            cluster_key=cluster_key,
            state=ResolutionState.UNKNOWN,
            reason=(
                f"no occurrences were found, but the reading covered {after_coverage.value} "
                "records rather than the whole window. Nothing was found where we looked, "
                "which is not the same as the trouble having stopped"
            ),
            before_rate_per_week=before_rate_per_week,
            after_rate_per_week=after_rate_per_week,
            observation_window_complete=True,
        )
    if after_rate_per_week == 0:
        return ResolutionAssessment(
            cluster_key=cluster_key,
            state=ResolutionState.VERIFIED_RESOLVED,
            reason=(
                f"occurrences reached zero across a complete window after "
                f"{shipped.release_ref}, from {before_rate_per_week:.1f} a week before"
            ),
            before_rate_per_week=before_rate_per_week,
            after_rate_per_week=after_rate_per_week,
            observation_window_complete=True,
        )
    if after_rate_per_week <= before_rate_per_week * improvement_ratio:
        return ResolutionAssessment(
            cluster_key=cluster_key,
            state=ResolutionState.IMPROVED_NOT_RESOLVED,
            reason=(
                f"occurrences fell from {before_rate_per_week:.1f} to {after_rate_per_week:.1f} "
                f"a week after {shipped.release_ref}. Fewer people hit this; it still happens, "
                "so nobody can be told theirs is fixed"
            ),
            before_rate_per_week=before_rate_per_week,
            after_rate_per_week=after_rate_per_week,
            observation_window_complete=True,
        )
    return ResolutionAssessment(
        cluster_key=cluster_key,
        state=ResolutionState.SHIPPED_UNVERIFIED,
        reason=(
            f"{shipped.release_ref} shipped but occurrences are still "
            f"{after_rate_per_week:.1f} a week against {before_rate_per_week:.1f} before; the "
            "difficulty has not been shown to be resolved"
        ),
        before_rate_per_week=before_rate_per_week,
        after_rate_per_week=after_rate_per_week,
        observation_window_complete=True,
    )


@dataclass(frozen=True, slots=True)
class FollowUpPlan:
    """What to tell people, and where. Never a claim the evidence does not support."""

    cluster_key: str
    notify_support_refs: tuple[str, ...]
    help_content_ref: str
    message_kind: str
    permitted: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required(self.cluster_key, "cluster_key")
        required(self.message_kind, "message_kind")
        required(self.reason, "follow-up reason")
        object.__setattr__(self, "details", immutable_json_object(self.details, "details"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "cluster_key": self.cluster_key,
            "notify_support_refs": list(self.notify_support_refs),
            "help_content_ref": self.help_content_ref,
            "message_kind": self.message_kind,
            "permitted": self.permitted,
            "reason": self.reason,
            "details": thaw_json(self.details),
        }


def plan_follow_up(
    *,
    assessment: ResolutionAssessment,
    observation: DifficultyObservation,
    help_content_ref: str = "",
) -> FollowUpPlan:
    """Prepare the follow-up the evidence actually supports, for the right people.

    The observation's references decide who hears from us, so an assessment of one
    difficulty paired with another's observation would write to people who never reported
    this trouble. The two are bound rather than assumed to match.
    """

    if assessment.cluster_key != observation.cluster_key:
        raise ContractError(
            f"assessment is about {assessment.cluster_key!r} and the observation about "
            f"{observation.cluster_key!r}; a follow-up would reach people who reported "
            "something else"
        )
    if assessment.customer_follow_up_permitted:
        return FollowUpPlan(
            cluster_key=assessment.cluster_key,
            notify_support_refs=observation.support_refs,
            help_content_ref=help_content_ref,
            message_kind="resolved_follow_up",
            permitted=True,
            reason=assessment.reason,
        )
    return FollowUpPlan(
        cluster_key=assessment.cluster_key,
        notify_support_refs=(),
        help_content_ref=help_content_ref,
        message_kind="no_customer_message",
        permitted=False,
        reason=(
            f"the difficulty is {assessment.state.value}: {assessment.reason}. Telling a "
            "customer it is fixed would claim more than has been observed."
        ),
    )


__all__ = [
    "DifficultyKind",
    "DifficultyObservation",
    "FollowUpPlan",
    "ImprovementKind",
    "ImprovementRequest",
    "ObservationCoverage",
    "RecurrenceThreshold",
    "ResolutionAssessment",
    "ResolutionState",
    "ShippedChange",
    "SummaryAuthority",
    "assert_shareable",
    "assert_summary_admissible",
    "assess_resolution",
    "plan_follow_up",
    "privacy_violations",
    "raise_improvement",
]
