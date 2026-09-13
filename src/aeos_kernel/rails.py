"""Rails: the named rules a move passes, each answering in the same shape.

A rail is one rule with a name. It reads the product's core fields or its family profile —
never a hard-coded product — and returns the same three things every other rail returns: a
verdict, an operator-readable reason, and any gaps it found. Because the shape is identical,
merging them is arithmetic rather than a per-rail special case, and the merged answer is the
move's decision.

Rails are developed gaps-first: a rail can be registered in observing mode, where it reports
what it would have done and changes nothing. Nothing enforces until somebody has looked at
the gaps it produces and agreed they are right.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import required
from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapRow, GapSeverity
from aeos_kernel.modules import MoveFamily
from aeos_kernel.moves import MoveDecision


class RailVerdict(StrEnum):
    """What one rail concluded. The same four every rail may return."""

    PASS = "pass"
    #: The rule is not met and the move cannot derive its claim.
    DECLINE = "decline"
    #: A person must choose; the rail will not guess.
    PARK = "park"
    #: Suppressed pending a signal or gate, not refused.
    HOLD = "hold"
    #: This rail has nothing to say about this move.
    NOT_APPLICABLE = "not_applicable"


class RailMode(StrEnum):
    """Whether a rail's verdict counts yet."""

    #: Reports what it would have decided and changes nothing. Gaps still surface, which is
    #: the point: a rail is read before it is trusted.
    OBSERVING = "observing"
    ENFORCING = "enforcing"


#: How a verdict maps onto the move's decision. `park` outranks `decline`, which outranks
#: `hold`: a person being asked is a stronger outcome than a refusal, and a refusal is
#: stronger than a suppression.
_SEVERITY: dict[RailVerdict, int] = {
    RailVerdict.PARK: 3,
    RailVerdict.DECLINE: 2,
    RailVerdict.HOLD: 1,
    RailVerdict.PASS: 0,
    RailVerdict.NOT_APPLICABLE: 0,
}

_DECISION_FOR: dict[RailVerdict, MoveDecision] = {
    RailVerdict.PARK: MoveDecision.PARKED,
    RailVerdict.DECLINE: MoveDecision.DECLINE,
    RailVerdict.HOLD: MoveDecision.HOLD,
}


@dataclass(frozen=True, slots=True)
class RailResult:
    """One rail's answer, in the shape every rail answers in."""

    rail: str
    verdict: RailVerdict
    reason: str = ""
    gaps: tuple[GapRow, ...] = ()

    def __post_init__(self) -> None:
        required(self.rail, "rail name")
        if not isinstance(self.verdict, RailVerdict):
            raise ContractError("rail verdict is not recognized")
        if self.verdict not in {RailVerdict.PASS, RailVerdict.NOT_APPLICABLE} and not self.reason:
            raise ContractError(f"rail {self.rail!r} must say why it did not pass")
        if not isinstance(self.gaps, tuple):
            raise ContractError("rail gaps must be a tuple, not a lazy sequence")


@dataclass(frozen=True, slots=True)
class RailContext:
    """What a rail is allowed to look at.

    Deliberately a mapping rather than a product object: a rail that could reach into a
    product instance would be one import away from reading a field only one family has.
    """

    product_slug: str
    move_type: str
    detected_at: datetime
    facts: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required(self.product_slug, "product_slug")
        required(self.move_type, "move_type")

    def fact(self, name: str, default: Any = None) -> Any:
        """Read one declared fact, or the default where this family does not have it."""

        return self.facts.get(name, default)

    def gap(self, gap_type: str, subject_ref: str, reason: str) -> GapRow:
        return GapRow(
            gap_type=gap_type,
            severity=GapSeverity.ERROR,
            product_slug=self.product_slug,
            subject_ref=subject_ref,
            reason=reason,
            detected_at=self.detected_at,
        )


@dataclass(frozen=True, slots=True)
class Rail:
    """One named rule, and the move types it answers for."""

    name: str
    move_types: tuple[str, ...]
    #: Takes the rail's own name as well as the context, so one implementation can serve
    #: two registered names — the specification's and a host's — without either result
    #: being labelled with the other's.
    check: Callable[[str, RailContext], RailResult]
    mode: RailMode = RailMode.ENFORCING

    def __post_init__(self) -> None:
        required(self.name, "rail name")
        if not self.move_types:
            raise ContractError(f"rail {self.name!r} must declare the move types it answers for")
        if len(set(self.move_types)) != len(self.move_types):
            raise ContractError(f"rail {self.name!r} lists a move type twice")
        if not isinstance(self.mode, RailMode):
            raise ContractError("rail mode is not recognized")

    def applies_to(self, move_type: str) -> bool:
        return move_type in self.move_types

    def run(self, context: RailContext) -> RailResult:
        if not self.applies_to(context.move_type):
            return RailResult(rail=self.name, verdict=RailVerdict.NOT_APPLICABLE)
        result = self.check(self.name, context)
        if result.rail != self.name:
            raise ContractError(
                f"rail {self.name!r} returned a result labelled {result.rail!r}"
            )
        return result


