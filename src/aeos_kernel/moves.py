"""Moves: one decision about one product, and the append-only record of what happened.

A move's decision is total over ship, hold, decline and parked — every rail output lands on
one of those. How far the decided action has run is a separate axis, so a move that waits
weeks on an external clock is not confused with a move that is still undecided.

The commit boundary is the load-bearing rule: nothing ships without a complete evidence
path, whoever produced it. A move that cannot derive its claim declines, visibly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required, thaw_json, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapRow, GapSeverity
from aeos_kernel.modules import MoveFamily, PriorityClass


class MoveDecision(StrEnum):
    SHIP = "ship"
    HOLD = "hold"
    DECLINE = "decline"
    PARKED = "parked"


class ExecStatus(StrEnum):
    """How far the decided action has run. Orthogonal to the decision itself."""

    QUEUED = "queued"
    IN_FLIGHT = "in_flight"
    AWAITING_EXTERNAL = "awaiting_external"
    SETTLED = "settled"


class Disposition(StrEnum):
    SHIPPED = "shipped"
    HELD = "held"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    CORRECTED = "corrected"


class RequestedBy(StrEnum):
    OPERATOR = "operator"
    SCHEDULE = "schedule"
    SELF_HEAL = "self_heal"


_DISPOSITION_FOR: dict[MoveDecision, Disposition] = {
    MoveDecision.SHIP: Disposition.SHIPPED,
    MoveDecision.HOLD: Disposition.HELD,
    MoveDecision.DECLINE: Disposition.DECLINED,
}


@dataclass(frozen=True, slots=True)
class MoveRequest:
    """One asked-for decision: this product, this move type, as of this date."""

    request_id: str
    product_slug: str
    move_type: str
    as_of: date
    priority_class: PriorityClass
    requested_by: RequestedBy
    requested_at: datetime
    args: dict[str, Any] = field(default_factory=dict)
    window_start: date | None = None
    window_end: date | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "product_slug", "move_type"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.as_of, date):
            raise ContractError("as_of must be a date")
        if not isinstance(self.priority_class, PriorityClass):
            raise ContractError("priority class is not recognized")
        if not isinstance(self.requested_by, RequestedBy):
            raise ContractError("requested_by is not recognized")
        utc(self.requested_at, "requested_at")
        for name in ("window_start", "window_end"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, date):
                raise ContractError(f"{name} must be a date")
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end < self.window_start
        ):
            raise ContractError("move window cannot end before it starts")
        object.__setattr__(self, "args", immutable_json_object(self.args, "move args"))

    @property
    def args_digest(self) -> str:
        return stable_fingerprint(thaw_json(self.args))

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "product_slug": self.product_slug,
            "move_type": self.move_type,
            "as_of": self.as_of.isoformat(),
            "priority_class": self.priority_class.value,
            "requested_by": self.requested_by.value,
            "requested_at": self.requested_at.isoformat(),
            "args": thaw_json(self.args),
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
        }


def move_idempotency_key(
    *,
    product_slug: str,
    move_type: str,
    as_of: date,
    args_digest: str,
    data_snapshot_refs: tuple[str, ...],
    rulepack_version: str,
) -> str:
    """Identity of a logically identical move.

    The snapshot and rulepack are inside the key on purpose: re-issuing the same move is a
    no-op, but re-running it under fresh data is a new move, not a dedup collision.
    """

    return stable_fingerprint(
        {
            "product_slug": product_slug,
            "move_type": move_type,
            "as_of": as_of.isoformat(),
            "args_digest": args_digest,
            "data_snapshot_refs": sorted(data_snapshot_refs),
            "rulepack_version": rulepack_version,
        }
    )


@dataclass(frozen=True, slots=True)
class Move:
    """The decided action. Immutable once its ledger entry exists."""

    move_id: str
    move_request_id: str
    product_slug: str
    move_type: str
    decision: MoveDecision
    exec_status: ExecStatus
    as_of: date
    rulepack_version: str
    manifest_version: str
    idempotency_key: str
    data_snapshot_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    decline_reason: str = ""
    content_ref: str = ""
    secondary_product_slugs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "move_id",
            "move_request_id",
            "product_slug",
            "move_type",
            "rulepack_version",
            "manifest_version",
            "idempotency_key",
        ):
            required(str(getattr(self, name)), name)
        if not isinstance(self.decision, MoveDecision):
            raise ContractError("move decision is not recognized")
        if not isinstance(self.exec_status, ExecStatus):
            raise ContractError("move exec_status is not recognized")
        if not isinstance(self.as_of, date):
            raise ContractError("as_of must be a date")
        if not self.data_snapshot_refs:
            raise ContractError("every move records the snapshots it derived from")
        for group, label in (
            (self.data_snapshot_refs, "data snapshot ref"),
            (self.evidence_refs, "evidence ref"),
            (self.secondary_product_slugs, "secondary product"),
        ):
            if len(set(group)) != len(group):
                raise ContractError(f"move {label}s must be unique")
            for item in group:
                required(item, f"move {label}")
        if self.product_slug in self.secondary_product_slugs:
            raise ContractError("the target product cannot also be a secondary product")
        # A declined or parked move has no evidence by definition; a shipped one always has.
        if self.decision is MoveDecision.SHIP and not self.evidence_refs:
            raise ContractError("a shipped move must cite at least one evidence item")
        if self.decision is MoveDecision.DECLINE and not self.decline_reason:
            raise ContractError("a declined move must carry an operator-readable reason")
        if self.decision is not MoveDecision.DECLINE and self.decline_reason:
            raise ContractError("only a declined move carries a decline reason")
        if self.content_ref:
            required(self.content_ref, "content_ref")

    def as_dict(self) -> dict[str, Any]:
        return {
            "move_id": self.move_id,
            "move_request_id": self.move_request_id,
            "product_slug": self.product_slug,
            "move_type": self.move_type,
            "decision": self.decision.value,
            "exec_status": self.exec_status.value,
            "as_of": self.as_of.isoformat(),
            "rulepack_version": self.rulepack_version,
            "manifest_version": self.manifest_version,
            "idempotency_key": self.idempotency_key,
            "data_snapshot_refs": list(self.data_snapshot_refs),
            "evidence_refs": list(self.evidence_refs),
            "decline_reason": self.decline_reason,
            "content_ref": self.content_ref,
            "secondary_product_slugs": list(self.secondary_product_slugs),
        }

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())

    @property
    def replay_anchor(self) -> str:
        """What a replay must reproduce: the snapshots, rulepack and manifest it ran under."""

        return stable_fingerprint(
            {
                "data_snapshot_refs": sorted(self.data_snapshot_refs),
                "rulepack_version": self.rulepack_version,
                "manifest_version": self.manifest_version,
            }
        )


@dataclass(frozen=True, slots=True)
class MoveLedgerEntry:
    """The outcome row. Its existence is what freezes the move."""

    entry_id: str
    move_id: str
    move_digest: str
    disposition: Disposition
    recorded_at: datetime
    artifact_uri: str = ""
    artifact_sha256: str = ""

    def __post_init__(self) -> None:
        for name in ("entry_id", "move_id"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.disposition, Disposition):
            raise ContractError("ledger disposition is not recognized")
        utc(self.recorded_at, "recorded_at")
        digest(self.move_digest, "move_digest")
        if self.disposition is Disposition.SHIPPED:
            required(self.artifact_uri, "artifact_uri")
            digest(self.artifact_sha256, "artifact_sha256")
        elif self.artifact_uri or self.artifact_sha256:
            raise ContractError("only a shipped move publishes an artifact")

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "move_id": self.move_id,
            "move_digest": self.move_digest,
            "disposition": self.disposition.value,
            "recorded_at": self.recorded_at.isoformat(),
            "artifact_uri": self.artifact_uri,
            "artifact_sha256": self.artifact_sha256,
        }


@dataclass(frozen=True, slots=True)
class CommitRefusal:
    """Why the commit boundary rejected a move, in words an operator can act on."""

    reason: str
    gaps: tuple[GapRow, ...] = ()

    def __post_init__(self) -> None:
        required(self.reason, "commit refusal reason")
        if not isinstance(self.gaps, tuple):
            raise ContractError("commit refusal gaps must be a tuple, not a lazy sequence")


def _restriction_refusal(
    *, move: Move, family: MoveFamily, actor_role: str, tool: str, detected_at: datetime
) -> CommitRefusal | None:
    """Enforce what a family declares about who and what may run it.

    A family that restricts actors or tools and is then handed an unattributed move is
    refused too: an empty actor against a restricted family is not "unrestricted", it is a
    move nobody will answer for. An unrestricted family is unaffected, which is why adding
    this check breaks no caller that was not already relying on a declaration nothing read.
    """

    for kind, value, permitted, declared in (
        ("actor role", actor_role, family.permits_actor(actor_role), family.allowed_actor_roles),
        ("tool", tool, family.permits_tool(tool), family.allowed_tools),
    ):
        if permitted:
            continue
        named = repr(value) if value else "no " + kind
        return CommitRefusal(
            f"{move.move_type} permits {kind}s {', '.join(sorted(declared))}; got {named}",
            (
                GapRow(
                    gap_type="move_actor_not_permitted",
                    severity=GapSeverity.ERROR,
                    product_slug=move.product_slug,
                    subject_ref=move.move_type,
                    reason=(
                        f"{move.move_type} declares an allow-list of {kind}s and this move "
                        f"reached the commit boundary with {named}"
                    ),
                    detected_at=detected_at,
                    move_id=move.move_id,
                    rulepack_version=move.rulepack_version,
                    data_snapshot_ref=move.data_snapshot_refs[0],
                ),
            ),
        )
    return None


def commit_boundary_refusal(
    *,
    move: Move,
    family: MoveFamily,
    resolved_evidence_refs: frozenset[str],
    detected_at: datetime,
    actor_role: str = "",
    tool: str = "",
) -> CommitRefusal | None:
    """The one structural check every shipped move passes, whoever produced it.

    ``resolved_evidence_refs`` are the evidence identities the host proved resolve into the
    target product's own records. Prose about a product is not evidence; a pointer into its
    graph is.

    ``actor_role`` and ``tool`` are checked against what the family declares. They default to
    empty because most families restrict neither; a family that does restrict refuses an
    empty one, so the default cannot be used to skip the check.
    """

    if move.move_type != family.move_type:
        return CommitRefusal(
            f"move type {move.move_type!r} was committed against family {family.move_type!r}"
        )
    restricted = _restriction_refusal(
        move=move, family=family, actor_role=actor_role, tool=tool, detected_at=detected_at
    )
    if restricted is not None:
        return restricted
    if family.human_override and move.decision is MoveDecision.SHIP:
        return CommitRefusal(
            f"{move.move_type} always parks for an operator before it executes",
            (
                GapRow(
                    gap_type="unparked_high_risk_move",
                    severity=GapSeverity.ERROR,
                    product_slug=move.product_slug,
                    subject_ref=move.move_type,
                    reason=(
                        f"{move.move_type} is a parking family; it reached the commit boundary "
                        "in ship state without an approval"
                    ),
                    detected_at=detected_at,
                    move_id=move.move_id,
                    rulepack_version=move.rulepack_version,
                    data_snapshot_ref=move.data_snapshot_refs[0],
                ),
            ),
        )
    if move.decision is not MoveDecision.SHIP:
        return None
    unresolved = sorted(set(move.evidence_refs) - resolved_evidence_refs)
    if unresolved:
        return CommitRefusal(
            "incomplete_evidence_path: " + ", ".join(unresolved),
            tuple(
                GapRow(
                    gap_type="incomplete_evidence_path",
                    severity=GapSeverity.ERROR,
                    product_slug=move.product_slug,
                    subject_ref=reference,
                    reason=(
                        f"{move.move_type} cites evidence {reference!r}, which does not resolve "
                        f"into {move.product_slug}'s own records"
                    ),
                    detected_at=detected_at,
                    move_id=move.move_id,
                    rulepack_version=move.rulepack_version,
                    data_snapshot_ref=move.data_snapshot_refs[0],
                )
                for reference in unresolved
            ),
        )
    return None


def duplicate_of(
    *, idempotency_key: str, committed: tuple[Move, ...]
) -> Move | None:
    """The already-committed move this one repeats, if any."""

    return next(
        (move for move in committed if move.idempotency_key == idempotency_key),
        None,
    )


def record_outcome(
    *,
    move: Move,
    recorded_at: datetime,
    artifact_uri: str = "",
    artifact_sha256: str = "",
) -> MoveLedgerEntry:
    """Close one move into the ledger. After this the move never changes again."""

    disposition = _DISPOSITION_FOR.get(move.decision)
    if disposition is None:
        raise ContractError("a parked move is not closed until its approval resolves")
    identity = stable_fingerprint({"move": move.move_id, "at": recorded_at.isoformat()})
    return MoveLedgerEntry(
        entry_id=f"entry_{identity[:24]}",
        move_id=move.move_id,
        move_digest=move.digest,
        disposition=disposition,
        recorded_at=recorded_at,
        artifact_uri=artifact_uri,
        artifact_sha256=artifact_sha256,
    )


def assert_unmutated(move: Move, entry: MoveLedgerEntry) -> None:
    """Refuse a move whose content changed after its ledger entry was written."""

    if entry.move_id != move.move_id:
        raise ContractError("ledger entry belongs to a different move")
    if entry.move_digest != move.digest:
        raise ContractError(
            f"move {move.move_id} changed after its ledger entry; corrections are new "
            "superseding entries, never edits"
        )


@dataclass(frozen=True, slots=True)
class SettlementRefusal:
    reason: str


def settle_external(
    *,
    original: Move,
    observation: str,
    observed_snapshot_ref: str,
    settled_at: datetime,
) -> Move | SettlementRefusal:
    """Settle a long-running move by observing its outcome, as a follow-up record.

    The original move keeps its decision and its ledger entry. What changes is only how far
    the action has run, carried on a new record that cites what was observed.
    """

    utc(settled_at, "settled_at")
    required(observation, "observation")
    required(observed_snapshot_ref, "observed_snapshot_ref")
    if original.exec_status is ExecStatus.SETTLED:
        return SettlementRefusal(f"move {original.move_id} is already settled")
    if original.decision is MoveDecision.PARKED:
        return SettlementRefusal("a parked move settles through its approval, not an observation")
    return Move(
        move_id="move_"
        + stable_fingerprint({"settles": original.move_id, "observed": observed_snapshot_ref})[:24],
        move_request_id=original.move_request_id,
        product_slug=original.product_slug,
        move_type=original.move_type,
        decision=original.decision,
        exec_status=ExecStatus.SETTLED,
        as_of=original.as_of,
        rulepack_version=original.rulepack_version,
        manifest_version=original.manifest_version,
        idempotency_key=stable_fingerprint(
            {"settles": original.idempotency_key, "observed": observed_snapshot_ref}
        ),
        data_snapshot_refs=(observed_snapshot_ref,),
        evidence_refs=original.evidence_refs,
        decline_reason=original.decline_reason,
        content_ref=original.content_ref,
        secondary_product_slugs=original.secondary_product_slugs,
    )


@dataclass(frozen=True, slots=True)
class GraduationState:
    """Whether a parking family has earned unattended execution on this product."""

    move_type: str
    product_slug: str
    approved_count: int
    reversal_count: int
    threshold: int
    eligible: bool
    reason: str


def graduation_state(
    *,
    family: MoveFamily,
    product_slug: str,
    approved_count: int,
    reversal_count: int,
    threshold: int,
) -> GraduationState:
    """Money, legal, kill-fence and person-subject families never graduate."""

    if approved_count < 0 or reversal_count < 0 or threshold <= 0:
        raise ContractError("graduation counts must be nonnegative with a positive threshold")
    if not family.human_override:
        reason = f"{family.move_type} does not park, so graduation does not apply"
        return GraduationState(
            family.move_type, product_slug, approved_count, reversal_count, threshold, False, reason
        )
    if family.never_graduates:
        reason = f"{family.move_type} never graduates; it is a permanently reserved decision"
        return GraduationState(
            family.move_type, product_slug, approved_count, reversal_count, threshold, False, reason
        )
    if reversal_count:
        reason = (
            f"{family.move_type} had {reversal_count} reversal(s) on {product_slug}; "
            "graduation is revoked by the first reversal"
        )
        return GraduationState(
            family.move_type, product_slug, approved_count, reversal_count, threshold, False, reason
        )
    if approved_count < threshold:
        reason = (
            f"{family.move_type} has {approved_count} of {threshold} approvals without reversal "
            f"on {product_slug}"
        )
        return GraduationState(
            family.move_type, product_slug, approved_count, reversal_count, threshold, False, reason
        )
    reason = (
        f"{family.move_type} reached {approved_count} approvals with no reversal on "
        f"{product_slug}; graduation itself is a governed move"
    )
    return GraduationState(
        family.move_type, product_slug, approved_count, reversal_count, threshold, True, reason
    )


__all__ = [
    "CommitRefusal",
    "Disposition",
    "ExecStatus",
    "GraduationState",
    "Move",
    "MoveDecision",
    "MoveLedgerEntry",
    "MoveRequest",
    "RequestedBy",
    "SettlementRefusal",
    "assert_unmutated",
    "commit_boundary_refusal",
    "duplicate_of",
    "graduation_state",
    "move_idempotency_key",
    "record_outcome",
    "settle_external",
]
