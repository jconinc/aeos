"""Readiness, gates and the path from a repeated difficulty to a verified fix."""

from __future__ import annotations

import datetime as dt

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapRow, GapSeverity
from aeos_kernel.gates import (
    Comparison,
    ExitSet,
    Gate,
    GateOutcome,
    Run,
    RunStatus,
    Signal,
    SignalPredicate,
    Stage,
    StopRule,
    evaluate_gate,
    re_measure_after_repair,
    stage_is_complete,
)
from aeos_kernel.improvement import (
    DifficultyKind,
    DifficultyObservation,
    ImprovementKind,
    ObservationCoverage,
    RecurrenceThreshold,
    ResolutionState,
    ShippedChange,
    SummaryAuthority,
    assert_shareable,
    assert_summary_admissible,
    assess_resolution,
    plan_follow_up,
    raise_improvement,
)
from aeos_kernel.pipeline import (
    ClaimState,
    CoverageSnapshot,
    GateManifestEntry,
    GateStatus,
    MirroredTask,
    PipelineOutcome,
    PredicateKind,
    ProductGateManifest,
    ProductHealth,
    Readiness,
    RegistryRef,
    ValidationSnapshot,
    WLGProjectBinding,
    active_binding,
    binding_required_refusal,
    evaluate_release_readiness,
    launch_refusal,
    pipeline_signals,
    reconcile_tasks,
)
from aeos_kernel.registry import LiabilityClass
from tests.factories_control_plane import DESK_FAMILY, NOW, manifest

SLUG = "fictional-app"


def registry_ref(suffix: str = "1") -> RegistryRef:
    return RegistryRef(
        project_id="fictionalproject",
        registry_locator=f"fictional://registry/{suffix}",
        registry_sha256=suffix[0] * 64 if suffix[0].isalpha() else "c" * 64,
        row_count=12,
        captured_at=NOW,
        snapshot_ref=f"snapshot-{suffix}",
    )


def coverage(
    *,
    total: int = 10,
    covered: int = 10,
    uncovered: tuple[str, ...] = (),
    unmet: tuple[tuple[str, str], ...] = (),
    by_kind: dict[str, object] | None = None,
) -> CoverageSnapshot:
    measured = {"Screen": {"required": 2, "satisfied": 2}} if by_kind is None else by_kind
    return CoverageSnapshot(
        snapshot_id="coverage-1",
        binding_id="binding-1",
        product_slug=SLUG,
        snapshot_ref="snapshot-1",
        captured_at=NOW,
        total_requirements=total,
        covered_requirements=covered,
        uncovered_requirement_ids=uncovered,
        unmet_kind_obligations=unmet,
        coverage_by_kind=measured,
    )


def validation(
    *,
    errors: int = 0,
    warnings: int = 4,
    prior_warnings: int = 4,
    triple: dict[str, bool] | None = None,
    captured_at: dt.datetime = NOW,
    by_rule: dict[str, object] | None = None,
) -> ValidationSnapshot:
    return ValidationSnapshot(
        snapshot_id="validation-1",
        binding_id="binding-1",
        product_slug=SLUG,
        snapshot_ref="snapshot-1",
        captured_at=captured_at,
        error_gap_count=errors,
        warning_gap_count=warnings,
        prior_warning_gap_count=prior_warnings,
        triple_gate_status=triple
        or {
            "spec_satisfied": True,
            "closure_valid": True,
            "net_delta_ok": True,
            "warning_ratchet": True,
        },
        gaps_by_rule=by_rule or {},
    )


def gate_manifest(
    *,
    entries: tuple[GateManifestEntry, ...] | None = None,
) -> ProductGateManifest:
    return ProductGateManifest(
        manifest_id="gate-manifest-1",
        product_slug=SLUG,
        gates=entries
        or (
            GateManifestEntry(
                gate_id="PGM-01-pilot-acceptance",
                description="Twenty-five fictional verdicts delivered to five distinct buyers",
                predicate_kind=PredicateKind.PILOT_COUNT,
                status=GateStatus.GREEN,
                launch_blocking=True,
                evidence_ref="fictional://pilot-ledger/1",
            ),
        ),
        source_ref="fictional://requirements#16",
        captured_at=NOW,
        snapshot_ref="snapshot-1",
    )


def readiness_now(**overrides: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "manifest": manifest(SLUG),
        "coverage": coverage(),
        "validation": validation(),
        "gate_manifest": gate_manifest(),
        "family_coverage_thresholds": {"min_overall": 0.9},
        "now": NOW,
    }
    values.update(overrides)
    return evaluate_release_readiness(**values)  # type: ignore[arg-type]


def test_a_complete_product_reads_green() -> None:
    result = readiness_now()
    assert result.readiness is Readiness.GREEN
    assert result.blocking_reasons == ()


def test_a_product_with_no_gate_manifest_is_blocked_rather_than_green() -> None:
    result = readiness_now(gate_manifest=None)
    assert result.readiness is Readiness.BLOCKED
    assert any("no_product_gate_manifest" in reason for reason in result.blocking_reasons)


