"""The build pipeline as a governed surface: coverage, validation and release readiness.

The control plane does not own the build graph. It captures point-in-time snapshots of it
and records its own decisions about them, so "was this product releasable on that date, and
why not" is a deterministic read rather than a re-query of something that has since moved.

Release readiness is one query. Its negation is the same query's blocking reasons, which is
why the gate and the "why is this blocked" answer can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapRow, GapSeverity
from aeos_kernel.registry import LiabilityClass, ProductManifest, ReleaseState


class BindingStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class PipelineGateKind(StrEnum):
    COVERAGE = "coverage"
    VALIDATION = "validation"
    RELEASE_READINESS = "release_readiness"


class PipelineOutcome(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    PARK = "park"


class Readiness(StrEnum):
    GREEN = "green"
    BLOCKED = "blocked"
    PARKED = "parked"


class GateStatus(StrEnum):
    OPEN = "open"
    GREEN = "green"
    WAIVED = "waived"


class PredicateKind(StrEnum):
    """How a product's own launch bar is evidenced."""

    FIXTURE = "fixture"
    COUNSEL_SIGNOFF = "counsel_signoff"
    INSURANCE = "insurance"
    PILOT_COUNT = "pilot_count"
    CANARY_WINDOW = "canary_window"
    STATUTE_PIN = "statute_pin"
    CUSTOM = "custom"


class ClaimState(StrEnum):
    UNCLAIMED = "unclaimed"
    CLAIMED = "claimed"
    COMMITTED = "committed"
    FAILED = "failed"


# The launch bars each liability class must carry, whatever the product is.
_CLASS_REQUIRED_PREDICATES: dict[LiabilityClass, tuple[PredicateKind, ...]] = {
    LiabilityClass.A: (),
    LiabilityClass.B: (PredicateKind.COUNSEL_SIGNOFF,),
    LiabilityClass.C: (
        PredicateKind.COUNSEL_SIGNOFF,
        PredicateKind.INSURANCE,
        PredicateKind.CUSTOM,
    ),
}


@dataclass(frozen=True, slots=True)
class RegistryRef:
    """A pinned pointer to one registry, with the digest that makes it replayable."""

    project_id: str
    registry_locator: str
    registry_sha256: str
    row_count: int
    captured_at: datetime
    snapshot_ref: str

    def __post_init__(self) -> None:
        for name in ("project_id", "registry_locator", "snapshot_ref"):
            required(str(getattr(self, name)), name)
        digest(self.registry_sha256, "registry_sha256")
        if self.row_count < 0:
            raise ContractError("registry row count must be nonnegative")
        utc(self.captured_at, "captured_at")


@dataclass(frozen=True, slots=True)
class WLGProjectBinding:
    """One product to one build project. Rebinding supersedes; it never edits."""

    binding_id: str
    product_slug: str
    project_id: str
    requirements_ref: RegistryRef
    shape_ref: RegistryRef
    bound_at: datetime
    bound_by: str
    status: BindingStatus = BindingStatus.ACTIVE

    def __post_init__(self) -> None:
        for name in ("binding_id", "product_slug", "project_id", "bound_by"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.status, BindingStatus):
            raise ContractError("binding status is not recognized")
        utc(self.bound_at, "bound_at")
        if self.requirements_ref.project_id != self.project_id:
            raise ContractError("requirements registry belongs to a different project")
        if self.shape_ref.project_id != self.project_id:
            raise ContractError("shape registry belongs to a different project")

    @property
    def is_active(self) -> bool:
        return self.status is BindingStatus.ACTIVE


def active_binding(
    bindings: tuple[WLGProjectBinding, ...], *, product_slug: str
) -> WLGProjectBinding | None:
    """The one active binding for a product, refusing if the history has two."""

    matches = [
        binding
        for binding in bindings
        if binding.product_slug == product_slug and binding.is_active
    ]
    if len(matches) > 1:
        raise ContractError(
            f"{product_slug} has {len(matches)} active bindings; exactly one may be active"
        )
    return matches[0] if matches else None