@dataclass(frozen=True, slots=True)
class MergedRails:
    """Every rail's answer for one move, and the one decision they add up to."""

    move_type: str
    decision: MoveDecision
    results: tuple[RailResult, ...]
    gaps: tuple[GapRow, ...]
    observing_only: tuple[RailResult, ...] = ()

    @property
    def reasons(self) -> tuple[str, ...]:
        """Why the move did not simply pass, in the words each rail used."""

        return tuple(
            result.reason
            for result in self.results
            if result.reason and result.verdict is not RailVerdict.PASS
        )

    @property
    def would_have(self) -> tuple[str, ...]:
        """What the observing rails would have done, had they been enforcing."""

        return tuple(
            f"{result.rail} would have {result.verdict.value}: {result.reason}"
            for result in self.observing_only
            if result.verdict not in {RailVerdict.PASS, RailVerdict.NOT_APPLICABLE}
        )


def evaluate_rails(
    rails: tuple[Rail, ...], context: RailContext, *, default: MoveDecision = MoveDecision.SHIP
) -> MergedRails:
    """Run every rail that answers for this move and merge the answers.

    Merging is arithmetic because the shape is uniform: the strongest verdict wins, a park
    beating a decline beating a hold. An observing rail contributes its gaps and its sentence
    but never its verdict, so a rail can be read for a while before it is trusted.

    Gaps from every rail travel, observing or not. A gap is a fact about the product, and
    whether the rule that found it is switched on does not make it less true.
    """

    enforcing: list[RailResult] = []
    observing: list[RailResult] = []
    gaps: list[GapRow] = []
    for rail in sorted(rails, key=lambda item: item.name):
        result = rail.run(context)
        gaps.extend(result.gaps)
        if rail.mode is RailMode.ENFORCING:
            enforcing.append(result)
        else:
            observing.append(result)
    decision = default
    strongest = max(
        (result for result in enforcing), key=lambda item: _SEVERITY[item.verdict], default=None
    )
    if strongest is not None and strongest.verdict in _DECISION_FOR:
        decision = _DECISION_FOR[strongest.verdict]
    return MergedRails(
        move_type=context.move_type,
        decision=decision,
        results=tuple(enforcing),
        gaps=tuple(gaps),
        observing_only=tuple(observing),
    )


def decide_move(
    *, family: MoveFamily, rails: tuple[Rail, ...], context: RailContext
) -> MergedRails:
    """Merge the rails answering for one move, starting from what its family declares.

    A family that always parks starts parked rather than shipping, so no rail has to
    remember to park it and an empty or all-passing rail set still routes it to a person.
    Starting at ship and relying on a rail to park would make the safe outcome depend on a
    rule being present, which is the wrong way round.
    """

    if context.move_type != family.move_type:
        raise ContractError(
            f"rails for {context.move_type!r} cannot decide a {family.move_type!r} move"
        )
    default = MoveDecision.PARKED if family.human_override else MoveDecision.SHIP
    return evaluate_rails(rails, context, default=default)


class RailRegistry:
    """The rails available to a rule profile, and which move types they cover."""

    def __init__(self, rails: tuple[Rail, ...] = ()) -> None:
        self._rails: dict[str, Rail] = {}
        for rail in rails:
            self.register(rail)

    def register(self, rail: Rail) -> None:
        if rail.name in self._rails:
            raise ContractError(f"rail {rail.name!r} is already registered")
        self._rails[rail.name] = rail

    @property
    def names(self) -> frozenset[str]:
        """What the module loader checks a module's declared rails against."""

        return frozenset(self._rails)

    def for_move(self, move_type: str) -> tuple[Rail, ...]:
        return tuple(
            rail for rail in sorted(self._rails.values(), key=lambda item: item.name)
            if rail.applies_to(move_type)
        )

    def uncovered(self, move_types: tuple[str, ...]) -> tuple[str, ...]:
        """Move types no registered rail answers for — a family that would run ungated."""

        return tuple(sorted(move for move in move_types if not self.for_move(move)))


__all__ = [
    "MergedRails",
    "Rail",
    "RailContext",
    "RailMode",
    "RailRegistry",
    "RailResult",
    "RailVerdict",
    "decide_move",
    "evaluate_rails",
]
