"""Signals and gates: measured rows, and the one query that decides a stage transition.

A gate is a query over one product's signals and gaps, not a procedure. The same query
whose emptiness means "this stage is done" is the query the gate evaluates, so the gate and
the completion check can never disagree about whether a product has converged.

Stop rules run first. A product whose complaint rate is climbing does not graduate because
its growth numbers look good.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import immutable_json_object, required, thaw_json, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapRow, GapSeverity, gaps_in_scope


class Stage(StrEnum):
    """How far a product has run through one module."""

    SEED = "seed"
    VALIDATE = "validate"
    SCALE = "scale"
    SUSTAIN = "sustain"


class WLGStage(StrEnum):
    """The governed build module's stages, independent of marketing stages."""

    ONBOARDING = "onboarding"
    BUILDING = "building"
    RELEASE_CANDIDATE = "release_candidate"
    LAUNCHED = "launched"


class RunStatus(StrEnum):
    """What the run is doing. Parked is a status, never a stage."""

    RUNNING = "running"
    PAUSED = "paused"
    PARKED = "parked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GateOutcome(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    PARK = "park"


class Comparison(StrEnum):
    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    BELOW = "below"
    ABOVE = "above"


_COMPARE: dict[Comparison, Callable[[float, float], bool]] = {
    Comparison.AT_LEAST: lambda value, threshold: value >= threshold,
    Comparison.AT_MOST: lambda value, threshold: value <= threshold,
    Comparison.BELOW: lambda value, threshold: value < threshold,
    Comparison.ABOVE: lambda value, threshold: value > threshold,
}

_PHRASE: dict[Comparison, str] = {
    Comparison.AT_LEAST: "at least",
    Comparison.AT_MOST: "at most",
    Comparison.BELOW: "below",
    Comparison.ABOVE: "above",
}


@dataclass(frozen=True, slots=True)
class Signal:
    """One measured row, scoped to the product it is about. Append-only."""

    product_slug: str
    metric: str
    value: float
    window: str
    ts: datetime
    move_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("product_slug", "metric", "window"):
            required(str(getattr(self, name)), name)
        if isinstance(self.value, bool) or not isinstance(self.value, int | float):
            raise ContractError("signal value must be numeric")
        utc(self.ts, "ts")
        if self.move_id:
            required(self.move_id, "move_id")
        object.__setattr__(self, "meta", immutable_json_object(self.meta, "signal meta"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_slug": self.product_slug,
            "metric": self.metric,
            "value": float(self.value),
            "window": self.window,
            "ts": self.ts.isoformat(),
            "move_id": self.move_id,
            "meta": thaw_json(self.meta),
        }


def latest_signal(
    signals: tuple[Signal, ...], *, product_slug: str, metric: str, window: str
) -> Signal | None:
    """The most recent measurement of one metric for one product.

    Scoped by construction: a gate reading through this cannot accidentally read another
    product's numbers.
    """

    matching = [
        item
        for item in signals
        if item.product_slug == product_slug and item.metric == metric and item.window == window
    ]
    return max(matching, key=lambda item: item.ts) if matching else None


@dataclass(frozen=True, slots=True)
class SignalPredicate:
    """One named, implementable condition over a measured metric."""

    metric: str
    window: str
    comparison: Comparison
    threshold: float
    required_observation: bool = True

    def __post_init__(self) -> None:
        required(self.metric, "metric")
        required(self.window, "window")
        if not isinstance(self.comparison, Comparison):
            raise ContractError("signal comparison is not recognized")
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, int | float):
            raise ContractError("signal threshold must be numeric")

    @property
    def sentence(self) -> str:
        return (
            f"{self.metric} over {self.window} must be "
            f"{_PHRASE[self.comparison]} {self.threshold:g}"
        )

    def unmet_reason(self, signals: tuple[Signal, ...], *, product_slug: str) -> str:
        """Why this condition is not satisfied, or ``""`` when it is.

        A metric with no measurement is unknown, never zero and never healthy.
        """

        observed = latest_signal(
            signals, product_slug=product_slug, metric=self.metric, window=self.window
        )
        if observed is None:
            if self.required_observation:
                return f"{self.metric} over {self.window} has not been measured"
            return ""
        if _COMPARE[self.comparison](float(observed.value), float(self.threshold)):
            return ""
        return (
            f"{self.metric} over {self.window} is {float(observed.value):g}; "
            f"{self.sentence.split(' must be ')[1]} is required"
        )