@dataclass(frozen=True, slots=True)
class CoverageSnapshot:
    """What the build graph covered at one instant, and what it did not."""

    snapshot_id: str
    binding_id: str
    product_slug: str
    snapshot_ref: str
    captured_at: datetime
    total_requirements: int
    covered_requirements: int
    uncovered_requirement_ids: tuple[str, ...]
    unmet_kind_obligations: tuple[tuple[str, str], ...] = ()
    coverage_by_kind: dict[str, Any] = field(default_factory=dict)
    orphan_shape_count: int = 0

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "binding_id", "product_slug", "snapshot_ref"):
            required(str(getattr(self, name)), name)
        utc(self.captured_at, "captured_at")
        if self.total_requirements < 0 or self.covered_requirements < 0:
            raise ContractError("coverage counts must be nonnegative")
        if self.covered_requirements > self.total_requirements:
            raise ContractError("covered requirements cannot exceed the total")
        if len(set(self.uncovered_requirement_ids)) != len(self.uncovered_requirement_ids):
            raise ContractError("uncovered requirement ids must be unique")
        if self.orphan_shape_count < 0:
            raise ContractError("orphan shape count must be nonnegative")
        for requirement_id, shape_kind in self.unmet_kind_obligations:
            required(requirement_id, "unmet obligation requirement id")
            required(shape_kind, "unmet obligation shape kind")
        object.__setattr__(
            self,
            "coverage_by_kind",
            immutable_json_object(self.coverage_by_kind, "coverage_by_kind"),
        )

    @property
    def coverage_pct(self) -> float:
        if not self.total_requirements:
            return 0.0
        return self.covered_requirements / self.total_requirements

    def gaps(self, *, default_kind_severity: GapSeverity = GapSeverity.ERROR) -> tuple[GapRow, ...]:
        """Coverage shortfalls as ordinary gap rows, not a parallel dashboard."""

        rows = [
            GapRow(
                gap_type="coverage_requirement_uncovered",
                severity=GapSeverity.ERROR,
                product_slug=self.product_slug,
                subject_ref=requirement_id,
                reason=f"{requirement_id} has no shape covering it",
                detected_at=self.captured_at,
                data_snapshot_ref=self.snapshot_ref,
            )
            for requirement_id in self.uncovered_requirement_ids
        ]
        rows.extend(
            GapRow(
                gap_type="coverage_kind_unmet",
                severity=default_kind_severity,
                product_slug=self.product_slug,
                subject_ref=f"{requirement_id}:{shape_kind}",
                reason=f"{requirement_id} requires a {shape_kind} shape, which does not exist",
                detected_at=self.captured_at,
                data_snapshot_ref=self.snapshot_ref,
            )
            for requirement_id, shape_kind in self.unmet_kind_obligations
        )
        return tuple(rows)

    def kind_shortfalls(self, thresholds: dict[str, Any]) -> tuple[str, ...]:
        """Per-kind coverage that has not reached the family's declared threshold."""

        reasons: list[str] = []
        for shape_kind, needed in sorted(thresholds.items()):
            if not isinstance(needed, int) or isinstance(needed, bool):
                continue
            observed = self.coverage_by_kind.get(shape_kind)
            satisfied = observed.get("satisfied") if isinstance(observed, dict) else None
            if not isinstance(satisfied, int) or isinstance(satisfied, bool):
                reasons.append(f"{shape_kind} coverage has not been measured")
            elif satisfied < needed:
                reasons.append(f"{shape_kind} coverage is {satisfied} of {needed} required")
        return tuple(reasons)


#: The four components a WLG-built product's gate reports. Named so a WLG consumer has one
#: place to read them from instead of four string literals that can drift apart.
WLG_GATE_COMPONENTS: tuple[str, ...] = (
    "spec_satisfied",
    "closure_valid",
    "net_delta_ok",
    "warning_ratchet",
)