def test_an_unmeasured_coverage_or_validation_snapshot_is_never_read_as_ready() -> None:
    for absent in ("coverage", "validation"):
        result = readiness_now(**{absent: None})
        assert result.readiness is Readiness.BLOCKED
        assert any("has been captured" in reason for reason in result.blocking_reasons)


def test_a_stale_validation_snapshot_parks_for_a_refresh_instead_of_green_lighting() -> None:
    result = readiness_now(
        validation=validation(captured_at=NOW - dt.timedelta(hours=72)),
    )
    assert result.readiness is Readiness.PARKED
    assert any("stale reading" in reason for reason in result.blocking_reasons)


def test_a_warning_ratchet_regression_blocks_the_release() -> None:
    result = readiness_now(validation=validation(warnings=17, prior_warnings=5))
    assert result.readiness is Readiness.BLOCKED
    assert any("warning gaps rose by 12" in reason for reason in result.blocking_reasons)


def test_the_build_gate_result_is_read_verbatim_not_softened() -> None:
    result = readiness_now(
        validation=validation(
            triple={
                "spec_satisfied": True,
                "closure_valid": True,
                "net_delta_ok": False,
                "warning_ratchet": True,
            }
        )
    )
    assert result.readiness is Readiness.BLOCKED
    assert any("net_delta_ok" in reason for reason in result.blocking_reasons)


def test_an_uncovered_requirement_becomes_an_ordinary_error_gap() -> None:
    snapshot = coverage(total=10, covered=8, uncovered=("REQ-FICTION-001", "REQ-FICTION-002"))
    gaps = snapshot.gaps()
    assert [gap.gap_type for gap in gaps] == ["coverage_requirement_uncovered"] * 2
    assert all(gap.severity is GapSeverity.ERROR for gap in gaps)
    result = readiness_now(coverage=snapshot)
    assert result.readiness is Readiness.BLOCKED
    assert any("coverage error gap" in reason for reason in result.blocking_reasons)


def test_a_required_shape_kind_with_no_shape_is_its_own_gap() -> None:
    snapshot = coverage(unmet=(("REQ-FICTION-003", "StateMachine"),))
    gaps = snapshot.gaps()
    assert gaps[0].gap_type == "coverage_kind_unmet"
    assert "requires a StateMachine shape" in gaps[0].reason


def test_per_kind_coverage_that_was_never_measured_reads_as_unmeasured() -> None:
    result = readiness_now(
        coverage=coverage(by_kind={}),
        family_coverage_thresholds={"min_overall": 0.9, "Screen": 2},
    )
    assert any("has not been measured" in reason for reason in result.blocking_reasons)


def test_a_named_blocking_rule_with_errors_blocks_whatever_the_totals_say() -> None:
    result = readiness_now(
        manifest=manifest(
            SLUG,
            release_policy={
                "max_open_error_gaps": 0,
                "block_on_error_rules": ["fictional_invalid_role_target"],
            },
        ),
        validation=validation(by_rule={"fictional_invalid_role_target": {"error": 2}}),
    )
    reasons = result.blocking_reasons
    assert any("fictional_invalid_role_target has 2" in reason for reason in reasons)


def test_a_class_c_product_without_its_class_selected_bars_cannot_read_green() -> None:
    result = readiness_now(manifest=manifest(SLUG, liability_class=LiabilityClass.C))
    assert result.readiness is Readiness.BLOCKED
    reasons = " ".join(result.blocking_reasons)
    assert "counsel_signoff" in reasons
    assert "insurance" in reasons


def test_a_class_a_product_takes_the_baseline_bar_set() -> None:
    """Control: the class-C refusal is the class, not the manifest being rejected outright."""

    assert readiness_now(manifest=manifest(SLUG, liability_class=LiabilityClass.A)).is_green


def test_an_open_launch_bar_blocks_and_names_itself() -> None:
    result = readiness_now(
        gate_manifest=gate_manifest(
            entries=(
                GateManifestEntry(
                    gate_id="PGM-02-eo-in-force",
                    description="Professional indemnity cover is in force before the first sale",
                    predicate_kind=PredicateKind.INSURANCE,
                    status=GateStatus.OPEN,
                    launch_blocking=True,
                ),
            )
        )
    )
    assert any("PGM-02-eo-in-force is open" in reason for reason in result.blocking_reasons)


def test_a_bar_for_another_regime_does_not_block_this_one() -> None:
    entries = (
        GateManifestEntry(
            gate_id="PGM-03-region-a",
            description="Region A statute pinning verified",
            predicate_kind=PredicateKind.STATUTE_PIN,
            status=GateStatus.GREEN,
            launch_blocking=True,
            evidence_ref="fictional://statute/a",
            regime_id="region-a",
        ),
        GateManifestEntry(
            gate_id="PGM-04-region-b",
            description="Region B statute pinning verified",
            predicate_kind=PredicateKind.STATUTE_PIN,
            status=GateStatus.OPEN,
            launch_blocking=True,
            regime_id="region-b",
        ),
    )
    live = readiness_now(gate_manifest=gate_manifest(entries=entries), regime_id="region-a")
    assert live.is_green
    slow = readiness_now(gate_manifest=gate_manifest(entries=entries), regime_id="region-b")
    assert not slow.is_green
    # A product-level read must not hide the region that is not live.
    aggregate = readiness_now(gate_manifest=gate_manifest(entries=entries))
    assert not aggregate.is_green