@dataclass(frozen=True, slots=True)
class ExitSet:
    """The exact condition a stage transition requires, stated so a builder can implement it.

    This object is the single definition read twice: once by the gate deciding a transition
    and once by the completion predicate asking whether the stage has converged.
    """

    name: str
    signal_predicates: tuple[SignalPredicate, ...] = ()
    max_open_error_gaps: int = 0
    gap_types_in_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required(self.name, "exit set name")
        if self.max_open_error_gaps < 0:
            raise ContractError("an exit set cannot permit a negative number of gaps")
        if not self.signal_predicates and not self.gap_types_in_scope:
            # An exit set that constrains nothing would pass anything.
            raise ContractError(f"exit set {self.name!r} declares no condition")
        if len(set(self.gap_types_in_scope)) != len(self.gap_types_in_scope):
            raise ContractError("exit set gap types must be unique")

    def scoped_gaps(self, gaps: tuple[GapRow, ...], *, product_slug: str) -> tuple[GapRow, ...]:
        """The gaps this exit set counts, in its exact scope — never an archive-wide scan."""

        scoped = gaps_in_scope(gaps, product_slug=product_slug)
        blocking = tuple(gap for gap in scoped if gap.severity is GapSeverity.ERROR)
        if not self.gap_types_in_scope:
            return blocking
        return tuple(gap for gap in blocking if gap.gap_type in self.gap_types_in_scope)

    def unmet(
        self,
        *,
        product_slug: str,
        signals: tuple[Signal, ...],
        gaps: tuple[GapRow, ...],
    ) -> tuple[str, ...]:
        """Every reason this exit set is not satisfied, in words an operator can act on."""

        reasons = [
            reason
            for predicate in self.signal_predicates
            if (reason := predicate.unmet_reason(signals, product_slug=product_slug))
        ]
        open_gaps = self.scoped_gaps(gaps, product_slug=product_slug)
        if len(open_gaps) > self.max_open_error_gaps:
            kinds = sorted({gap.gap_type for gap in open_gaps})
            reasons.append(
                f"{len(open_gaps)} open error gap(s) in scope ({', '.join(kinds)}); "
                f"at most {self.max_open_error_gaps} permitted"
            )
        return tuple(reasons)

    @property
    def sentence(self) -> str:
        parts = [predicate.sentence for predicate in self.signal_predicates]
        scope = ", ".join(self.gap_types_in_scope) if self.gap_types_in_scope else "any type"
        parts.append(f"open error gaps ({scope}) must be at most {self.max_open_error_gaps}")
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class StopRule:
    """A deterministic halt that outranks every growth condition."""

    name: str
    predicate: SignalPredicate
    outcome: GateOutcome
    operator_reason: str

    def __post_init__(self) -> None:
        required(self.name, "stop rule name")
        required(self.operator_reason, "stop rule operator reason")
        if not isinstance(self.outcome, GateOutcome):
            raise ContractError("stop rule outcome is not recognized")
        if self.outcome is GateOutcome.PASS:
            raise ContractError("a stop rule cannot pass a transition")

    def fires(self, signals: tuple[Signal, ...], *, product_slug: str) -> bool:
        """A stop rule fires when its condition is *met* — the condition describes the harm."""

        observed = latest_signal(
            signals,
            product_slug=product_slug,
            metric=self.predicate.metric,
            window=self.predicate.window,
        )
        if observed is None:
            return False
        return _COMPARE[self.predicate.comparison](
            float(observed.value), float(self.predicate.threshold)
        )


@dataclass(frozen=True, slots=True)
class Gate:
    """One stage transition and everything it requires."""

    gate_id: str
    module_key: str
    from_stage: Stage
    to_stage: Stage
    exit_set: ExitSet
    stop_rules: tuple[StopRule, ...] = ()

    def __post_init__(self) -> None:
        required(self.gate_id, "gate_id")
        required(self.module_key, "module_key")
        for name in ("from_stage", "to_stage"):
            if not isinstance(getattr(self, name), Stage):
                raise ContractError(f"gate {name} is not a recognized stage")
        if self.from_stage is self.to_stage:
            raise ContractError("a gate must move between two different stages")
        names = [rule.name for rule in self.stop_rules]
        if len(set(names)) != len(names):
            raise ContractError("gate stop rules must be uniquely named")


@dataclass(frozen=True, slots=True)
class Run:
    """One product's pass through one module."""

    run_id: str
    product_slug: str
    module_key: str
    stage: Stage | WLGStage
    status: RunStatus
    started_at: datetime

    def __post_init__(self) -> None:
        for name in ("run_id", "product_slug", "module_key"):
            required(str(getattr(self, name)), name)
        expected_stage = WLGStage if self.module_key == "prod_wlg" else Stage
        if not isinstance(self.stage, expected_stage):
            raise ContractError("run stage is not recognized")
        if not isinstance(self.status, RunStatus):
            raise ContractError("run status is not recognized")
        utc(self.started_at, "started_at")


@dataclass(frozen=True, slots=True)
class GateDecision:
    """The gate's answer and the machine-readable reason behind it."""

    decision_id: str
    run_id: str
    product_slug: str
    gate_id: str
    from_stage: Stage
    to_stage: Stage
    outcome: GateOutcome
    reasons: tuple[str, ...]
    evaluated_at: datetime
    stop_rule_fired: str = ""

    def __post_init__(self) -> None:
        for name in ("decision_id", "run_id", "product_slug", "gate_id"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.outcome, GateOutcome):
            raise ContractError("gate outcome is not recognized")
        utc(self.evaluated_at, "evaluated_at")
        if self.outcome is not GateOutcome.PASS and not self.reasons:
            raise ContractError("a gate that did not pass must say why")
        if self.outcome is GateOutcome.PASS and self.reasons:
            raise ContractError("a passing gate carries no blocking reasons")

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "product_slug": self.product_slug,
            "gate_id": self.gate_id,
            "from_stage": self.from_stage.value,
            "to_stage": self.to_stage.value,
            "outcome": self.outcome.value,
            "reasons": list(self.reasons),
            "stop_rule_fired": self.stop_rule_fired,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