@dataclass(frozen=True, slots=True)
class ValidationSnapshot:
    """The build system's own gate result, read verbatim rather than re-derived.

    ``gate_status`` carries whatever named components that build system reports, and the pass
    is their conjunction. The names are not fixed here because they belong to the build
    system: a WLG-built product supplies :data:`WLG_GATE_COMPONENTS`, and a product built some
    other way supplies its own. Requiring the WLG four everywhere would leave every other
    product with one honest option and one dishonest one — no snapshot at all, or four
    borrowed labels over checks that are not those checks.
    """

    snapshot_id: str
    binding_id: str
    product_slug: str
    snapshot_ref: str
    captured_at: datetime
    error_gap_count: int
    warning_gap_count: int
    prior_warning_gap_count: int
    gate_status: dict[str, Any]
    gaps_by_rule: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "binding_id", "product_slug", "snapshot_ref"):
            required(str(getattr(self, name)), name)
        utc(self.captured_at, "captured_at")
        for name in ("error_gap_count", "warning_gap_count", "prior_warning_gap_count"):
            if getattr(self, name) < 0:
                raise ContractError(f"{name} must be nonnegative")
        if not self.gate_status:
            # An empty conjunction is vacuously true: a gate that could never be red.
            raise ContractError(
                "a validation snapshot must name at least one gate component; an empty gate "
                "status would pass unconditionally"
            )
        for name, value in self.gate_status.items():
            if not isinstance(value, bool):
                raise ContractError(f"gate component {name!r} must be a boolean")
        for name in ("gate_status", "gaps_by_rule"):
            object.__setattr__(
                self, name, immutable_json_object(getattr(self, name), f"validation {name}")
            )

    @property
    def triple_gate_pass(self) -> bool:
        """The conjunction of every component the build system reported.

        Never a softer re-derivation: each component is read as given, and the pass is all of
        them. A component this code does not recognize still has to be true.
        """

        return all(bool(value) for value in self.gate_status.values())

    @property
    def failed_components(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, value in self.gate_status.items() if not value))

    @property
    def ratchet_delta(self) -> int:
        return self.warning_gap_count - self.prior_warning_gap_count

    @property
    def warning_ratchet_ok(self) -> bool:
        return self.ratchet_delta <= 0

    def failing_rules(self, block_on: tuple[str, ...]) -> tuple[str, ...]:
        """Named rules with errors that block a release regardless of the totals."""

        failing: list[str] = []
        for rule in block_on:
            counts = self.gaps_by_rule.get(rule)
            errors = counts.get("error") if isinstance(counts, dict) else None
            if isinstance(errors, int) and not isinstance(errors, bool) and errors > 0:
                failing.append(f"{rule} has {errors} error gap(s)")
        return tuple(failing)

    def is_stale(self, *, now: datetime, threshold_hours: float) -> bool:
        if threshold_hours <= 0:
            return False
        return now - self.captured_at > timedelta(hours=threshold_hours)


@dataclass(frozen=True, slots=True)
class GateManifestEntry:
    """One of the product's own launch bars, compiled from its requirements."""

    gate_id: str
    description: str
    predicate_kind: PredicateKind
    status: GateStatus
    launch_blocking: bool
    evidence_ref: str = ""
    regime_id: str = ""

    def __post_init__(self) -> None:
        required(self.gate_id, "gate_id")
        required(self.description, "gate description")
        if not isinstance(self.predicate_kind, PredicateKind):
            raise ContractError("gate predicate kind is not recognized")
        if not isinstance(self.status, GateStatus):
            raise ContractError("gate status is not recognized")
        if self.status in {GateStatus.GREEN, GateStatus.WAIVED}:
            required(self.evidence_ref, "evidence_ref")
        elif self.evidence_ref:
            raise ContractError("an open gate carries no evidence reference")
        if self.regime_id:
            required(self.regime_id, "regime_id")

    @property
    def satisfied(self) -> bool:
        return self.status in {GateStatus.GREEN, GateStatus.WAIVED}

    def in_scope(self, regime_id: str) -> bool:
        """Which read this bar belongs to.

        A product-level read covers every regime, so a slow regime cannot hide behind an
        aggregate. A regime-scoped read covers the product-wide bars plus that regime's,
        so a slow regime does not block its verdict-live siblings either.
        """

        if not regime_id:
            return True
        return not self.regime_id or self.regime_id == regime_id


