"""Refusal, identity, recovery and unknown-observation behavior across the nine core modules.

Written against the coverage gaps root measured on the integrated source. These are not
mirrored implementation tests and not an inventory of lines: each one names a contract an
operator or a caller depends on, and each calibrated fault sits beside the ordinary case it
would otherwise be indistinguishable from.

Four kinds of behavior, because those are what a control plane gets wrong expensively:

  refusal      a malformed contract is rejected where it is built, not where it is read
  identity     a record is bound to the thing it is about, not merely well-formed
  recovery     what happens after a person answers, a repair lands, or a run is retried
  unknown      a measurement nobody took is reported as absent, never as zero

No database, provider, sleep or network. Every fixture is a small immutable value.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from aeos_kernel.approvals import (
    Approval,
    ApprovalStatus,
    ParkCause,
    ParkRecord,
    SeedBatch,
    expire_overdue,
    park_move,
    queue_depth,
    resume_from_approval,
    seed_batch,
)
from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapRow, GapSeverity, error_gaps
from aeos_kernel.gates import (
    Comparison,
    ConvergenceCheck,
    ExitSet,
    Gate,
    GateDecision,
    GateOutcome,
    Run,
    RunStatus,
    Signal,
    SignalPredicate,
    Stage,
    StopRule,
    evaluate_gate,
)
from aeos_kernel.improvement import (
    DifficultyKind,
    DifficultyObservation,
    ImprovementKind,
    ImprovementRequest,
    ObservationCoverage,
    RecurrenceThreshold,
    ResolutionState,
    ShippedChange,
    SummaryAuthority,
    assess_resolution,
)
from aeos_kernel.modules import Module, ModuleRegistry, MoveFamily, PriorityClass, load_modules
from aeos_kernel.moves import (
    ExecStatus,
    Move,
    MoveDecision,
    MoveLedgerEntry,
    MoveRequest,
    RequestedBy,
    SettlementRefusal,
    assert_unmutated,
    duplicate_of,
    graduation_state,
    record_outcome,
    settle_external,
)
from aeos_kernel.pipeline import (
    CoverageSnapshot,
    ProductHealth,
    Readiness,
    ValidationSnapshot,
)
from aeos_kernel.registry import (
    FamilyRegistry,
    Gating,
    OwnerKind,
    ProductFamilyKey,
    ProductOwner,
    ProfileFieldSpec,
    ProfileFieldType,
    manifest_from_mapping,
)
from aeos_kernel.scheduling import (
    Channel,
    ChannelKind,
    ChannelState,
    ProductFault,
    ValidationScope,
    admit_move,
    run_scoped_validation,
)
from tests.factories_control_plane import NOW, TODAY, manifest, pipeline_module

SLUG = "fictional-app"
LATER = NOW + dt.timedelta(hours=4)


# --------------------------------------------------------------------------------------
# registry — who is accountable, and what a family will accept as a profile
# --------------------------------------------------------------------------------------


def test_an_owner_row_names_a_product_a_role_and_a_kind() -> None:
    owner = ProductOwner(
        product_slug=SLUG, role="fictional.owner", owner_kind=OwnerKind.PRODUCT_LEAD, since=TODAY
    )
    assert owner.as_dict()["owner_kind"] == "product_lead"
    assert owner.as_dict()["escalation_role"] == ""


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"product_slug": ""}, "product_slug"),
        ({"role": ""}, "owner role"),
        ({"owner_kind": "product_lead"}, "owner kind is not recognized"),
        ({"since": "2026-09-13"}, "owner since must be a date"),
    ],
)
def test_an_owner_row_that_cannot_say_who_is_accountable_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    """Accountability is the one field a control plane cannot infer later."""

    fields: dict[str, Any] = {
        "product_slug": SLUG,
        "role": "fictional.owner",
        "owner_kind": OwnerKind.PRODUCT_LEAD,
        "since": TODAY,
        **kwargs,
    }
    with pytest.raises(ContractError, match=refusal):
        ProductOwner(**fields)


def test_ordinary_gating_thresholds_are_accepted() -> None:
    assert Gating().as_dict()["graduation_count"] == 25


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"graduation_count": 0}, "positive graduation"),
        ({"seed_approval_count": -1}, "nonnegative"),
        ({"judgment_confidence_gate": 0}, r"\(0, 1\]"),
        ({"judgment_confidence_gate": 1.5}, r"\(0, 1\]"),
        ({"park_ttl_hours": 0}, "windows must be positive"),
        ({"stale_claim_days": 0}, "windows must be positive"),
    ],
)
def test_a_gating_threshold_outside_its_range_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    """These are the numbers that decide when an agent stops asking a person.

    A confidence gate of zero would graduate everything on its first run, and a park window
    of zero hours would expire every approval before anyone read it.
    """

    with pytest.raises(ContractError, match=refusal):
        Gating(**kwargs)


def test_a_profile_field_says_which_value_it_rejected_and_what_it_would_accept() -> None:
    spec = ProfileFieldSpec(
        name="liability_class", field_type=ProfileFieldType.ENUM, allowed_values=("A", "B")
    )
    assert spec.violation("A") == ""
    assert "not one of: A, B" in spec.violation("Z")
    assert spec.violation(7) == "liability_class must be enum"


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"field_type": ProfileFieldType.ENUM, "allowed_values": ()}, "must declare allowed"),
        (
            {"field_type": ProfileFieldType.ENUM, "allowed_values": ("A", "A")},
            "values must be unique",
        ),
        (
            {"field_type": ProfileFieldType.BOOLEAN, "allowed_values": ("A",)},
            "cannot constrain values by type",
        ),
    ],
)
def test_a_profile_field_that_cannot_be_checked_is_refused_at_declaration(
    kwargs: dict[str, Any], refusal: str
) -> None:
    """An enum with no members admits everything, which is the opposite of an enum."""

    with pytest.raises(ContractError, match=refusal):
        ProfileFieldSpec(name="liability_class", **kwargs)


def test_an_unregistered_family_is_named_rather_than_returned_as_none_to_a_caller() -> None:
    """`get` is for a caller that has an alternative; `require` is for one that does not."""

    registry = FamilyRegistry()
    assert registry.get(ProductFamilyKey.CONSUMER_APP) is None
    with pytest.raises(ContractError, match="is not registered"):
        registry.require(ProductFamilyKey.CONSUMER_APP)


def test_a_manifest_mapping_missing_a_key_says_which_one() -> None:
    """Recovery: the host reads this from stored policy, so the message is the repair."""

    with pytest.raises(ContractError, match="manifest mapping is missing"):
        manifest_from_mapping(SLUG, {"modules_enabled": ["pipeline"]}, version="1.0.0")


# --------------------------------------------------------------------------------------
# modules — what is registered, and what a missing dependency takes down with it
# --------------------------------------------------------------------------------------


def test_a_module_registry_answers_which_module_owns_a_move_type() -> None:
    registry = ModuleRegistry((pipeline_module(),))
    found = registry.family("launch_product")
    assert found is not None and found.module_key == "pipeline"
    assert registry.family("not_a_move") is None


def test_a_module_whose_dependency_is_absent_is_dropped_and_says_what_it_wanted() -> None:
    """The module that will not load is a capability the product is counting on."""

    dependent = Module(
        key="outreach",
        version="1.0.0",
        rule_profile_ref="fictional.outreach@1",
        move_families=(outreach_family(),),
        module_dependencies=("absent_module",),
    )
    loaded = load_modules(
        registry=ModuleRegistry((dependent,)),
        manifest=manifest(SLUG, modules=("outreach",)),
        available_rails=frozenset({"outreach.requires_evidence_path"}),
        detected_at=NOW,
    )
    assert loaded.is_active("outreach") is False
    assert loaded.family("post_update") is None
    assert any("absent_module" in gap.reason for gap in loaded.gaps)


def outreach_family(move_type: str = "post_update", **kwargs: Any) -> MoveFamily:
    fields: dict[str, Any] = {
        "move_type": move_type,
        "module_key": "outreach",
        "priority_class": PriorityClass.NORMAL,
        "owner_role": "fictional.owner",
        "approval_policy": "fictional.owner_attested",
        "evidence_kinds": ("record_row",),
        "rails": ("outreach.requires_evidence_path",),
        "human_override": True,
        **kwargs,
    }
    return MoveFamily(**fields)


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"move_families": ()}, "registers no move family"),
        (
            {"move_families": (outreach_family(), outreach_family())},
            "registers a move type twice",
        ),
        ({"module_dependencies": ("pipeline", "pipeline")}, "must be unique"),
        ({"module_dependencies": ("outreach",)}, "depend on itself"),
    ],
)
def test_a_module_that_could_not_be_loaded_coherently_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    """Each of these would leave a move type with no owner, or two."""

    fields: dict[str, Any] = {
        "key": "outreach",
        "version": "1.0.0",
        "rule_profile_ref": "fictional.outreach@1",
        "move_families": (outreach_family(),),
        **kwargs,
    }
    with pytest.raises(ContractError, match=refusal):
        Module(**fields)


def test_a_family_that_never_graduates_must_be_one_that_parks() -> None:
    """Otherwise the declaration is about a decision nobody was ever asked to make."""

    with pytest.raises(ContractError, match="only a parking family"):
        outreach_family(human_override=False, never_graduates=True)


# --------------------------------------------------------------------------------------
# moves — identity, and what happens on the second attempt
# --------------------------------------------------------------------------------------


def move_for(**kwargs: Any) -> Move:
    fields: dict[str, Any] = {
        "move_id": "move_fictional_1",
        "move_request_id": "request_fictional_1",
        "product_slug": SLUG,
        "move_type": "capture_coverage",
        "decision": MoveDecision.SHIP,
        "exec_status": ExecStatus.SETTLED,
        "as_of": TODAY,
        "rulepack_version": "1.0.0",
        "manifest_version": "1.0.0",
        "idempotency_key": "key-1",
        "data_snapshot_refs": ("snapshot:1",),
        "evidence_refs": ("evidence:1",),
        **kwargs,
    }
    return Move(**fields)


def test_a_repeat_of_a_committed_move_finds_it_and_a_new_one_does_not() -> None:
    """Identity: the second attempt must recognize the first, or it executes twice."""

    committed = (move_for(),)
    assert duplicate_of(idempotency_key="key-1", committed=committed) is not None
    assert duplicate_of(idempotency_key="key-2", committed=committed) is None


def test_a_ledger_entry_cannot_close_a_move_it_is_not_about() -> None:
    """Identity: the entry freezes one move, and it has to be that move."""

    move = move_for()
    entry = record_outcome(
        move=move,
        recorded_at=NOW,
        artifact_uri="fictional://artifact/1",
        artifact_sha256="0" * 64,
    )
    assert_unmutated(move, entry)
    elsewhere = MoveLedgerEntry(
        entry_id=entry.entry_id,
        move_id="move_somebody_elses",
        move_digest=entry.move_digest,
        disposition=entry.disposition,
        recorded_at=NOW,
        artifact_uri=entry.artifact_uri,
        artifact_sha256=entry.artifact_sha256,
    )
    with pytest.raises(ContractError, match="belongs to a different move"):
        assert_unmutated(move, elsewhere)


def test_an_already_settled_move_refuses_a_second_settlement_and_says_so() -> None:
    """Recovery: a retry after a crash must not mint a second outcome."""

    refusal = settle_external(
        original=move_for(exec_status=ExecStatus.SETTLED),
        observation="the external action completed",
        observed_snapshot_ref="snapshot:2",
        settled_at=LATER,
    )
    assert isinstance(refusal, SettlementRefusal)
    assert "already settled" in refusal.reason


def test_an_in_flight_move_settles_into_a_new_record_that_cites_what_was_observed() -> None:
    """Control: the refusal above is the state, not settlement being impossible."""

    settled = settle_external(
        original=move_for(exec_status=ExecStatus.AWAITING_EXTERNAL),
        observation="the external action completed",
        observed_snapshot_ref="snapshot:2",
        settled_at=LATER,
    )
    assert isinstance(settled, Move)
    assert settled.exec_status is ExecStatus.SETTLED
    assert settled.data_snapshot_refs == ("snapshot:2",)
    assert settled.move_id != "move_fictional_1"


def test_a_parked_move_settles_through_its_approval_and_not_by_observation() -> None:
    refusal = settle_external(
        original=move_for(decision=MoveDecision.PARKED, exec_status=ExecStatus.QUEUED),
        observation="somebody said yes in a meeting",
        observed_snapshot_ref="snapshot:2",
        settled_at=LATER,
    )
    assert isinstance(refusal, SettlementRefusal)
    assert "through its approval" in refusal.reason


def test_a_family_that_does_not_park_has_no_graduation_to_reach() -> None:
    capture = next(
        item for item in pipeline_module().move_families if item.move_type == "capture_coverage"
    )
    state = graduation_state(
        family=capture, product_slug=SLUG, approved_count=99, reversal_count=0, threshold=25
    )
    assert state.eligible is False
    assert "does not park" in state.reason


def test_a_reserved_decision_never_graduates_however_many_times_it_was_approved() -> None:
    launch = next(
        item for item in pipeline_module().move_families if item.move_type == "launch_product"
    )
    state = graduation_state(
        family=launch, product_slug=SLUG, approved_count=500, reversal_count=0, threshold=25
    )
    assert state.eligible is False
    assert "permanently reserved" in state.reason


@pytest.mark.parametrize(
    ("approved", "reversals", "expected"),
    [(24, 0, "24 of 25 approvals"), (30, 1, "graduation is revoked by the first reversal")],
)
def test_graduation_is_withheld_and_says_which_condition_withheld_it(
    approved: int, reversals: int, expected: str
) -> None:
    state = graduation_state(
        family=outreach_family(),
        product_slug=SLUG,
        approved_count=approved,
        reversal_count=reversals,
        threshold=25,
    )
    assert state.eligible is False
    assert expected in state.reason


# --------------------------------------------------------------------------------------
# approvals — what the person actually answered, and what expiry does
# --------------------------------------------------------------------------------------


def parked_pair() -> tuple[ParkRecord, Approval]:
    return park_move(
        move=move_for(
            decision=MoveDecision.PARKED, exec_status=ExecStatus.QUEUED, evidence_refs=()
        ),
        cause=ParkCause.ALWAYS_PARKS,
        reason_operator="Promoting is yours to decide.",
        choice_set=("promote",),
        payload_preview={"release_state_after": "release_candidate"},
        parked_at=NOW,
        park_ttl_hours=72,
    )


def test_a_rejected_approval_declines_the_move_and_keeps_the_reason_given() -> None:
    """Recovery: no is an answer, and the move records which answer it was."""

    _, approval = parked_pair()
    answered = Approval(
        approval_id=approval.approval_id,
        move_id=approval.move_id,
        park_id=approval.park_id,
        status=ApprovalStatus.REJECTED,
        chosen="promote",
        reason_operator=approval.reason_operator,
        payload_preview=dict(approval.payload_preview),
        payload_preview_digest=approval.payload_preview_digest,
        choice_set=approval.choice_set,
        decided_by="fictional.owner",
        decided_at=LATER,
        decision_note="not this week",
    )
    outcome = resume_from_approval(approval=answered, now=LATER)
    assert outcome.decision is MoveDecision.DECLINE
    assert outcome.reason == "not this week"


def test_an_approved_move_runs_only_the_payload_that_was_previewed() -> None:
    _, approval = parked_pair()
    answered = Approval(
        approval_id=approval.approval_id,
        move_id=approval.move_id,
        park_id=approval.park_id,
        status=ApprovalStatus.APPROVED,
        chosen="promote",
        reason_operator=approval.reason_operator,
        payload_preview=dict(approval.payload_preview),
        payload_preview_digest=approval.payload_preview_digest,
        choice_set=approval.choice_set,
        decided_by="fictional.owner",
        decided_at=LATER,
    )
    outcome = resume_from_approval(approval=answered, now=LATER)
    assert outcome.decision is MoveDecision.SHIP
    assert outcome.execute_payload == {"release_state_after": "release_candidate"}

    # The digest is what binds the answer to what was shown, and it is checked where the
    # approval is built rather than where it is resumed — so an edited preview never reaches
    # a caller at all.
    with pytest.raises(ContractError, match="digest does not match"):
        Approval(
            approval_id=answered.approval_id,
            move_id=answered.move_id,
            park_id=answered.park_id,
            status=ApprovalStatus.APPROVED,
            chosen="promote",
            reason_operator=answered.reason_operator,
            payload_preview={"release_state_after": "launched"},
            payload_preview_digest=answered.payload_preview_digest,
            choice_set=answered.choice_set,
            decided_by="fictional.owner",
            decided_at=LATER,
        )


def test_expiry_touches_only_an_approval_still_waiting_for_an_answer() -> None:
    """An answered approval is not re-opened by the clock passing its window."""

    park_record, approval = parked_pair()
    answered = Approval(
        approval_id=approval.approval_id,
        move_id=approval.move_id,
        park_id=approval.park_id,
        status=ApprovalStatus.APPROVED,
        chosen="promote",
        reason_operator=approval.reason_operator,
        payload_preview=dict(approval.payload_preview),
        payload_preview_digest=approval.payload_preview_digest,
        choice_set=approval.choice_set,
        decided_by="fictional.owner",
        decided_at=LATER,
    )
    long_after = NOW + dt.timedelta(days=30)
    assert expire_overdue((answered,), (park_record,), now=long_after) == ()
    expired = expire_overdue((approval,), (park_record,), now=long_after)
    assert [item.status for item in expired] == [ApprovalStatus.EXPIRED]
    # Still the operator's backlog: expiry marks the approval, it does not answer it.
    assert queue_depth((approval,)) == 1


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"choice_set": ()}, "at least one choice"),
        ({"choice_set": ("promote", "promote")}, "choices must be unique"),
        ({"expires_at": NOW - dt.timedelta(hours=1)}, "must expire after it was created"),
    ],
)
def test_a_park_that_could_not_be_answered_is_refused_where_it_is_built(
    kwargs: dict[str, Any], refusal: str
) -> None:
    park, _ = parked_pair()
    fields: dict[str, Any] = {
        "park_id": park.park_id,
        "move_id": park.move_id,
        "product_slug": park.product_slug,
        "move_type": park.move_type,
        "cause": park.cause,
        "reason_operator": park.reason_operator,
        "choice_set": park.choice_set,
        "parked_at": park.parked_at,
        "expires_at": park.expires_at,
        **kwargs,
    }
    with pytest.raises(ContractError, match=refusal):
        ParkRecord(**fields)


def test_a_seed_sitting_gathers_only_the_onboarding_parks() -> None:
    """A sitting is how the parks are shown, never a single yes that covers them all."""

    park, approval = parked_pair()
    batch = seed_batch(product_slug=SLUG, approvals=(approval,), parks=(park,))
    # This park is an always-parks decision, not a seed one, so it is not in the sitting.
    assert batch.item_count == 0


def test_a_seed_sitting_refuses_to_list_one_approval_twice() -> None:
    """Identity: a sitting that counted one decision twice would over-report the backlog."""

    _, approval = parked_pair()
    assert SeedBatch(product_slug=SLUG, approvals=(approval,)).item_count == 1
    with pytest.raises(ContractError, match="cannot list one approval twice"):
        SeedBatch(product_slug=SLUG, approvals=(approval, approval))


# --------------------------------------------------------------------------------------
# gates — an unmeasured metric, and a repair that did not converge
# --------------------------------------------------------------------------------------


def test_an_optional_predicate_passes_on_an_absent_reading_and_a_required_one_does_not() -> None:
    """Unknown: the two readings differ, and the predicate declares which it wants."""

    required_reading = SignalPredicate(
        metric="coverage_pct", window="per_reading", comparison=Comparison.AT_LEAST, threshold=1
    )
    optional_reading = SignalPredicate(
        metric="coverage_pct",
        window="per_reading",
        comparison=Comparison.AT_LEAST,
        threshold=1,
        required_observation=False,
    )
    assert "has not been measured" in required_reading.unmet_reason((), product_slug=SLUG)
    assert optional_reading.unmet_reason((), product_slug=SLUG) == ""


def test_an_exit_set_states_its_condition_in_words_a_builder_can_implement() -> None:
    exit_set = ExitSet(
        name="fictional.exit",
        signal_predicates=(
            SignalPredicate(
                metric="coverage_pct",
                window="per_reading",
                comparison=Comparison.AT_LEAST,
                threshold=1,
            ),
        ),
        gap_types_in_scope=("fictional_gap",),
    )
    sentence = exit_set.sentence
    assert "coverage_pct over per_reading must be at least 1" in sentence
    assert "open error gaps (fictional_gap) must be at most 0" in sentence


def test_a_gate_cannot_decide_a_run_from_another_module() -> None:
    """Identity: gates and runs are both per-module, and crossing them decides nothing real."""

    gate = Gate(
        gate_id="fictional.gate",
        module_key="pipeline",
        from_stage=Stage.VALIDATE,
        to_stage=Stage.SCALE,
        exit_set=ExitSet(name="fictional.exit", gap_types_in_scope=("fictional_gap",)),
    )
    run = Run(
        run_id="run-1",
        product_slug=SLUG,
        module_key="outreach",
        stage=Stage.VALIDATE,
        status=RunStatus.RUNNING,
        started_at=NOW,
    )
    with pytest.raises(ContractError, match="different modules"):
        evaluate_gate(gate=gate, run=run, signals=(), gaps=(), evaluated_at=NOW)


@pytest.mark.parametrize(
    ("converged", "closed", "new", "reasons", "expected"),
    [
        (True, ("gap-1",), (), (), "converged: 1 gap(s) closed"),
        (False, ("gap-1",), ("gap-2", "gap-3"), (), "1 closed but 2 new gap(s) appeared"),
        (False, (), (), ("coverage is short",), "did not converge: coverage is short"),
    ],
)
def test_a_convergence_check_says_which_of_the_three_outcomes_it_found(
    converged: bool,
    closed: tuple[str, ...],
    new: tuple[str, ...],
    reasons: tuple[str, ...],
    expected: str,
) -> None:
    """A repair that traded one gap for another is not the same as one that did not land."""

    check = ConvergenceCheck(
        product_slug=SLUG,
        gate_id="fictional.gate",
        converged=converged,
        closed_gap_ids=closed,
        new_gap_ids=new,
        reasons=reasons,
    )
    assert expected in check.sentence


@pytest.mark.parametrize(
    ("outcome", "reasons", "refusal"),
    [
        (GateOutcome.BLOCK, (), "must say why"),
        (GateOutcome.PASS, ("something",), "passing gate carries no blocking reasons"),
    ],
)
def test_a_gate_decision_that_contradicts_itself_is_refused(
    outcome: GateOutcome, reasons: tuple[str, ...], refusal: str
) -> None:
    with pytest.raises(ContractError, match=refusal):
        GateDecision(
            decision_id="decision-1",
            run_id="run-1",
            product_slug=SLUG,
            gate_id="fictional.gate",
            from_stage=Stage.VALIDATE,
            to_stage=Stage.SCALE,
            outcome=outcome,
            reasons=reasons,
            evaluated_at=NOW,
        )


def test_a_stop_rule_cannot_be_declared_as_something_that_passes_a_transition() -> None:
    with pytest.raises(ContractError, match="cannot pass a transition"):
        StopRule(
            name="fictional.stop",
            predicate=SignalPredicate(
                metric="ratchet_delta",
                window="per_reading",
                comparison=Comparison.ABOVE,
                threshold=0,
            ),
            outcome=GateOutcome.PASS,
            operator_reason="this would be a stop rule that stops nothing",
        )


def test_a_signal_records_a_number_and_refuses_anything_that_is_not_one() -> None:
    measured = Signal(
        product_slug=SLUG, metric="coverage_pct", value=0.78, window="per_reading", ts=NOW
    )
    assert measured.as_dict()["value"] == 0.78
    with pytest.raises(ContractError, match="must be numeric"):
        Signal(
            product_slug=SLUG, metric="coverage_pct", value=True, window="per_reading", ts=NOW
        )


# --------------------------------------------------------------------------------------
# gaps — severity, and what a scoped reader counts
# --------------------------------------------------------------------------------------


def gap(severity: GapSeverity, gap_type: str = "fictional_gap") -> GapRow:
    return GapRow(
        gap_type=gap_type,
        severity=severity,
        product_slug=SLUG,
        subject_ref="subject-1",
        reason="a fictional finding",
        detected_at=NOW,
    )


def test_only_errors_block_and_warnings_still_travel() -> None:
    rows = (gap(GapSeverity.ERROR), gap(GapSeverity.WARNING), gap(GapSeverity.INFO))
    assert len(error_gaps(rows)) == 1
    assert error_gaps(()) == ()


def test_a_gap_citing_the_same_evidence_twice_is_refused() -> None:
    """Identity: two references to one record is one reference, counted twice."""

    with pytest.raises(ContractError, match="evidence references must be unique"):
        GapRow(
            gap_type="fictional_gap",
            severity=GapSeverity.ERROR,
            product_slug=SLUG,
            subject_ref="subject-1",
            reason="a fictional finding",
            detected_at=NOW,
            evidence_refs=("evidence:1", "evidence:1"),
        )


# --------------------------------------------------------------------------------------
# pipeline — measurements that were never taken
# --------------------------------------------------------------------------------------


def coverage(total: int, covered: int) -> CoverageSnapshot:
    return CoverageSnapshot(
        snapshot_id="coverage:1",
        binding_id="binding-1",
        product_slug=SLUG,
        snapshot_ref="registry:1",
        captured_at=NOW,
        total_requirements=total,
        covered_requirements=covered,
        uncovered_requirement_ids=tuple(f"REQ-{n}" for n in range(total - covered)),
    )


def test_a_register_with_no_requirements_reports_no_coverage_rather_than_perfect_coverage() -> None:
    """Unknown: zero of zero is not 100%. An empty register has measured nothing."""

    assert coverage(0, 0).coverage_pct == 0.0
    assert coverage(4, 3).coverage_pct == 0.75


def validation(*, warnings: int, prior: int, captured_at: dt.datetime = NOW) -> ValidationSnapshot:
    return ValidationSnapshot(
        snapshot_id="validation:1",
        binding_id="binding-1",
        product_slug=SLUG,
        snapshot_ref="revision-1",
        captured_at=captured_at,
        error_gap_count=0,
        warning_gap_count=warnings,
        prior_warning_gap_count=prior,
        gate_status={"fictional_gate": True},
    )


def test_the_ratchet_holds_when_warnings_fall_or_hold_and_breaks_when_they_rise() -> None:
    """A release does not go out on a regression, however good the other numbers are."""

    assert validation(warnings=2, prior=5).ratchet_delta == -3
    assert validation(warnings=5, prior=5).ratchet_delta == 0
    assert validation(warnings=6, prior=5).ratchet_delta == 1


def test_a_reading_is_stale_only_against_a_threshold_somebody_declared() -> None:
    """A zero threshold means no staleness policy, not that everything is stale."""

    old = validation(warnings=0, prior=0, captured_at=NOW - dt.timedelta(hours=48))
    assert old.is_stale(now=NOW, threshold_hours=24) is True
    assert old.is_stale(now=NOW, threshold_hours=72) is False
    assert old.is_stale(now=NOW, threshold_hours=0) is False


def test_a_gate_component_that_is_not_a_boolean_is_refused() -> None:
    """The build system reports pass or fail; a string here would read as truthy."""

    with pytest.raises(ContractError, match="must be a boolean"):
        ValidationSnapshot(
            snapshot_id="validation:1",
            binding_id="binding-1",
            product_slug=SLUG,
            snapshot_ref="revision-1",
            captured_at=NOW,
            error_gap_count=0,
            warning_gap_count=0,
            prior_warning_gap_count=0,
            gate_status={"fictional_gate": "green"},
        )


def health(**kwargs: Any) -> ProductHealth:
    fields: dict[str, Any] = {
        "product_slug": SLUG,
        "captured_at": NOW,
        "coverage_pct": 1.0,
        "open_error_gaps": 0,
        "open_warning_gaps": 0,
        "ratchet_delta": 0,
        "readiness": Readiness.GREEN,
        "open_tasks": 0,
        "parked_move_count": 0,
        **kwargs,
    }
    return ProductHealth(**fields)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "healthy"),
        ({"ratchet_delta": 1}, "degraded"),
        ({"open_error_gaps": 11}, "degraded"),
        ({"open_error_gaps": 1}, "at_risk"),
        ({"parked_move_count": 11}, "at_risk"),
        ({"readiness": None, "coverage_pct": 0.2}, "stalled"),
    ],
)
def test_health_is_derived_from_named_thresholds_in_a_stated_order(
    kwargs: dict[str, Any], expected: str
) -> None:
    """A degraded product is not re-labelled at_risk because a later rule also matched."""

    assert health(**kwargs).health_score == expected


# --------------------------------------------------------------------------------------
# scheduling — one product's fault, and a shared channel's cooldown
# --------------------------------------------------------------------------------------


def request_for(slug: str = SLUG) -> MoveRequest:
    return MoveRequest(
        request_id="request-1",
        product_slug=slug,
        move_type="capture_coverage",
        as_of=TODAY,
        priority_class=PriorityClass.BACKGROUND,
        requested_by=RequestedBy.SCHEDULE,
        requested_at=NOW,
    )


def capture_family() -> MoveFamily:
    return next(
        item for item in pipeline_module().move_families if item.move_type == "capture_coverage"
    )


def test_another_product_s_fault_does_not_stop_this_one() -> None:
    """The carve-out is shared channels, and a product fault is not one."""

    fault = ProductFault(
        product_slug="somebody-else",
        fault_type="provider_unavailable",
        reason="its provider is down",
        detected_at=NOW,
    )
    admitted = admit_move(
        request=request_for(), family=capture_family(), faults=(fault,), channels=(), now=NOW
    )
    assert admitted is None


def test_this_product_s_fault_stops_it_and_names_the_scope_that_stopped_it() -> None:
    fault = ProductFault(
        product_slug=SLUG,
        fault_type="provider_unavailable",
        reason="its provider is down",
        detected_at=NOW,
    )
    refusal = admit_move(
        request=request_for(), family=capture_family(), faults=(fault,), channels=(), now=NOW
    )
    assert refusal is not None
    assert refusal.scope == f"product:{SLUG}"


def channel(state: ChannelState, **kwargs: Any) -> Channel:
    fields: dict[str, Any] = {
        "key": "fictional-domain",
        "kind": ChannelKind.EMAIL_DOMAIN,
        "state": state,
        "product_slugs": (SLUG,),
        **kwargs,
    }
    return Channel(**fields)


def test_a_cooling_channel_blocks_until_its_window_passes_and_then_stops_blocking() -> None:
    """Recovery: a cooldown is a wait, not a revocation, and it ends on its own."""

    cooling = channel(
        ChannelState.COOLDOWN,
        cooldown_until=LATER,
        cooldown_reason="a bounce rate the provider flagged",
    )
    assert cooling.blocks_outbound(now=NOW) is True
    assert cooling.blocks_outbound(now=LATER + dt.timedelta(minutes=1)) is False
    assert channel(ChannelState.ACTIVE).blocks_outbound(now=NOW) is False
    assert channel(ChannelState.REVOKED).blocks_outbound(now=NOW) is True


def test_a_channel_in_cooldown_must_say_why_and_until_when() -> None:
    """Without both, nobody can tell a wait from a silent failure."""

    with pytest.raises(ContractError, match="cooldown_reason"):
        channel(ChannelState.COOLDOWN, cooldown_until=LATER)
    with pytest.raises(ContractError, match="when it is reconsidered"):
        channel(ChannelState.COOLDOWN, cooldown_reason="a bounce rate the provider flagged")


def test_a_move_on_a_channel_it_does_not_send_on_is_refused_with_the_channel_scope() -> None:
    refusal = admit_move(
        request=request_for("somebody-else"),
        family=capture_family(),
        faults=(),
        channels=(channel(ChannelState.ACTIVE),),
        channel_key="fictional-domain",
        now=NOW,
    )
    assert refusal is not None
    assert refusal.scope == "channel:fictional-domain"


def test_a_validator_that_returned_something_outside_its_scope_is_refused() -> None:
    """A validator that quietly widened would pass unnoticed until the ledger made it slow."""

    scope = ValidationScope(product_slug=SLUG, subject_ids=("subject-1",))
    inside = run_scoped_validation(
        scope=scope,
        validator=lambda _scope: ((SLUG, "subject-1"),),
        belongs_to=lambda row: row,
    )
    assert inside == ((SLUG, "subject-1"),)
    with pytest.raises(ContractError, match="outside its scope"):
        run_scoped_validation(
            scope=scope,
            validator=lambda _scope: ((SLUG, "subject-9"),),
            belongs_to=lambda row: row,
        )


def test_an_unscoped_per_move_validation_is_refused_rather_than_rescanning_everything() -> None:
    with pytest.raises(ContractError, match="unscoped rescan is refused"):
        ValidationScope(product_slug=SLUG, subject_ids=())


# --------------------------------------------------------------------------------------
# improvement — how often, how many people, and what a zero means
# --------------------------------------------------------------------------------------


def observation(**kwargs: Any) -> DifficultyObservation:
    fields: dict[str, Any] = {
        "cluster_key": "cluster-1",
        "product_slug": SLUG,
        "difficulty_kind": DifficultyKind.UNCLEAR_INSTRUCTION,
        "surface": "fictional-maker",
        "occurrence_count": 5,
        "distinct_customer_count": 4,
        "window_started_at": NOW - dt.timedelta(days=7),
        "window_ended_at": NOW,
        "operator_summary": "the same step confuses people",
        "summary_authority": SummaryAuthority.AGENT_AUTHORED,
        "coverage": ObservationCoverage.COMPLETE,
        **kwargs,
    }
    return DifficultyObservation(**fields)


def test_a_threshold_asking_about_customers_is_never_met_by_a_count_nobody_kept() -> None:
    """Unknown: an unknown count is not low and it is not high."""

    threshold = RecurrenceThreshold(minimum_occurrences=3, minimum_distinct_customers=2)
    assert threshold.unmet_reason(observation()) == ""
    unknown = observation(distinct_customer_count=None)
    assert "cannot count that" in threshold.unmet_reason(unknown)
    # A producer that cannot identify customers has a threshold it can actually meet.
    assert RecurrenceThreshold.by_occurrences(3).unmet_reason(unknown) == ""


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"occurrence_count": 2, "distinct_customer_count": 2}, "2 occurrence(s)"),
        ({"distinct_customer_count": 1}, "1 distinct customer(s)"),
    ],
)
def test_a_difficulty_below_its_threshold_says_which_number_fell_short(
    kwargs: dict[str, Any], expected: str
) -> None:
    threshold = RecurrenceThreshold(minimum_occurrences=3, minimum_distinct_customers=2)
    assert expected in threshold.unmet_reason(observation(**kwargs))


@pytest.mark.parametrize(
    ("kwargs", "refusal"),
    [
        ({"occurrence_count": 0}, "at least one occurrence"),
        ({"distinct_customer_count": 9}, "cannot exceed occurrences"),
        ({"window_ended_at": NOW - dt.timedelta(days=14)}, "cannot end before it starts"),
        ({"support_refs": ("ref-1", "ref-1")}, "support references must be unique"),
    ],
)
def test_an_observation_that_does_not_describe_a_real_window_is_refused(
    kwargs: dict[str, Any], refusal: str
) -> None:
    with pytest.raises(ContractError, match=refusal):
        observation(**kwargs)


def test_a_threshold_that_could_never_be_met_is_refused_at_declaration() -> None:
    with pytest.raises(ContractError, match="at least one occurrence"):
        RecurrenceThreshold(minimum_occurrences=0)
    with pytest.raises(ContractError, match="at least one"):
        RecurrenceThreshold(minimum_distinct_customers=0)


def improvement_pair() -> tuple[ImprovementRequest, ShippedChange]:
    request = ImprovementRequest(
        request_id="improvement-1",
        cluster_key="cluster-1",
        product_slug=SLUG,
        improvement_kind=ImprovementKind.HELP_CONTENT,
        title="say which file the step wants",
        problem_statement="people cannot tell which file the step wants",
        requirement_ref="REQ-FICTIONAL-1",
        raised_at=NOW,
        observation_digest="0" * 64,
    )
    shipped = ShippedChange(
        request_id="improvement-1",
        release_ref="release-1",
        verification_ref="verification-1",
        shipped_at=NOW,
    )
    return request, shipped


def test_a_zero_from_an_indexed_reading_is_not_the_same_sentence_as_a_measured_zero() -> None:
    """Unknown: the coverage of the reading decides whether anyone may be told it is fixed."""

    request, shipped = improvement_pair()
    complete = assess_resolution(
        cluster_key="cluster-1",
        request=request,
        shipped=shipped,
        before_rate_per_week=8.0,
        after_rate_per_week=0.0,
        observation_window_complete=True,
        after_coverage=ObservationCoverage.COMPLETE,
    )
    partial = assess_resolution(
        cluster_key="cluster-1",
        request=request,
        shipped=shipped,
        before_rate_per_week=8.0,
        after_rate_per_week=0.0,
        observation_window_complete=True,
        after_coverage=ObservationCoverage.INDEXED_ONLY,
    )
    assert complete.state is not partial.state
    assert partial.state is ResolutionState.UNKNOWN


def test_a_missing_before_or_after_measurement_reads_as_unknown_not_as_success() -> None:
    request, shipped = improvement_pair()
    for before, after in ((None, 0.0), (8.0, None)):
        assessment = assess_resolution(
            cluster_key="cluster-1",
            request=request,
            shipped=shipped,
            before_rate_per_week=before,
            after_rate_per_week=after,
            observation_window_complete=True,
        )
        assert assessment.state is ResolutionState.UNKNOWN


@pytest.mark.parametrize("ratio", [0, 1.5, -0.5])
def test_an_improvement_ratio_outside_its_range_is_refused(ratio: float) -> None:
    """A ratio of zero would call any change an improvement."""

    with pytest.raises(ContractError, match=r"must fall in \(0, 1\]"):
        assess_resolution(
            cluster_key="cluster-1",
            request=None,
            shipped=None,
            before_rate_per_week=8.0,
            after_rate_per_week=4.0,
            observation_window_complete=True,
            improvement_ratio=ratio,
        )