def test_a_waived_bar_records_the_evidence_that_waived_it() -> None:
    with pytest.raises(ContractError):
        GateManifestEntry(
            gate_id="PGM-05",
            description="A bar someone tried to wave through",
            predicate_kind=PredicateKind.CUSTOM,
            status=GateStatus.WAIVED,
            launch_blocking=True,
        )


def test_a_launch_against_a_blocked_gate_is_refused_whoever_asked() -> None:
    blocked = readiness_now(gate_manifest=None)
    outcome = launch_refusal(readiness=blocked, product_slug=SLUG)
    assert outcome is not None
    assert outcome[0] is PipelineOutcome.BLOCK
    assert launch_refusal(readiness=readiness_now(), product_slug=SLUG) is None


def test_a_launch_against_a_parked_gate_parks_rather_than_blocking() -> None:
    parked = readiness_now(validation=validation(captured_at=NOW - dt.timedelta(hours=72)))
    outcome = launch_refusal(readiness=parked, product_slug=SLUG)
    assert outcome is not None
    assert outcome[0] is PipelineOutcome.PARK


def test_readiness_for_one_product_is_not_accepted_for_another() -> None:
    with pytest.raises(ContractError):
        launch_refusal(readiness=readiness_now(), product_slug="fictional-desk")


def test_a_pipeline_move_on_an_unbound_product_has_nothing_to_read() -> None:
    assert binding_required_refusal(
        move_type="capture_coverage", product_slug=SLUG, bound=False
    ).startswith("no_wlg_binding")
    assert (
        binding_required_refusal(move_type="bind_wlg_project", product_slug=SLUG, bound=False) == ""
    )
    assert (
        binding_required_refusal(move_type="capture_coverage", product_slug=SLUG, bound=True) == ""
    )


def test_a_product_cannot_hold_two_active_bindings_at_once() -> None:
    def binding(identifier: str) -> WLGProjectBinding:
        return WLGProjectBinding(
            binding_id=identifier,
            product_slug=SLUG,
            project_id="fictionalproject",
            requirements_ref=registry_ref("a"),
            shape_ref=registry_ref("b"),
            bound_at=NOW,
            bound_by="fictional.owner",
        )

    assert active_binding((binding("binding-1"),), product_slug=SLUG) is not None
    with pytest.raises(ContractError):
        active_binding((binding("binding-1"), binding("binding-2")), product_slug=SLUG)


def test_a_task_the_build_system_stopped_reporting_is_unknown_not_complete() -> None:
    mirrored = MirroredTask(
        task_id="task-1",
        batch_id="batch-1",
        external_task_id="fictional-task-1",
        rule="fictional_rule",
        claim_state=ClaimState.CLAIMED,
        fix_commands_present=True,
    )
    divergences = reconcile_tasks((mirrored,), {})
    assert "is unknown, not complete" in divergences[0].reason
    # A mirror that matches produces no finding at all.
    assert reconcile_tasks((mirrored,), {"fictional-task-1": ClaimState.CLAIMED}) == ()


def test_a_mirror_that_disagrees_with_the_build_system_is_surfaced() -> None:
    mirrored = MirroredTask(
        task_id="task-1",
        batch_id="batch-1",
        external_task_id="fictional-task-1",
        rule="fictional_rule",
        claim_state=ClaimState.COMMITTED,
        fix_commands_present=True,
    )
    divergences = reconcile_tasks((mirrored,), {"fictional-task-1": ClaimState.FAILED})
    assert divergences[0].observed_state is ClaimState.FAILED


def test_health_is_derived_from_named_thresholds_not_a_free_score() -> None:
    regressing = ProductHealth(
        product_slug=SLUG,
        captured_at=NOW,
        coverage_pct=0.95,
        open_error_gaps=0,
        open_warning_gaps=9,
        ratchet_delta=4,
        readiness=Readiness.BLOCKED,
        open_tasks=2,
        parked_move_count=1,
    )
    assert regressing.health_score == "degraded"
    assert regressing.warning_trend == "regressing"
    healthy = ProductHealth(
        product_slug=SLUG,
        captured_at=NOW,
        coverage_pct=1.0,
        open_error_gaps=0,
        open_warning_gaps=0,
        ratchet_delta=-2,
        readiness=Readiness.GREEN,
        open_tasks=0,
        parked_move_count=0,
    )
    assert healthy.health_score == "healthy"
    assert pipeline_signals(healthy)["approval_queue_depth"] == 0.0