@dataclass(frozen=True, slots=True)
class ProductGateManifest:
    """The product's own launch criteria, as gate inputs rather than prose."""

    manifest_id: str
    product_slug: str
    gates: tuple[GateManifestEntry, ...]
    source_ref: str
    captured_at: datetime
    snapshot_ref: str
    version: int = 1

    def __post_init__(self) -> None:
        for name in ("manifest_id", "product_slug", "source_ref", "snapshot_ref"):
            required(str(getattr(self, name)), name)
        utc(self.captured_at, "captured_at")
        if self.version <= 0:
            raise ContractError("gate manifest version must be positive")
        identities = [entry.gate_id for entry in self.gates]
        if len(set(identities)) != len(identities):
            raise ContractError("gate ids must be unique within a manifest")

    def liability_gate_set_valid(self, liability_class: LiabilityClass) -> tuple[str, ...]:
        """Missing class-selected bars, as reasons. Empty means the set is valid."""

        present = {entry.predicate_kind for entry in self.gates if entry.launch_blocking}
        missing = [
            kind.value
            for kind in _CLASS_REQUIRED_PREDICATES[liability_class]
            if kind not in present
        ]
        return tuple(
            f"class {liability_class.value} requires a launch-blocking {kind} gate"
            for kind in missing
        )

    def open_blocking(self, *, regime_id: str = "") -> tuple[GateManifestEntry, ...]:
        return tuple(
            entry
            for entry in self.gates
            if entry.launch_blocking and entry.in_scope(regime_id) and not entry.satisfied
        )


@dataclass(frozen=True, slots=True)
class ReleaseReadiness:
    """One product's releasability, and the exact reasons when it is not."""

    product_slug: str
    readiness: Readiness
    blocking_reasons: tuple[str, ...]
    evaluated_at: datetime
    coverage_snapshot_id: str
    validation_snapshot_id: str
    gate_manifest_id: str
    regime_id: str = ""

    def __post_init__(self) -> None:
        required(self.product_slug, "product_slug")
        if not isinstance(self.readiness, Readiness):
            raise ContractError("readiness is not recognized")
        utc(self.evaluated_at, "evaluated_at")
        if self.readiness is Readiness.GREEN and self.blocking_reasons:
            raise ContractError("a green readiness carries no blocking reasons")
        if self.readiness is not Readiness.GREEN and not self.blocking_reasons:
            raise ContractError("a readiness that is not green must say why")

    @property
    def is_green(self) -> bool:
        return self.readiness is Readiness.GREEN

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_slug": self.product_slug,
            "readiness": self.readiness.value,
            "blocking_reasons": list(self.blocking_reasons),
            "evaluated_at": self.evaluated_at.isoformat(),
            "coverage_snapshot_id": self.coverage_snapshot_id,
            "validation_snapshot_id": self.validation_snapshot_id,
            "gate_manifest_id": self.gate_manifest_id,
            "regime_id": self.regime_id,
        }