def evaluate_gate(
    *,
    gate: Gate,
    run: Run,
    signals: tuple[Signal, ...],
    gaps: tuple[GapRow, ...],
    evaluated_at: datetime,
) -> GateDecision:
    """Decide one transition for one product. Stop rules are evaluated before anything else."""

    if run.module_key != gate.module_key:
        raise ContractError("gate and run belong to different modules")
    if run.stage is not gate.from_stage:
        raise ContractError(
            f"run is at {run.stage.value}; gate {gate.gate_id} leaves {gate.from_stage.value}"
        )
    identity = stable_fingerprint(
        {"run": run.run_id, "gate": gate.gate_id, "at": evaluated_at.isoformat()}
    )
    for rule in gate.stop_rules:
        if rule.fires(signals, product_slug=run.product_slug):
            return GateDecision(
                decision_id=f"gate_decision_{identity[:24]}",
                run_id=run.run_id,
                product_slug=run.product_slug,
                gate_id=gate.gate_id,
                from_stage=gate.from_stage,
                to_stage=gate.to_stage,
                outcome=rule.outcome,
                reasons=(rule.operator_reason,),
                evaluated_at=evaluated_at,
                stop_rule_fired=rule.name,
            )
    unmet = gate.exit_set.unmet(product_slug=run.product_slug, signals=signals, gaps=gaps)
    return GateDecision(
        decision_id=f"gate_decision_{identity[:24]}",
        run_id=run.run_id,
        product_slug=run.product_slug,
        gate_id=gate.gate_id,
        from_stage=gate.from_stage,
        to_stage=gate.to_stage,
        outcome=GateOutcome.PASS if not unmet else GateOutcome.BLOCK,
        reasons=unmet,
        evaluated_at=evaluated_at,
    )


def stage_is_complete(
    *,
    gate: Gate,
    product_slug: str,
    signals: tuple[Signal, ...],
    gaps: tuple[GapRow, ...],
) -> bool:
    """The completion predicate — the same query the gate reads, not a looser one."""

    return not gate.exit_set.unmet(product_slug=product_slug, signals=signals, gaps=gaps)


@dataclass(frozen=True, slots=True)
class ConvergenceCheck:
    """Whether a repair actually converged, measured after the repair, in the same scope."""

    product_slug: str
    gate_id: str
    converged: bool
    closed_gap_ids: tuple[str, ...]
    new_gap_ids: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def sentence(self) -> str:
        if self.converged:
            return f"{self.gate_id} converged: {len(self.closed_gap_ids)} gap(s) closed"
        if self.new_gap_ids:
            return (
                f"{self.gate_id} did not converge: {len(self.closed_gap_ids)} closed but "
                f"{len(self.new_gap_ids)} new gap(s) appeared"
            )
        return f"{self.gate_id} did not converge: {'; '.join(self.reasons)}"


def re_measure_after_repair(
    *,
    gate: Gate,
    product_slug: str,
    signals: tuple[Signal, ...],
    gaps_before: tuple[GapRow, ...],
    gaps_after: tuple[GapRow, ...],
) -> ConvergenceCheck:
    """Re-measure in the gate's exact scope after a repair.

    A fix that closes one gap and trips a different rule has not converged. The new gap is
    reported as its own finding rather than absorbed into the repaired one.
    """

    scoped_before = gate.exit_set.scoped_gaps(gaps_before, product_slug=product_slug)
    scoped_after = gate.exit_set.scoped_gaps(gaps_after, product_slug=product_slug)
    before = {gap.identity for gap in scoped_before}
    after = {gap.identity for gap in scoped_after}
    closed = tuple(sorted(set(before) - set(after)))
    appeared = tuple(sorted(set(after) - set(before)))
    unmet = gate.exit_set.unmet(product_slug=product_slug, signals=signals, gaps=gaps_after)
    return ConvergenceCheck(
        product_slug=product_slug,
        gate_id=gate.gate_id,
        converged=not unmet,
        closed_gap_ids=closed,
        new_gap_ids=appeared,
        reasons=unmet,
    )


__all__ = [
    "Comparison",
    "ConvergenceCheck",
    "ExitSet",
    "Gate",
    "GateDecision",
    "GateOutcome",
    "Run",
    "RunStatus",
    "Signal",
    "SignalPredicate",
    "Stage",
    "StopRule",
    "evaluate_gate",
    "latest_signal",
    "re_measure_after_repair",
    "stage_is_complete",
]