def growth_gate() -> Gate:
    return Gate(
        gate_id="fictional-validate-to-scale",
        module_key="outreach",
        from_stage=Stage.VALIDATE,
        to_stage=Stage.SCALE,
        exit_set=ExitSet(
            name="validate_to_scale",
            signal_predicates=(
                SignalPredicate("records_indexed", "14d", Comparison.AT_LEAST, 10),
                SignalPredicate("reply_rate", "7d", Comparison.AT_LEAST, 0.03),
            ),
            max_open_error_gaps=0,
        ),
        stop_rules=(
            StopRule(
                name="complaint_rate",
                predicate=SignalPredicate("complaint_rate", "7d", Comparison.AT_LEAST, 0.001),
                outcome=GateOutcome.PARK,
                operator_reason=(
                    "Complaints reached the threshold for this sending domain, so outbound "
                    "stops until someone looks at it."
                ),
            ),
        ),
    )


def run_at(stage: Stage = Stage.VALIDATE) -> Run:
    return Run(
        run_id="run-1",
        product_slug=SLUG,
        module_key="outreach",
        stage=stage,
        status=RunStatus.RUNNING,
        started_at=NOW,
    )


def signal(metric: str, value: float, window: str = "7d") -> Signal:
    return Signal(product_slug=SLUG, metric=metric, value=value, window=window, ts=NOW)


def test_a_stop_rule_outranks_healthy_growth_numbers() -> None:
    signals = (
        signal("records_indexed", 40, "14d"),
        signal("reply_rate", 0.2),
        signal("complaint_rate", 0.004),
    )
    decision = evaluate_gate(
        gate=growth_gate(), run=run_at(), signals=signals, gaps=(), evaluated_at=NOW
    )
    assert decision.outcome is GateOutcome.PARK
    assert decision.stop_rule_fired == "complaint_rate"


def test_the_same_numbers_pass_once_the_stop_rule_is_clear() -> None:
    """Control: the park above is the complaint rate, not the growth conditions."""

    signals = (
        signal("records_indexed", 40, "14d"),
        signal("reply_rate", 0.2),
        signal("complaint_rate", 0.0001),
    )
    decision = evaluate_gate(
        gate=growth_gate(), run=run_at(), signals=signals, gaps=(), evaluated_at=NOW
    )
    assert decision.outcome is GateOutcome.PASS


def test_a_metric_that_was_never_measured_is_unknown_rather_than_zero() -> None:
    decision = evaluate_gate(
        gate=growth_gate(),
        run=run_at(),
        signals=(signal("records_indexed", 40, "14d"),),
        gaps=(),
        evaluated_at=NOW,
    )
    assert decision.outcome is GateOutcome.BLOCK
    assert any("has not been measured" in reason for reason in decision.reasons)


def test_the_completion_predicate_is_the_gate_s_own_query() -> None:
    signals = (signal("records_indexed", 40, "14d"), signal("reply_rate", 0.2))
    gate = growth_gate()
    decision = evaluate_gate(gate=gate, run=run_at(), signals=signals, gaps=(), evaluated_at=NOW)
    complete = stage_is_complete(gate=gate, product_slug=SLUG, signals=signals, gaps=())
    assert (decision.outcome is GateOutcome.PASS) is complete
    # And they agree when the answer is no.
    blocked = evaluate_gate(gate=gate, run=run_at(), signals=(), gaps=(), evaluated_at=NOW)
    assert blocked.outcome is GateOutcome.BLOCK
    assert not stage_is_complete(gate=gate, product_slug=SLUG, signals=(), gaps=())


def test_another_product_s_gaps_never_enter_this_gate_s_scope() -> None:
    signals = (signal("records_indexed", 40, "14d"), signal("reply_rate", 0.2))
    foreign = GapRow(
        gap_type="coverage_requirement_uncovered",
        severity=GapSeverity.ERROR,
        product_slug="fictional-desk",
        subject_ref="REQ-OTHER-001",
        reason="a different product's problem",
        detected_at=NOW,
    )
    decision = evaluate_gate(
        gate=growth_gate(), run=run_at(), signals=signals, gaps=(foreign,), evaluated_at=NOW
    )
    assert decision.outcome is GateOutcome.PASS


def test_a_repair_that_trips_a_different_rule_has_not_converged() -> None:
    gate = growth_gate()
    signals = (signal("records_indexed", 40, "14d"), signal("reply_rate", 0.2))
    before = (
        GapRow(
            gap_type="stale_claim",
            severity=GapSeverity.ERROR,
            product_slug=SLUG,
            subject_ref="record-1",
            reason="the claim is older than the freshness window",
            detected_at=NOW,
        ),
    )
    after = (
        GapRow(
            gap_type="rate_limited",
            severity=GapSeverity.ERROR,
            product_slug=SLUG,
            subject_ref="record-1",
            reason="the republish tripped the rate limit",
            detected_at=NOW,
        ),
    )
    check = re_measure_after_repair(
        gate=gate,
        product_slug=SLUG,
        signals=signals,
        gaps_before=before,
        gaps_after=after,
    )
    assert not check.converged
    assert len(check.closed_gap_ids) == 1
    assert len(check.new_gap_ids) == 1
    assert "new gap(s) appeared" in check.sentence