def evaluate_release_readiness(
    *,
    manifest: ProductManifest,
    coverage: CoverageSnapshot | None,
    validation: ValidationSnapshot | None,
    gate_manifest: ProductGateManifest | None,
    family_coverage_thresholds: dict[str, Any],
    now: datetime,
    regime_id: str = "",
) -> ReleaseReadiness:
    """The single query. Everything absent is unknown, and unknown never reads as ready."""

    utc(now, "now")
    reasons: list[str] = []
    parked = False
    max_errors = int(manifest.release_rule("max_open_error_gaps", 0) or 0)

    # Every input is evaluated on its own. Stopping at the first absent one would report a
    # missing snapshot and stay silent about blockers already sitting in the inputs that did
    # arrive, which reads as one small problem instead of the several that exist.
    if coverage is None:
        reasons.append("no coverage snapshot has been captured")
    else:
        thresholds = dict(family_coverage_thresholds)
        thresholds.update(manifest.release_rule("coverage_thresholds", {}) or {})
        minimum = thresholds.pop("min_overall", None)
        if (
            isinstance(minimum, int | float)
            and not isinstance(minimum, bool)
            and coverage.coverage_pct < float(minimum)
        ):
            reasons.append(
                f"coverage is {coverage.coverage_pct:.0%}; at least {float(minimum):.0%} "
                f"required ({coverage.covered_requirements} of "
                f"{coverage.total_requirements} requirements)"
            )
        reasons.extend(coverage.kind_shortfalls(thresholds))
        coverage_errors = [gap for gap in coverage.gaps() if gap.severity is GapSeverity.ERROR]
        if len(coverage_errors) > max_errors:
            reasons.append(
                f"{len(coverage_errors)} coverage error gap(s); at most {max_errors} permitted"
            )

    if validation is None:
        reasons.append("no validation snapshot has been captured")
    else:
        staleness = float(manifest.wlg_sync_policy.get("staleness_threshold_hours", 0) or 0)
        if validation.is_stale(now=now, threshold_hours=staleness):
            parked = True
            reasons.append(
                f"the validation snapshot is older than {staleness:g}h; a stale reading cannot "
                "green-light a launch"
            )
        if validation.ratchet_delta > 0:
            reasons.append(
                f"warning gaps rose by {validation.ratchet_delta} since the previous snapshot"
            )
        if not validation.triple_gate_pass:
            reasons.append(
                f"build gate did not pass: {', '.join(validation.failed_components)}"
            )
        block_on = tuple(manifest.release_rule("block_on_error_rules", ()) or ())
        reasons.extend(validation.failing_rules(block_on))
        if validation.error_gap_count > max_errors:
            reasons.append(
                f"{validation.error_gap_count} build error gap(s); at most {max_errors} permitted"
            )

    if gate_manifest is None:
        reasons.append("no_product_gate_manifest: the product's own launch bars are not compiled")
    else:
        reasons.extend(gate_manifest.liability_gate_set_valid(manifest.liability_class))
        for entry in gate_manifest.open_blocking(regime_id=regime_id):
            scope = f" ({entry.regime_id})" if entry.regime_id else ""
            reasons.append(f"launch bar {entry.gate_id}{scope} is open: {entry.description}")

    if not reasons:
        readiness = Readiness.GREEN
    elif parked:
        readiness = Readiness.PARKED
    else:
        readiness = Readiness.BLOCKED
    return ReleaseReadiness(
        product_slug=manifest.product_slug,
        readiness=readiness,
        blocking_reasons=tuple(reasons),
        evaluated_at=now,
        coverage_snapshot_id=coverage.snapshot_id if coverage else "",
        validation_snapshot_id=validation.snapshot_id if validation else "",
        gate_manifest_id=gate_manifest.manifest_id if gate_manifest else "",
        regime_id=regime_id,
    )


@dataclass(frozen=True, slots=True)
class PipelineGateDecision:
    """One recorded pipeline-stage transition decision."""

    decision_id: str
    product_slug: str
    run_id: str
    gate_kind: PipelineGateKind
    from_state: ReleaseState
    to_state: ReleaseState
    outcome: PipelineOutcome
    reason: str
    evaluated_at: datetime
    coverage_snapshot_id: str = ""
    validation_snapshot_id: str = ""

    def __post_init__(self) -> None:
        for name in ("decision_id", "product_slug", "run_id", "reason"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.gate_kind, PipelineGateKind):
            raise ContractError("pipeline gate kind is not recognized")
        if not isinstance(self.outcome, PipelineOutcome):
            raise ContractError("pipeline outcome is not recognized")
        for name in ("from_state", "to_state"):
            if not isinstance(getattr(self, name), ReleaseState):
                raise ContractError(f"pipeline {name} is not a recognized release state")
        utc(self.evaluated_at, "evaluated_at")


