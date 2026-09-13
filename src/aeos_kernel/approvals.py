"""Approvals: the parked move waiting on a person, and what that person is shown.

Parking is the approval gate. A runner that is not confident enough does not guess — it
routes one item to a person with the exact action that will run, written so it can be read
without knowing anything about the runner that produced it.

One unresolvable item never parks a whole run: the rest drains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required, thaw_json, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.modules import MoveFamily
from aeos_kernel.moves import Move, MoveDecision


class ApprovalStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ParkCause(StrEnum):
    """Why this item is in front of a person rather than already done."""

    BELOW_CONFIDENCE_GATE = "below_confidence_gate"
    ALWAYS_PARKS = "always_parks"
    SEED_MOVE = "seed_move"
    AMBIGUOUS = "ambiguous"
    POLICY_RESERVED = "policy_reserved"


@dataclass(frozen=True, slots=True)
class ParkRecord:
    """The park itself: what was undecided, and the bounded set offered."""

    park_id: str
    move_id: str
    product_slug: str
    move_type: str
    cause: ParkCause
    reason_operator: str
    choice_set: tuple[str, ...]
    parked_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in ("park_id", "move_id", "product_slug", "move_type", "reason_operator"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.cause, ParkCause):
            raise ContractError("park cause is not recognized")
        if len(self.choice_set) < 1:
            raise ContractError("a park must offer at least one choice besides declining")
        if len(set(self.choice_set)) != len(self.choice_set):
            raise ContractError("park choices must be unique")
        for choice in self.choice_set:
            required(choice, "park choice")
        utc(self.parked_at, "parked_at")
        utc(self.expires_at, "expires_at")
        if self.expires_at <= self.parked_at:
            raise ContractError("a park must expire after it was created")
        # A stack trace is not an approval-inbox sentence.
        if len(self.reason_operator) > 400:
            raise ContractError("park reason must stay short enough to read in an inbox")

    @property
    def offered_choices(self) -> tuple[str, ...]:
        """Declining is always available, so it is always in the offered set."""

        return (*self.choice_set, "decline")

    def as_dict(self) -> dict[str, Any]:
        return {
            "park_id": self.park_id,
            "move_id": self.move_id,
            "product_slug": self.product_slug,
            "move_type": self.move_type,
            "cause": self.cause.value,
            "reason_operator": self.reason_operator,
            "choice_set": list(self.offered_choices),
            "parked_at": self.parked_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class Approval:
    """What a person was shown, and what they decided about it."""

    approval_id: str
    move_id: str
    park_id: str
    status: ApprovalStatus
    reason_operator: str
    payload_preview: dict[str, Any]
    payload_preview_digest: str
    choice_set: tuple[str, ...]
    chosen: str = ""
    decided_by: str = ""
    decided_at: datetime | None = None
    decision_note: str = ""

    def __post_init__(self) -> None:
        for name in ("approval_id", "move_id", "park_id", "reason_operator"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.status, ApprovalStatus):
            raise ContractError("approval status is not recognized")
        if not self.choice_set:
            raise ContractError("an approval must record the choices offered")
        if self.status in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            required(self.chosen, "chosen")
            required(self.decided_by, "decided_by")
            if self.decided_at is None:
                raise ContractError("a decided approval records when it was decided")
            if self.chosen not in self.choice_set:
                raise ContractError("the chosen option was not among those offered")
        elif self.chosen or self.decided_by or self.decided_at is not None:
            raise ContractError("an undecided approval carries no decision")
        if self.decided_at is not None:
            utc(self.decided_at, "decided_at")
        digest(self.payload_preview_digest, "payload_preview_digest")
        object.__setattr__(
            self,
            "payload_preview",
            immutable_json_object(self.payload_preview, "payload_preview"),
        )
        if self.payload_preview_digest != stable_fingerprint(thaw_json(self.payload_preview)):
            raise ContractError("payload preview digest does not match the previewed payload")

    def as_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "move_id": self.move_id,
            "park_id": self.park_id,
            "status": self.status.value,
            "reason_operator": self.reason_operator,
            "payload_preview": thaw_json(self.payload_preview),
            "payload_preview_digest": self.payload_preview_digest,
            "choice_set": list(self.choice_set),
            "chosen": self.chosen,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_note": self.decision_note,
        }


def park_move(
    *,
    move: Move,
    cause: ParkCause,
    reason_operator: str,
    choice_set: tuple[str, ...],
    payload_preview: dict[str, Any],
    parked_at: datetime,
    park_ttl_hours: int,
) -> tuple[ParkRecord, Approval]:
    """Route one move to a person, with the exact action they are approving."""

    if move.decision is not MoveDecision.PARKED:
        raise ContractError("only a parked move creates an approval")
    if park_ttl_hours <= 0:
        raise ContractError("park TTL must be positive")
    park_id = "park_" + stable_fingerprint({"move": move.move_id, "cause": cause.value})[:24]
    record = ParkRecord(
        park_id=park_id,
        move_id=move.move_id,
        product_slug=move.product_slug,
        move_type=move.move_type,
        cause=cause,
        reason_operator=reason_operator,
        choice_set=choice_set,
        parked_at=parked_at,
        expires_at=parked_at + timedelta(hours=park_ttl_hours),
    )
    preview_digest = stable_fingerprint(payload_preview)
    approval = Approval(
        approval_id="approval_" + stable_fingerprint({"park": park_id})[:24],
        move_id=move.move_id,
        park_id=park_id,
        status=ApprovalStatus.REQUESTED,
        reason_operator=reason_operator,
        payload_preview=payload_preview,
        payload_preview_digest=preview_digest,
        choice_set=record.offered_choices,
    )
    return record, approval


@dataclass(frozen=True, slots=True)
class ResumeOutcome:
    """What the parked move becomes once its approval resolves."""

    decision: MoveDecision
    reason: str
    execute_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required(self.reason, "resume reason")
        object.__setattr__(
            self,
            "execute_payload",
            immutable_json_object(self.execute_payload, "execute_payload"),
        )


def resume_from_approval(*, approval: Approval, now: datetime) -> ResumeOutcome:
    """Resume exactly what the person saw — never a fresh derivation that could differ.

    Approving runs the previewed payload. Rejecting declines with the person's own reason.
    Letting it expire holds: silence is not consent, and it is not a refusal either.
    """

    utc(now, "now")
    if approval.status is ApprovalStatus.APPROVED:
        if approval.payload_preview_digest != stable_fingerprint(
            thaw_json(approval.payload_preview)
        ):
            raise ContractError("the approved payload no longer matches what was previewed")
        return ResumeOutcome(
            decision=MoveDecision.SHIP,
            reason=f"approved by {approval.decided_by} as {approval.chosen}",
            execute_payload=thaw_json(approval.payload_preview),
        )
    if approval.status is ApprovalStatus.REJECTED:
        note = approval.decision_note or f"rejected by {approval.decided_by}"
        return ResumeOutcome(decision=MoveDecision.DECLINE, reason=note)
    if approval.status is ApprovalStatus.EXPIRED:
        return ResumeOutcome(
            decision=MoveDecision.HOLD,
            reason="the approval window passed without a decision; the move is held, not declined",
        )
    return ResumeOutcome(
        decision=MoveDecision.PARKED,
        reason="still waiting on an operator decision",
    )


def expire_overdue(
    approvals: tuple[Approval, ...], parks: tuple[ParkRecord, ...], *, now: datetime
) -> tuple[Approval, ...]:
    """Mark the approvals whose window has passed. Only a parked decision expires."""

    utc(now, "now")
    deadlines = {record.park_id: record.expires_at for record in parks}
    expired: list[Approval] = []
    for approval in approvals:
        if approval.status is not ApprovalStatus.REQUESTED:
            continue
        deadline = deadlines.get(approval.park_id)
        if deadline is not None and now >= deadline:
            expired.append(
                Approval(
                    approval_id=approval.approval_id,
                    move_id=approval.move_id,
                    park_id=approval.park_id,
                    status=ApprovalStatus.EXPIRED,
                    reason_operator=approval.reason_operator,
                    payload_preview=thaw_json(approval.payload_preview),
                    payload_preview_digest=approval.payload_preview_digest,
                    choice_set=approval.choice_set,
                    decision_note=approval.decision_note,
                )
            )
    return tuple(expired)


@dataclass(frozen=True, slots=True)
class DrainResult:
    """A run that parked one item and finished the rest."""

    proceeded: tuple[Move, ...]
    parked: tuple[Move, ...]

    @property
    def drained_count(self) -> int:
        return len(self.proceeded)


def drain_partially(moves: tuple[Move, ...]) -> DrainResult:
    """Separate the parked items from the rest. Partial drains are the rule, not a fallback."""

    return DrainResult(
        proceeded=tuple(item for item in moves if item.decision is not MoveDecision.PARKED),
        parked=tuple(item for item in moves if item.decision is MoveDecision.PARKED),
    )


@dataclass(frozen=True, slots=True)
class ApprovalLoadProjection:
    """How many decisions enabling this module would put in front of a person each week."""

    product_slug: str
    module_key: str
    projected_parks_per_week: float
    headroom_parks_per_week: float
    #: Families with scheduled work whose park rate nobody has measured. While this is
    #: non-empty the projection is a floor, not a number, and it certifies nothing.
    unmeasured_move_types: tuple[str, ...] = ()
    by_move_type: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required(self.product_slug, "product_slug")
        required(self.module_key, "module_key")
        if self.projected_parks_per_week < 0 or self.headroom_parks_per_week < 0:
            raise ContractError("projected and available approval load must be nonnegative")
        if len(set(self.unmeasured_move_types)) != len(self.unmeasured_move_types):
            raise ContractError("unmeasured move types must be unique")
        object.__setattr__(
            self, "by_move_type", immutable_json_object(self.by_move_type, "by_move_type")
        )

    @property
    def is_complete(self) -> bool:
        """Whether every family with scheduled work has a measured rate behind it."""

        return not self.unmeasured_move_types

    @property
    def within_headroom(self) -> bool:
        """Whether this fits, which an incomplete projection can never say.

        An unmeasured rate is unknown. Reading it as zero would let a family scheduled five
        hundred times a week certify that it fits inside a headroom of one, which is the
        opposite of what not knowing means.
        """

        return self.is_complete and self.projected_parks_per_week <= self.headroom_parks_per_week

    @property
    def reason(self) -> str:
        if not self.is_complete:
            missing = ", ".join(sorted(self.unmeasured_move_types))
            return (
                f"enabling {self.module_key} on {self.product_slug} cannot be sized yet: "
                f"{missing} has scheduled work and no measured park rate, so the projection "
                f"of at least {self.projected_parks_per_week:.1f} approvals a week is a floor "
                "rather than an answer"
            )
        verb = "fits" if self.within_headroom else "exceeds"
        return (
            f"enabling {self.module_key} on {self.product_slug} projects "
            f"{self.projected_parks_per_week:.1f} approvals a week, which {verb} the declared "
            f"headroom of {self.headroom_parks_per_week:.1f}"
        )


def project_approval_load(
    *,
    product_slug: str,
    module_key: str,
    families: tuple[MoveFamily, ...],
    scheduled_moves_per_week: dict[str, float],
    observed_park_rate: dict[str, float | None],
    headroom_parks_per_week: float,
) -> ApprovalLoadProjection:
    """Size the operator's load by arithmetic before enabling a module, not by backlog.

    A family that always parks contributes its whole scheduled volume. A family that parks
    only below its confidence gate contributes its observed rate, defaulting to none where
    nothing has been observed yet — an unobserved rate is unknown, never assumed to be high.
    """

    per_type: dict[str, float] = {}
    unmeasured: list[str] = []
    for family in families:
        volume = float(scheduled_moves_per_week.get(family.move_type, 0.0))
        if volume < 0:
            raise ContractError("scheduled move volume must be nonnegative")
        observed = observed_park_rate.get(family.move_type)
        if observed is not None and not 0 <= float(observed) <= 1:
            raise ContractError("an observed park rate must fall between zero and one")
        if family.human_override:
            # It parks every time by declaration, so no measurement is owed.
            rate = 1.0
        elif observed is not None:
            rate = float(observed)
        elif volume == 0:
            # Nothing is scheduled, so no rate is needed to know it adds nothing.
            rate = 0.0
        else:
            # Scheduled work with no measured rate. Counting it as zero would let it
            # certify capacity nobody has observed, so it is named instead.
            unmeasured.append(family.move_type)
            rate = 0.0
        per_type[family.move_type] = volume * rate
    return ApprovalLoadProjection(
        product_slug=product_slug,
        module_key=module_key,
        projected_parks_per_week=sum(per_type.values()),
        headroom_parks_per_week=headroom_parks_per_week,
        unmeasured_move_types=tuple(unmeasured),
        by_move_type=per_type,
    )


@dataclass(frozen=True, slots=True)
class SeedBatch:
    """A product's onboarding parks, presented for one sitting.

    Each item is still approved or declined on its own. The batch is how they are shown,
    never a single yes that covers them all.
    """

    product_slug: str
    approvals: tuple[Approval, ...]

    def __post_init__(self) -> None:
        required(self.product_slug, "product_slug")
        identities = [approval.approval_id for approval in self.approvals]
        if len(set(identities)) != len(identities):
            raise ContractError("a seed batch cannot list one approval twice")

    @property
    def item_count(self) -> int:
        return len(self.approvals)


def seed_batch(
    *, product_slug: str, approvals: tuple[Approval, ...], parks: tuple[ParkRecord, ...]
) -> SeedBatch:
    seed_ids = {record.park_id for record in parks if record.cause is ParkCause.SEED_MOVE}
    return SeedBatch(
        product_slug=product_slug,
        approvals=tuple(
            approval
            for approval in approvals
            if approval.park_id in seed_ids and approval.status is ApprovalStatus.REQUESTED
        ),
    )


def queue_depth(approvals: tuple[Approval, ...]) -> int:
    """How many decisions are waiting. The person is the scarce resource, so this is a signal."""

    return sum(1 for approval in approvals if approval.status is ApprovalStatus.REQUESTED)


__all__ = [
    "Approval",
    "ApprovalLoadProjection",
    "ApprovalStatus",
    "DrainResult",
    "ParkCause",
    "ParkRecord",
    "ResumeOutcome",
    "SeedBatch",
    "drain_partially",
    "expire_overdue",
    "park_move",
    "project_approval_load",
    "queue_depth",
    "resume_from_approval",
    "seed_batch",
]