def test_a_repair_that_actually_closed_its_gap_converges() -> None:
    """Control: the non-convergence above is the new gap, not the re-measurement itself."""

    gate = growth_gate()
    signals = (signal("records_indexed", 40, "14d"), signal("reply_rate", 0.2))
    before = (
        GapRow(
            gap_type="stale_claim",
            severity=GapSeverity.ERROR,
            product_slug=SLUG,
            subject_ref="record-1",
            reason="the claim is older than the freshness window",
            detected_at=NOW,
        ),
    )
    check = re_measure_after_repair(
        gate=gate, product_slug=SLUG, signals=signals, gaps_before=before, gaps_after=()
    )
    assert check.converged
    assert check.new_gap_ids == ()


def test_a_gate_that_leaves_a_stage_the_run_is_not_in_is_refused() -> None:
    with pytest.raises(ContractError):
        evaluate_gate(
            gate=growth_gate(),
            run=run_at(Stage.SEED),
            signals=(),
            gaps=(),
            evaluated_at=NOW,
        )


def test_an_exit_set_that_constrains_nothing_is_refused() -> None:
    with pytest.raises(ContractError):
        ExitSet(name="empty", signal_predicates=(), gap_types_in_scope=(), max_open_error_gaps=0)


def observation(*, occurrences: int = 6, customers: int = 4) -> DifficultyObservation:
    return DifficultyObservation(
        cluster_key="export-step-unclear",
        product_slug=SLUG,
        difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
        surface="export screen",
        occurrence_count=occurrences,
        distinct_customer_count=customers,
        window_started_at=NOW - dt.timedelta(days=28),
        window_ended_at=NOW,
        support_refs=("support-ref-1", "support-ref-2"),
        operator_summary="People cannot tell which of the two export buttons keeps their notes.",
        summary_authority=SummaryAuthority.AGENT_AUTHORED,
    )


def test_a_customer_s_own_words_cannot_reach_a_shared_improvement_record() -> None:
    for unsafe in (
        "someone@fictional.example",
        "+1 555 0100 999",
        'they wrote "I clicked export and my whole afternoon of notes disappeared again"',
    ):
        with pytest.raises(ContractError):
            assert_shareable(unsafe, "operator_summary")


def test_an_aggregate_description_of_the_same_problem_is_shareable() -> None:
    """Control: the fence rejects identifiers and quotes, not ordinary description."""

    assert assert_shareable(
        "People cannot tell which export button keeps their notes.", "operator_summary"
    )


def test_one_report_is_not_yet_a_pattern() -> None:
    assert (
        raise_improvement(
            observation=observation(occurrences=1, customers=1),
            threshold=RecurrenceThreshold(),
            improvement_kind=ImprovementKind.HELP_CONTENT,
            title="Clarify the export step",
            problem_statement="The export screen offers two buttons with no stated difference.",
            requirement_ref="REQ-FICTION-010",
            raised_at=NOW,
        )
        is None
    )


def raised():  # type: ignore[no-untyped-def]
    request = raise_improvement(
        observation=observation(),
        threshold=RecurrenceThreshold(),
        improvement_kind=ImprovementKind.PRODUCT_CHANGE,
        title="Name the export buttons by what they keep",
        problem_statement="The export screen offers two buttons with no stated difference.",
        requirement_ref="REQ-FICTION-010",
        raised_at=NOW,
    )
    assert request is not None
    return request


def test_a_raised_improvement_alone_does_not_claim_the_problem_is_solved() -> None:
    assessment = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=None,
        before_rate_per_week=1.5,
        after_rate_per_week=None,
        observation_window_complete=False,
    )
    assert assessment.state is ResolutionState.WORK_IN_PROGRESS
    assert not assessment.customer_follow_up_permitted


def shipped() -> ShippedChange:
    return ShippedChange(
        request_id=raised().request_id,
        release_ref="fictional-release-42",
        verification_ref="fictional-verification-7",
        shipped_at=NOW,
        change_refs=("fictional-change-1",),
    )


def test_a_shipped_and_verified_change_still_does_not_claim_the_customer_is_better_off() -> None:
    assessment = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=1.5,
        after_rate_per_week=None,
        observation_window_complete=False,
    )
    assert assessment.state is ResolutionState.SHIPPED_UNVERIFIED
    plan = plan_follow_up(assessment=assessment, observation=observation())
    assert not plan.permitted
    assert plan.notify_support_refs == ()
    assert "would claim more than has been observed" in plan.reason


def test_the_difficulty_is_resolved_only_once_an_observation_says_it_stopped() -> None:
    """A near-miss is still a miss: 1.5 a week down to 0.2 is people still hitting it."""

    nearly = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=1.5,
        after_rate_per_week=0.2,
        observation_window_complete=True,
    )
    assert nearly.state is ResolutionState.IMPROVED_NOT_RESOLVED
    assert not plan_follow_up(assessment=nearly, observation=observation()).permitted
    stopped = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=1.5,
        after_rate_per_week=0.0,
        observation_window_complete=True,
    )
    assert stopped.state is ResolutionState.VERIFIED_RESOLVED
    plan = plan_follow_up(
        assessment=stopped,
        observation=observation(),
        help_content_ref="fictional://help/export",
    )
    assert plan.permitted
    assert plan.notify_support_refs == ("support-ref-1", "support-ref-2")