def launch_refusal(
    *, readiness: ReleaseReadiness, product_slug: str
) -> tuple[PipelineOutcome, tuple[str, ...]] | None:
    """Refuse a launch whose readiness is not green, whoever asked for it.

    Returns ``None`` when the launch may proceed.
    """

    if readiness.product_slug != product_slug:
        raise ContractError("readiness belongs to a different product")
    if readiness.is_green:
        return None
    outcome = (
        PipelineOutcome.PARK
        if readiness.readiness is Readiness.PARKED
        else PipelineOutcome.BLOCK
    )
    return outcome, readiness.blocking_reasons


@dataclass(frozen=True, slots=True)
class TaskBatch:
    """The record of one generated batch of build tasks, and what it targeted."""

    batch_id: str
    binding_id: str
    product_slug: str
    generated_by_move_id: str
    batch_mode: str
    errors_only: bool
    target_gap_count: int
    tasks_created: int
    coverage_snapshot_id: str
    validation_snapshot_id: str
    created_at: datetime
    rule_filter: str = ""

    def __post_init__(self) -> None:
        for name in (
            "batch_id",
            "binding_id",
            "product_slug",
            "generated_by_move_id",
            "coverage_snapshot_id",
            "validation_snapshot_id",
        ):
            required(str(getattr(self, name)), name)
        if self.batch_mode not in {"rule", "chain"}:
            raise ContractError("batch mode must be rule or chain")
        if self.target_gap_count < 0 or self.tasks_created < 0:
            raise ContractError("batch counts must be nonnegative")
        utc(self.created_at, "created_at")
        if self.rule_filter:
            required(self.rule_filter, "rule_filter")


@dataclass(frozen=True, slots=True)
class MirroredTask:
    """A build task as the control plane last saw it. The build system owns the truth."""

    task_id: str
    batch_id: str
    external_task_id: str
    rule: str
    claim_state: ClaimState
    fix_commands_present: bool
    anchor_requirement_id: str = ""
    claimed_by_move_id: str = ""
    commit_result_move_id: str = ""

    def __post_init__(self) -> None:
        for name in ("task_id", "batch_id", "external_task_id", "rule"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.claim_state, ClaimState):
            raise ContractError("task claim state is not recognized")


@dataclass(frozen=True, slots=True)
class MirrorDivergence:
    """Where the mirror disagrees with the build system. Surfaced, never absorbed."""

    task_id: str
    mirrored_state: ClaimState
    observed_state: ClaimState
    reason: str


def reconcile_tasks(
    mirrored: tuple[MirroredTask, ...], observed: dict[str, ClaimState]
) -> tuple[MirrorDivergence, ...]:
    """Compare the mirror against observed build state.

    Task throughput is not convergence. This says only whether the mirror is honest about
    what the build system did; whether gaps closed is measured from a fresh snapshot.
    """

    divergences: list[MirrorDivergence] = []
    for task in mirrored:
        state = observed.get(task.external_task_id)
        if state is None:
            divergences.append(
                MirrorDivergence(
                    task_id=task.task_id,
                    mirrored_state=task.claim_state,
                    observed_state=task.claim_state,
                    reason=(
                        f"task {task.external_task_id} is no longer reported by the build "
                        "system; its state is unknown, not complete"
                    ),
                )
            )
            continue
        if state is not task.claim_state:
            divergences.append(
                MirrorDivergence(
                    task_id=task.task_id,
                    mirrored_state=task.claim_state,
                    observed_state=state,
                    reason=(
                        f"task {task.external_task_id} is {state.value} in the build system "
                        f"but {task.claim_state.value} in the mirror"
                    ),
                )
            )
    return tuple(divergences)


@dataclass(frozen=True, slots=True)
class ProductHealth:
    """A rollup of one product's build and operating state, with named thresholds."""

    product_slug: str
    captured_at: datetime
    coverage_pct: float
    open_error_gaps: int
    open_warning_gaps: int
    ratchet_delta: int
    readiness: Readiness | None
    #: Open build tasks, or None where this product has no build-task store to read. A host
    #: whose build system keeps its own queue outside the control plane cannot answer this,
    #: and a zero would say the queue is empty when the truth is that nobody looked.
    open_tasks: int | None
    parked_move_count: int

    def __post_init__(self) -> None:
        required(self.product_slug, "product_slug")
        utc(self.captured_at, "captured_at")
        for name in ("open_error_gaps", "open_warning_gaps", "parked_move_count"):
            if getattr(self, name) < 0:
                raise ContractError(f"{name} must be nonnegative")
        if self.open_tasks is not None and self.open_tasks < 0:
            raise ContractError("open_tasks must be nonnegative")
        if not 0 <= self.coverage_pct <= 1:
            raise ContractError("coverage percentage must fall between zero and one")

    @property
    def warning_trend(self) -> str:
        if self.ratchet_delta > 0:
            return "regressing"
        return "improving" if self.ratchet_delta < 0 else "flat"

    @property
    def health_score(self) -> str:
        """Derived from named thresholds, never a free-scored judgement."""

        if self.ratchet_delta > 0 or self.open_error_gaps > 10:
            return "degraded"
        if self.open_error_gaps > 0 or self.parked_move_count > 10:
            return "at_risk"
        if self.readiness is None and self.coverage_pct < 0.5:
            return "stalled"
        return "healthy"

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_slug": self.product_slug,
            "captured_at": self.captured_at.isoformat(),
            "coverage_pct": self.coverage_pct,
            "open_error_gaps": self.open_error_gaps,
            "open_warning_gaps": self.open_warning_gaps,
            "warning_ratchet_trend": self.warning_trend,
            "release_readiness": self.readiness.value if self.readiness else "n/a",
            "open_tasks": self.open_tasks if self.open_tasks is not None else "unmeasured",
            "parked_move_count": self.parked_move_count,
            "health_score": self.health_score,
        }


def pipeline_signals(health: ProductHealth) -> dict[str, float]:
    """The portfolio metrics this product contributes to the nightly rollup.

    A metric this product cannot measure is absent from the rollup rather than present as a
    zero. A rollup that averages an unmeasured queue as empty reports a portfolio healthier
    than anybody observed.
    """

    rows = {
        "coverage_pct": health.coverage_pct,
        "open_error_gaps": float(health.open_error_gaps),
        "open_warning_gaps": float(health.open_warning_gaps),
        "warning_ratchet_delta": float(health.ratchet_delta),
        "approval_queue_depth": float(health.parked_move_count),
    }
    if health.open_tasks is not None:
        rows["open_build_tasks"] = float(health.open_tasks)
    return rows


def binding_required_refusal(*, move_type: str, product_slug: str, bound: bool) -> str:
    """The reason a pipeline move cannot run on an unbound product."""

    if bound or move_type in {"onboard_product", "bind_wlg_project"}:
        return ""
    return (
        f"no_wlg_binding: {product_slug} is not bound to a build project, so {move_type} "
        "has nothing to read"
    )


def snapshot_identity(*, product_slug: str, captured_at: datetime, registry_sha256: str) -> str:
    return stable_fingerprint(
        {
            "product_slug": product_slug,
            "captured_at": captured_at.isoformat(),
            "registry_sha256": registry_sha256,
        }
    )


__all__ = [
    "WLG_GATE_COMPONENTS",
    "BindingStatus",
    "ClaimState",
    "CoverageSnapshot",
    "GateManifestEntry",
    "GateStatus",
    "MirrorDivergence",
    "MirroredTask",
    "PipelineGateDecision",
    "PipelineGateKind",
    "PipelineOutcome",
    "PredicateKind",
    "ProductGateManifest",
    "ProductHealth",
    "Readiness",
    "RegistryRef",
    "ReleaseReadiness",
    "TaskBatch",
    "ValidationSnapshot",
    "WLGProjectBinding",
    "active_binding",
    "binding_required_refusal",
    "evaluate_release_readiness",
    "launch_refusal",
    "pipeline_signals",
    "reconcile_tasks",
    "snapshot_identity",
]