def test_a_change_that_did_not_reduce_the_difficulty_is_not_reported_as_a_fix() -> None:
    assessment = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=1.5,
        after_rate_per_week=1.4,
        observation_window_complete=True,
    )
    assert assessment.state is ResolutionState.SHIPPED_UNVERIFIED
    assert "has not been shown to be resolved" in assessment.reason


def test_a_missing_after_measurement_is_unknown_rather_than_success() -> None:
    assessment = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=1.5,
        after_rate_per_week=None,
        observation_window_complete=True,
    )
    assert assessment.state is ResolutionState.UNKNOWN
    assert "not zero" in assessment.reason


def test_a_desk_family_threshold_still_reads_through_the_same_readiness_query() -> None:
    result = evaluate_release_readiness(
        manifest=manifest(SLUG),
        coverage=coverage(total=10, covered=8, uncovered=("REQ-FICTION-001", "REQ-FICTION-002")),
        validation=validation(),
        gate_manifest=gate_manifest(),
        family_coverage_thresholds=dict(DESK_FAMILY.release_coverage_thresholds),
        now=NOW,
    )
    assert result.readiness is Readiness.BLOCKED
    assert any("coverage is 80%" in reason for reason in result.blocking_reasons)


def test_an_absent_snapshot_does_not_hide_the_launch_bars_that_are_already_known() -> None:
    """An operator asking why a launch is blocked wants everything that blocks it.

    Stopping at the first missing input would report a snapshot and stay silent about four
    launch bars nobody has met, which reads as one small problem instead of five.
    """

    entries = (
        GateManifestEntry(
            gate_id="PGM-06-not-activated",
            description="The purchase surface is switched on",
            predicate_kind=PredicateKind.CUSTOM,
            status=GateStatus.OPEN,
            launch_blocking=True,
        ),
    )
    result = readiness_now(coverage=None, gate_manifest=gate_manifest(entries=entries))
    assert result.readiness is Readiness.BLOCKED
    assert any("no coverage snapshot" in reason for reason in result.blocking_reasons)
    assert any("PGM-06-not-activated is open" in reason for reason in result.blocking_reasons)


def test_an_absent_gate_manifest_still_says_only_what_it_can() -> None:
    """Control: with no bars compiled there is nothing to add, and it does not invent any."""

    result = readiness_now(coverage=None, gate_manifest=None)
    assert sorted(result.blocking_reasons) == [
        "no coverage snapshot has been captured",
        "no_product_gate_manifest: the product's own launch bars are not compiled",
    ]


def test_a_summary_must_say_who_wrote_it_before_it_can_be_shared() -> None:
    """A pattern search cannot certify text as safe; the authority behind it is what can.

    Without this, any string that happened to contain no email address would ride into a
    shared record on the strength of a regex finding nothing.
    """

    with pytest.raises(ContractError) as error:
        DifficultyObservation(
            cluster_key="export-step-unclear",
            product_slug=SLUG,
            difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
            surface="export screen",
            occurrence_count=4,
            distinct_customer_count=3,
            window_started_at=NOW - dt.timedelta(days=7),
            window_ended_at=NOW,
            operator_summary="some words nobody has claimed",
        )
    assert "marked absent must be empty" in str(error.value)


def test_a_closed_vocabulary_summary_must_be_one_of_the_producer_s_registered_phrases() -> None:
    phrases = ("the export step is unclear", "the export step loses work")
    admitted = DifficultyObservation(
        cluster_key="export-step-unclear",
        product_slug=SLUG,
        difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
        surface="export screen",
        occurrence_count=4,
        distinct_customer_count=3,
        window_started_at=NOW - dt.timedelta(days=7),
        window_ended_at=NOW,
        operator_summary="the export step is unclear",
        summary_authority=SummaryAuthority.CLOSED_VOCABULARY,
        registered_phrases=phrases,
    )
    assert admitted.operator_summary == "the export step is unclear"
    with pytest.raises(ContractError) as error:
        DifficultyObservation(
            cluster_key="export-step-unclear",
            product_slug=SLUG,
            difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
            surface="export screen",
            occurrence_count=4,
            distinct_customer_count=3,
            window_started_at=NOW - dt.timedelta(days=7),
            window_ended_at=NOW,
            operator_summary="something a person typed that is not in the set",
            summary_authority=SummaryAuthority.CLOSED_VOCABULARY,
            registered_phrases=phrases,
        )
    assert "registered phrases" in str(error.value)


def test_an_agent_authored_summary_long_enough_to_quote_somebody_is_refused() -> None:
    """Length is the second fence: a line that can hold a message can carry one."""

    with pytest.raises(ContractError) as error:
        assert_summary_admissible(
            summary="x" * 201, authority=SummaryAuthority.AGENT_AUTHORED
        )
    assert "at most 200" in str(error.value)


def test_the_reason_code_and_counts_stand_alone_with_no_summary_at_all() -> None:
    """Control: a record with no summary is complete, so nothing forces free text."""

    observed = DifficultyObservation(
        cluster_key="export-step-unclear",
        product_slug=SLUG,
        difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
        surface="export screen",
        occurrence_count=4,
        distinct_customer_count=3,
        window_started_at=NOW - dt.timedelta(days=7),
        window_ended_at=NOW,
    )
    assert observed.operator_summary == ""
    assert observed.as_dict()["summary_authority"] == "absent"


def test_a_producer_that_cannot_count_customers_says_so_rather_than_inventing_one() -> None:
    """A mailbox that keeps no sender identity cannot answer this, and should not have to.

    Retaining an identity purely to fill the field would be a worse outcome than the honest
    unknown, so the unknown is representable.
    """

    uncounted = DifficultyObservation(
        cluster_key="export-step-unclear",
        product_slug=SLUG,
        difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
        surface="export screen",
        occurrence_count=6,
        distinct_customer_count=None,
        window_started_at=NOW - dt.timedelta(days=28),
        window_ended_at=NOW,
    )
    assert uncounted.distinct_customer_count is None


def test_an_unknown_customer_count_never_satisfies_a_distinct_customer_threshold() -> None:
    """Unknown is not low and it is not high, so a threshold that needs it stays unmet."""

    uncounted = DifficultyObservation(
        cluster_key="export-step-unclear",
        product_slug=SLUG,
        difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
        surface="export screen",
        occurrence_count=50,
        distinct_customer_count=None,
        window_started_at=NOW - dt.timedelta(days=28),
        window_ended_at=NOW,
    )
    assert not RecurrenceThreshold().met_by(uncounted)
    assert "cannot count that" in RecurrenceThreshold().unmet_reason(uncounted)
    # An occurrences-only threshold is the one such a producer can actually meet.
    assert RecurrenceThreshold.by_occurrences(3).met_by(uncounted)


def test_an_occurrences_only_threshold_still_refuses_a_single_report() -> None:
    """Control: dropping the customer requirement does not drop the recurrence requirement."""

    once = DifficultyObservation(
        cluster_key="export-step-unclear",
        product_slug=SLUG,
        difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
        surface="export screen",
        occurrence_count=1,
        distinct_customer_count=None,
        window_started_at=NOW - dt.timedelta(days=1),
        window_ended_at=NOW,
    )
    assert not RecurrenceThreshold.by_occurrences(3).met_by(once)


def test_a_release_shipped_for_another_improvement_says_nothing_about_this_difficulty() -> None:
    unrelated = ShippedChange(
        request_id="improvement_for_something_else",
        release_ref="fictional-release-99",
        verification_ref="fictional-verification-99",
        shipped_at=NOW,
    )
    with pytest.raises(ContractError) as error:
        assess_resolution(
            cluster_key="export-step-unclear",
            request=raised(),
            shipped=unrelated,
            before_rate_per_week=2.0,
            after_rate_per_week=0.0,
            observation_window_complete=True,
        )
    assert "says nothing about this difficulty" in str(error.value)


def test_an_improvement_raised_for_another_difficulty_cannot_be_borrowed() -> None:
    with pytest.raises(ContractError) as error:
        assess_resolution(
            cluster_key="a-completely-different-cluster",
            request=raised(),
            shipped=shipped(),
            before_rate_per_week=2.0,
            after_rate_per_week=0.0,
            observation_window_complete=True,
        )
    assert "cannot borrow another difficulty's work" in str(error.value)


def test_a_shipped_change_with_no_improvement_behind_it_is_refused() -> None:
    with pytest.raises(ContractError):
        assess_resolution(
            cluster_key="export-step-unclear",
            request=None,
            shipped=shipped(),
            before_rate_per_week=2.0,
            after_rate_per_week=0.0,
            observation_window_complete=True,
        )


def test_a_halving_is_reported_as_a_real_result_and_still_tells_nobody_it_is_fixed() -> None:
    """Fewer people hitting a problem is a measurement about the population.

    It is not the claim "yours is fixed", and reading it as one would tell customers who are
    still hitting the difficulty that it went away.
    """

    assessment = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=2.0,
        after_rate_per_week=1.0,
        observation_window_complete=True,
    )
    assert assessment.state is ResolutionState.IMPROVED_NOT_RESOLVED
    assert "it still happens" in assessment.reason
    assert not assessment.customer_follow_up_permitted
    plan = plan_follow_up(assessment=assessment, observation=observation())
    assert not plan.permitted
    assert plan.notify_support_refs == ()


def test_resolution_means_a_measured_zero_across_a_complete_window() -> None:
    assessment = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=2.0,
        after_rate_per_week=0.0,
        observation_window_complete=True,
    )
    assert assessment.state is ResolutionState.VERIFIED_RESOLVED
    assert "reached zero across a complete window" in assessment.reason


def test_an_absent_measurement_is_never_read_as_the_zero_that_would_resolve_it() -> None:
    """The distinction the whole path rests on: no data is unknown, measured zero is zero."""

    for after in (None,):
        assessment = assess_resolution(
            cluster_key="export-step-unclear",
            request=raised(),
            shipped=shipped(),
            before_rate_per_week=2.0,
            after_rate_per_week=after,
            observation_window_complete=True,
        )
        assert assessment.state is ResolutionState.UNKNOWN
    # And an open window is not a complete one, whatever the numbers say.
    still_open = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=2.0,
        after_rate_per_week=0.0,
        observation_window_complete=False,
    )
    assert still_open.state is ResolutionState.SHIPPED_UNVERIFIED


def test_a_follow_up_cannot_reach_the_people_who_reported_something_else() -> None:
    """The observation decides who hears from us, so a mismatched pair would write to them.

    Before this was bound, an assessment of one difficulty paired with another's observation
    returned permitted, carrying the wrong cluster's support references.
    """

    resolved = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=2.0,
        after_rate_per_week=0.0,
        observation_window_complete=True,
    )
    other = DifficultyObservation(
        cluster_key="a-different-difficulty",
        product_slug=SLUG,
        difficulty_kind=DifficultyKind.BILLING_OR_ORDER,
        surface="checkout",
        occurrence_count=3,
        distinct_customer_count=3,
        window_started_at=NOW - dt.timedelta(days=7),
        window_ended_at=NOW,
        support_refs=("support-ref-for-a-different-problem",),
    )
    with pytest.raises(ContractError) as error:
        plan_follow_up(assessment=resolved, observation=other)
    assert "reported something else" in str(error.value)
    # The matching pair is still permitted, so the binding is the mismatch and not a blanket no.
    assert plan_follow_up(assessment=resolved, observation=observation()).permitted


def test_a_zero_from_a_reading_that_did_not_cover_the_window_is_not_a_measured_zero() -> None:
    """Two identical zeros mean different things, and only the coverage separates them.

    A producer reading an index that does not hold every record found nothing where it
    looked. Reading that as "the trouble stopped" would tell customers a problem went away on
    the strength of records nobody consulted.
    """

    for coverage in (ObservationCoverage.INDEXED_ONLY, ObservationCoverage.PARTIAL):
        assessment = assess_resolution(
            cluster_key="export-step-unclear",
            request=raised(),
            shipped=shipped(),
            before_rate_per_week=2.0,
            after_rate_per_week=0.0,
            observation_window_complete=True,
            after_coverage=coverage,
        )
        assert assessment.state is ResolutionState.UNKNOWN, coverage
        assert "not the same as the trouble having stopped" in assessment.reason
        assert not assessment.customer_follow_up_permitted


def test_the_same_zero_resolves_once_the_reading_covered_the_whole_window() -> None:
    """Control: the refusal above is the coverage, not a refusal to ever resolve."""

    assessment = assess_resolution(
        cluster_key="export-step-unclear",
        request=raised(),
        shipped=shipped(),
        before_rate_per_week=2.0,
        after_rate_per_week=0.0,
        observation_window_complete=True,
        after_coverage=ObservationCoverage.COMPLETE,
    )
    assert assessment.state is ResolutionState.VERIFIED_RESOLVED


def test_an_observation_carries_what_its_reading_covered_and_the_digest_of_it() -> None:
    limited = DifficultyObservation(
        cluster_key="export-step-unclear",
        product_slug=SLUG,
        difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
        surface="export screen",
        occurrence_count=4,
        distinct_customer_count=None,
        window_started_at=NOW - dt.timedelta(days=28),
        window_ended_at=NOW,
        coverage=ObservationCoverage.INDEXED_ONLY,
        source_digest="b" * 64,
    )
    assert limited.as_dict()["coverage"] == "indexed_only"
    assert limited.as_dict()["source_digest"] == "b" * 64
    # A malformed digest is refused rather than stored as a label.
    with pytest.raises(ContractError):
        DifficultyObservation(
            cluster_key="export-step-unclear",
            product_slug=SLUG,
            difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
            surface="export screen",
            occurrence_count=4,
            distinct_customer_count=None,
            window_started_at=NOW - dt.timedelta(days=28),
            window_ended_at=NOW,
            source_digest="not-a-digest",
        )


def test_every_input_that_arrived_is_evaluated_even_when_another_is_missing() -> None:
    """Stopping at the first absent input hides blockers sitting in the inputs that did come.

    A coverage snapshot showing 80% is a blocker whether or not a validation snapshot exists,
    and an operator asking why a launch is blocked needs both sentences, not the first one.
    """

    result = readiness_now(
        coverage=coverage(total=10, covered=8, uncovered=("REQ-A", "REQ-B")),
        validation=None,
    )
    assert result.readiness is Readiness.BLOCKED
    joined = " ".join(result.blocking_reasons)
    assert "no validation snapshot has been captured" in joined
    assert "coverage is 80%" in joined
    assert "8 of 10 requirements" in joined
    assert "2 coverage error gap(s)" in joined


def test_the_same_holds_when_the_coverage_snapshot_is_the_missing_one() -> None:
    """Control: the pairing works in both directions, not just the one that was tested."""

    result = readiness_now(
        coverage=None,
        validation=validation(warnings=17, prior_warnings=5),
    )
    joined = " ".join(result.blocking_reasons)
    assert "no coverage snapshot has been captured" in joined
    assert "warning gaps rose by 12" in joined
