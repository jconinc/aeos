"""Moves, parks and admission: what may ship, what waits, and what never gets permission."""

from __future__ import annotations

import datetime as dt

import pytest

from aeos_kernel.approvals import (
    Approval,
    ApprovalStatus,
    ParkCause,
    drain_partially,
    expire_overdue,
    park_move,
    project_approval_load,
    queue_depth,
    resume_from_approval,
    seed_batch,
)
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.modules import PriorityClass
from aeos_kernel.moves import (
    Disposition,
    ExecStatus,
    Move,
    MoveDecision,
    MoveRequest,
    RequestedBy,
    SettlementRefusal,
    assert_unmutated,
    commit_boundary_refusal,
    duplicate_of,
    graduation_state,
    move_idempotency_key,
    record_outcome,
    settle_external,
)
from aeos_kernel.scheduling import (
    Channel,
    ChannelKind,
    ChannelState,
    ProductFault,
    ValidationScope,
    admit_move,
    drain_order,
    preemptions,
    resolve_adapter,
    run_scoped_validation,
)
from tests.factories_control_plane import NOW, TODAY, manifest, outreach_module, pipeline_module

SNAPSHOT = "snapshot-alpha"
LATER_SNAPSHOT = "snapshot-beta"


def request(
    *,
    slug: str = "fictional-app",
    move_type: str = "post_update",
    priority: PriorityClass = PriorityClass.NORMAL,
    at: dt.datetime = NOW,
    request_id: str = "request-1",
) -> MoveRequest:
    return MoveRequest(
        request_id=request_id,
        product_slug=slug,
        move_type=move_type,
        as_of=TODAY,
        priority_class=priority,
        requested_by=RequestedBy.SCHEDULE,
        requested_at=at,
        args={"subject": "fictional-record-1"},
    )


def move(
    *,
    decision: MoveDecision = MoveDecision.SHIP,
    evidence: tuple[str, ...] = ("evidence-1",),
    snapshots: tuple[str, ...] = (SNAPSHOT,),
    move_type: str = "post_update",
    exec_status: ExecStatus = ExecStatus.QUEUED,
    reason: str = "",
    move_id: str = "move-1",
) -> Move:
    return Move(
        move_id=move_id,
        move_request_id="request-1",
        product_slug="fictional-app",
        move_type=move_type,
        decision=decision,
        exec_status=exec_status,
        as_of=TODAY,
        rulepack_version="fictional.rulepack@3",
        manifest_version="1.0.0",
        idempotency_key=move_idempotency_key(
            product_slug="fictional-app",
            move_type=move_type,
            as_of=TODAY,
            args_digest=request().args_digest,
            data_snapshot_refs=snapshots,
            rulepack_version="fictional.rulepack@3",
        ),
        data_snapshot_refs=snapshots,
        evidence_refs=evidence,
        decline_reason=reason,
    )


def outreach_family():  # type: ignore[no-untyped-def]
    family = outreach_module().family("post_update")
    assert family is not None
    return family


def coverage_family():  # type: ignore[no-untyped-def]
    family = pipeline_module().family("capture_coverage")
    assert family is not None
    return family


def test_a_shipped_move_without_evidence_cannot_even_be_constructed() -> None:
    with pytest.raises(ContractError):
        move(evidence=())


def test_a_declined_move_must_say_why_in_words_an_operator_can_read() -> None:
    with pytest.raises(ContractError):
        move(decision=MoveDecision.DECLINE, evidence=(), reason="")


def test_evidence_that_does_not_resolve_into_the_product_is_refused_at_the_boundary() -> None:
    refusal = commit_boundary_refusal(
        move=move(decision=MoveDecision.SHIP, move_type="capture_coverage"),
        family=coverage_family(),
        resolved_evidence_refs=frozenset(),
        detected_at=NOW,
    )
    assert refusal is not None
    assert refusal.reason.startswith("incomplete_evidence_path")
    assert refusal.gaps[0].gap_type == "incomplete_evidence_path"


def test_the_same_move_passes_once_its_evidence_resolves() -> None:
    """Control: the refusal above is about the evidence path, not the move itself."""

    assert (
        commit_boundary_refusal(
            move=move(decision=MoveDecision.SHIP, move_type="capture_coverage"),
            family=coverage_family(),
            resolved_evidence_refs=frozenset({"evidence-1"}),
            detected_at=NOW,
        )
        is None
    )


def test_a_parking_family_reaching_the_boundary_in_ship_state_is_a_hard_refusal() -> None:
    refusal = commit_boundary_refusal(
        move=move(decision=MoveDecision.SHIP),
        family=outreach_family(),
        resolved_evidence_refs=frozenset({"evidence-1"}),
        detected_at=NOW,
    )
    assert refusal is not None
    assert refusal.gaps[0].gap_type == "unparked_high_risk_move"


def test_a_move_committed_against_the_wrong_family_is_refused() -> None:
    refusal = commit_boundary_refusal(
        move=move(move_type="capture_coverage"),
        family=outreach_family(),
        resolved_evidence_refs=frozenset({"evidence-1"}),
        detected_at=NOW,
    )
    assert refusal is not None
    assert "was committed against family" in refusal.reason


def test_re_issuing_the_same_move_dedups_but_fresh_data_makes_a_new_one() -> None:
    original = move(move_type="capture_coverage")
    identical = move(move_type="capture_coverage", move_id="move-2")
    repeat = duplicate_of(idempotency_key=identical.idempotency_key, committed=(original,))
    assert repeat is original
    under_new_data = move(
        move_type="capture_coverage", snapshots=(LATER_SNAPSHOT,), move_id="move-3"
    )
    fresh = duplicate_of(idempotency_key=under_new_data.idempotency_key, committed=(original,))
    assert fresh is None


def test_a_move_that_changed_after_its_ledger_entry_is_caught() -> None:
    original = move(move_type="capture_coverage")
    entry = record_outcome(
        move=original,
        recorded_at=NOW,
        artifact_uri="fictional://artifact/1",
        artifact_sha256="a" * 64,
    )
    assert entry.disposition is Disposition.SHIPPED
    assert_unmutated(original, entry)
    edited = move(move_type="capture_coverage", evidence=("evidence-1", "evidence-2"))
    with pytest.raises(ContractError) as error:
        assert_unmutated(edited, entry)
    assert "changed after its ledger entry" in str(error.value)


def test_only_a_shipped_move_carries_a_published_artifact() -> None:
    held = move(decision=MoveDecision.HOLD, evidence=(), move_type="capture_coverage")
    entry = record_outcome(move=held, recorded_at=NOW)
    assert entry.disposition is Disposition.HELD
    assert entry.artifact_uri == ""
    with pytest.raises(ContractError):
        record_outcome(
            move=held, recorded_at=NOW, artifact_uri="fictional://x", artifact_sha256="b" * 64
        )


def test_a_parked_move_is_not_closed_into_the_ledger() -> None:
    parked = move(decision=MoveDecision.PARKED, evidence=(), move_type="capture_coverage")
    with pytest.raises(ContractError):
        record_outcome(move=parked, recorded_at=NOW)


def test_waiting_on_an_external_clock_is_not_the_same_as_being_undecided() -> None:
    dispatched = move(
        move_type="capture_coverage", exec_status=ExecStatus.AWAITING_EXTERNAL
    )
    assert dispatched.decision is MoveDecision.SHIP
    settled = settle_external(
        original=dispatched,
        observation="the external system reported the capture finished",
        observed_snapshot_ref=LATER_SNAPSHOT,
        settled_at=NOW + dt.timedelta(days=14),
    )
    assert isinstance(settled, Move)
    assert settled.exec_status is ExecStatus.SETTLED
    assert settled.decision is dispatched.decision
    assert settled.move_id != dispatched.move_id
    # The original record is untouched by the settlement.
    assert dispatched.exec_status is ExecStatus.AWAITING_EXTERNAL


def test_settling_a_parked_move_by_observation_is_refused() -> None:
    parked = move(decision=MoveDecision.PARKED, evidence=(), move_type="capture_coverage")
    result = settle_external(
        original=parked,
        observation="something happened",
        observed_snapshot_ref=LATER_SNAPSHOT,
        settled_at=NOW,
    )
    assert isinstance(result, SettlementRefusal)


def test_a_reserved_family_never_graduates_however_many_approvals_it_collects() -> None:
    family = pipeline_module().family("launch_product")
    assert family is not None
    state = graduation_state(
        family=family,
        product_slug="fictional-app",
        approved_count=500,
        reversal_count=0,
        threshold=25,
    )
    assert not state.eligible
    assert "never graduates" in state.reason


def test_one_reversal_revokes_graduation_for_an_ordinary_parking_family() -> None:
    family = outreach_family()
    earned = graduation_state(
        family=family,
        product_slug="fictional-app",
        approved_count=25,
        reversal_count=0,
        threshold=25,
    )
    assert earned.eligible
    revoked = graduation_state(
        family=family,
        product_slug="fictional-app",
        approved_count=40,
        reversal_count=1,
        threshold=25,
    )
    assert not revoked.eligible
    assert "revoked by the first reversal" in revoked.reason


def parked_pair():  # type: ignore[no-untyped-def]
    parked = move(decision=MoveDecision.PARKED, evidence=(), move_type="capture_coverage")
    return park_move(
        move=parked,
        cause=ParkCause.BELOW_CONFIDENCE_GATE,
        reason_operator="Judgment confidence 0.62 is below the 0.80 gate on claim-evidence match.",
        choice_set=("publish as drafted", "publish without the third claim"),
        payload_preview={"body": "Fictional record summary as of 2026-09-13."},
        parked_at=NOW,
        park_ttl_hours=72,
    )


def test_approving_runs_exactly_what_the_person_was_shown() -> None:
    record, approval = parked_pair()
    assert "decline" in record.offered_choices
    decided = Approval(
        approval_id=approval.approval_id,
        move_id=approval.move_id,
        park_id=approval.park_id,
        status=ApprovalStatus.APPROVED,
        reason_operator=approval.reason_operator,
        payload_preview=dict(approval.payload_preview),
        payload_preview_digest=approval.payload_preview_digest,
        choice_set=approval.choice_set,
        chosen="publish as drafted",
        decided_by="fictional.owner",
        decided_at=NOW + dt.timedelta(hours=2),
    )
    outcome = resume_from_approval(approval=decided, now=NOW + dt.timedelta(hours=2))
    assert outcome.decision is MoveDecision.SHIP
    assert outcome.execute_payload["body"].startswith("Fictional record summary")


def test_an_approval_whose_preview_digest_no_longer_matches_is_refused() -> None:
    _record, approval = parked_pair()
    with pytest.raises(ContractError):
        Approval(
            approval_id=approval.approval_id,
            move_id=approval.move_id,
            park_id=approval.park_id,
            status=ApprovalStatus.APPROVED,
            reason_operator=approval.reason_operator,
            payload_preview={"body": "Different words than the operator saw."},
            payload_preview_digest=approval.payload_preview_digest,
            choice_set=approval.choice_set,
            chosen="publish as drafted",
            decided_by="fictional.owner",
            decided_at=NOW,
        )


def test_choosing_an_option_that_was_never_offered_is_refused() -> None:
    _record, approval = parked_pair()
    with pytest.raises(ContractError):
        Approval(
            approval_id=approval.approval_id,
            move_id=approval.move_id,
            park_id=approval.park_id,
            status=ApprovalStatus.APPROVED,
            reason_operator=approval.reason_operator,
            payload_preview=dict(approval.payload_preview),
            payload_preview_digest=approval.payload_preview_digest,
            choice_set=approval.choice_set,
            chosen="rewrite it entirely",
            decided_by="fictional.owner",
            decided_at=NOW,
        )


def test_an_unanswered_approval_holds_rather_than_declining_or_shipping() -> None:
    record, approval = parked_pair()
    expired = expire_overdue((approval,), (record,), now=NOW + dt.timedelta(hours=73))
    assert len(expired) == 1
    outcome = resume_from_approval(approval=expired[0], now=NOW + dt.timedelta(hours=73))
    assert outcome.decision is MoveDecision.HOLD
    assert "not declined" in outcome.reason


def test_an_approval_inside_its_window_does_not_expire() -> None:
    """Control: the expiry above is the clock, not a rule that fires regardless."""

    record, approval = parked_pair()
    assert expire_overdue((approval,), (record,), now=NOW + dt.timedelta(hours=71)) == ()


def test_a_park_reason_written_as_a_stack_trace_is_refused() -> None:
    parked = move(decision=MoveDecision.PARKED, evidence=(), move_type="capture_coverage")
    with pytest.raises(ContractError):
        park_move(
            move=parked,
            cause=ParkCause.AMBIGUOUS,
            reason_operator="Traceback: " + "x" * 500,
            choice_set=("a",),
            payload_preview={},
            parked_at=NOW,
            park_ttl_hours=72,
        )


def test_one_parked_item_does_not_stop_the_rest_of_the_run() -> None:
    batch = (
        move(move_id="m1", move_type="capture_coverage"),
        move(move_id="m2", decision=MoveDecision.PARKED, evidence=(), move_type="capture_coverage"),
        move(move_id="m3", decision=MoveDecision.HOLD, evidence=(), move_type="capture_coverage"),
    )
    result = drain_partially(batch)
    assert result.drained_count == 2
    assert [item.move_id for item in result.parked] == ["m2"]


def test_operator_load_is_sized_by_arithmetic_before_a_module_is_enabled() -> None:
    families = outreach_module().move_families
    projection = project_approval_load(
        product_slug="fictional-app",
        module_key="outreach",
        families=families,
        scheduled_moves_per_week={"post_update": 40.0},
        observed_park_rate={},
        headroom_parks_per_week=10.0,
    )
    # A family that always parks contributes its whole volume, not an assumed fraction.
    assert projection.projected_parks_per_week == 40.0
    assert not projection.within_headroom
    assert "exceeds the declared headroom" in projection.reason


def test_a_family_with_scheduled_work_and_no_measured_rate_sizes_nothing() -> None:
    """An unknown rate read as zero lets heavy work certify a headroom nobody observed.

    Seventy captures a week whose park rate nobody has measured would have projected zero
    parks and reported that it fits — the opposite of what not knowing means.
    """

    projection = project_approval_load(
        product_slug="fictional-app",
        module_key="pipeline",
        families=pipeline_module().move_families,
        scheduled_moves_per_week={"capture_coverage": 70.0, "launch_product": 1.0},
        observed_park_rate={},
        headroom_parks_per_week=10.0,
    )
    assert projection.unmeasured_move_types == ("capture_coverage",)
    assert not projection.is_complete
    assert not projection.within_headroom
    assert "has scheduled work and no measured park rate" in projection.reason


def test_a_family_nobody_scheduled_needs_no_rate_to_be_sized() -> None:
    """Nothing scheduled adds nothing, and that much is known without measuring it."""

    projection = project_approval_load(
        product_slug="fictional-app",
        module_key="pipeline",
        families=pipeline_module().move_families,
        scheduled_moves_per_week={"launch_product": 1.0},
        observed_park_rate={},
        headroom_parks_per_week=10.0,
    )
    assert projection.is_complete
    assert projection.projected_parks_per_week == 1.0
    assert projection.within_headroom


def test_a_measured_rate_sizes_the_work_it_was_measured_for() -> None:
    """Control: supplying the rate is what turns the floor into an answer."""

    projection = project_approval_load(
        product_slug="fictional-app",
        module_key="pipeline",
        families=pipeline_module().move_families,
        scheduled_moves_per_week={"capture_coverage": 70.0, "launch_product": 1.0},
        observed_park_rate={"capture_coverage": 0.1},
        headroom_parks_per_week=10.0,
    )
    assert projection.is_complete
    assert projection.projected_parks_per_week == 8.0
    assert projection.within_headroom


def test_seed_parks_are_presented_as_one_sitting_but_remain_individually_decidable() -> None:
    parks, approvals = [], []
    for index in range(3):
        parked = move(
            decision=MoveDecision.PARKED,
            evidence=(),
            move_type="capture_coverage",
            move_id=f"seed-{index}",
        )
        record, approval = park_move(
            move=parked,
            cause=ParkCause.SEED_MOVE,
            reason_operator=f"First run of capture_coverage on this product ({index + 1} of 3).",
            choice_set=("approve this capture",),
            payload_preview={"index": index},
            parked_at=NOW,
            park_ttl_hours=72,
        )
        parks.append(record)
        approvals.append(approval)
    batch = seed_batch(
        product_slug="fictional-app", approvals=tuple(approvals), parks=tuple(parks)
    )
    assert batch.item_count == 3
    assert queue_depth(tuple(approvals)) == 3
    # Each item still carries its own choice set; the batch is a presentation, not one yes.
    assert all(item.choice_set == ("approve this capture", "decline") for item in batch.approvals)


def test_one_product_s_fault_does_not_halt_another_product() -> None:
    fault = ProductFault(
        product_slug="fictional-desk",
        fault_type="budget_breached",
        reason="the daily model budget for fictional-desk is spent",
        detected_at=NOW,
    )
    assert (
        admit_move(
            request=request(slug="fictional-app"),
            family=outreach_family(),
            faults=(fault,),
            channels=(),
            now=NOW,
        )
        is None
    )
    refusal = admit_move(
        request=request(slug="fictional-desk"),
        family=outreach_family(),
        faults=(fault,),
        channels=(),
        now=NOW,
    )
    assert refusal is not None
    assert refusal.scope == "product:fictional-desk"


def test_a_fault_scoped_to_one_module_leaves_the_product_s_other_modules_running() -> None:
    fault = ProductFault(
        product_slug="fictional-app",
        fault_type="module_degraded",
        reason="the outreach module's provider is failing",
        detected_at=NOW,
        halts_module_keys=("outreach",),
    )
    assert (
        admit_move(
            request=request(move_type="capture_coverage"),
            family=coverage_family(),
            faults=(fault,),
            channels=(),
            now=NOW,
        )
        is None
    )
    assert (
        admit_move(
            request=request(), family=outreach_family(), faults=(fault,), channels=(), now=NOW
        )
        is not None
    )


def test_a_shared_sending_domain_in_cooldown_stops_outbound_for_every_product_on_it() -> None:
    channel = Channel(
        key="fictional-channel",
        kind=ChannelKind.EMAIL_DOMAIN,
        state=ChannelState.COOLDOWN,
        product_slugs=("fictional-app", "fictional-desk"),
        cooldown_until=NOW + dt.timedelta(hours=6),
        cooldown_reason="complaint rate above the threshold on this sending domain",
    )
    for slug in ("fictional-app", "fictional-desk"):
        refusal = admit_move(
            request=request(slug=slug),
            family=outreach_family(),
            faults=(),
            channels=(channel,),
            channel_key="fictional-channel",
            now=NOW,
        )
        assert refusal is not None
        assert refusal.scope == "channel:fictional-channel"
        assert "their other work continues" in refusal.reason
    # Everything not sending on that channel keeps draining.
    assert (
        admit_move(
            request=request(move_type="capture_coverage"),
            family=coverage_family(),
            faults=(),
            channels=(channel,),
            now=NOW,
        )
        is None
    )


def test_the_same_channel_admits_once_its_cooldown_has_passed() -> None:
    """Control: the refusal above is the cooldown window, not the channel's existence."""

    channel = Channel(
        key="fictional-channel",
        kind=ChannelKind.EMAIL_DOMAIN,
        state=ChannelState.COOLDOWN,
        product_slugs=("fictional-app",),
        cooldown_until=NOW + dt.timedelta(hours=6),
        cooldown_reason="complaint rate above the threshold on this sending domain",
    )
    assert (
        admit_move(
            request=request(),
            family=outreach_family(),
            faults=(),
            channels=(channel,),
            channel_key="fictional-channel",
            now=NOW + dt.timedelta(hours=7),
        )
        is None
    )


def test_a_product_that_does_not_send_on_a_channel_cannot_borrow_it() -> None:
    channel = Channel(
        key="fictional-channel",
        kind=ChannelKind.EMAIL_DOMAIN,
        state=ChannelState.ACTIVE,
        product_slugs=("fictional-desk",),
    )
    refusal = admit_move(
        request=request(slug="fictional-app"),
        family=outreach_family(),
        faults=(),
        channels=(channel,),
        channel_key="fictional-channel",
        now=NOW,
    )
    assert refusal is not None
    assert "does not send on channel" in refusal.reason


def test_urgent_work_displaces_background_work_on_the_same_product_only() -> None:
    urgent = request(
        slug="fictional-app", priority=PriorityClass.PRIORITY, request_id="urgent-1"
    )
    same_product = request(
        slug="fictional-app", priority=PriorityClass.BACKGROUND, request_id="bg-1"
    )
    other_product = request(
        slug="fictional-desk", priority=PriorityClass.BACKGROUND, request_id="bg-2"
    )
    result = preemptions((urgent,), in_flight=(same_product, other_product))
    assert [item.preempted_request_id for item in result] == ["bg-1"]


def test_the_queue_drains_urgent_first_then_oldest_first() -> None:
    ordered = drain_order(
        (
            request(priority=PriorityClass.BACKGROUND, request_id="c", at=NOW),
            request(
                priority=PriorityClass.PRIORITY,
                request_id="b",
                at=NOW + dt.timedelta(hours=1),
            ),
            request(priority=PriorityClass.NORMAL, request_id="a", at=NOW),
        ),
        now=NOW,
    )
    assert [item.request_id for item in ordered] == ["b", "a", "c"]


def test_a_per_move_validation_must_name_its_subjects() -> None:
    with pytest.raises(ContractError) as error:
        ValidationScope(product_slug="fictional-app", subject_ids=())
    assert "unscoped rescan is refused" in str(error.value)


def test_a_validator_that_escaped_its_scope_is_caught_however_much_data_exists() -> None:
    scope = ValidationScope(product_slug="fictional-app", subject_ids=("subject-1",))

    def honest(_scope: ValidationScope) -> tuple[tuple[str, str], ...]:
        return (("fictional-app", "subject-1"),)

    def widened(_scope: ValidationScope) -> tuple[tuple[str, str], ...]:
        # Simulates a validator that grew into an archive-wide scan as the ledger filled.
        return (("fictional-app", "subject-1"), ("fictional-desk", "subject-9"))

    assert run_scoped_validation(
        scope=scope, validator=honest, belongs_to=lambda item: item
    ) == (("fictional-app", "subject-1"),)
    with pytest.raises(ContractError) as error:
        run_scoped_validation(scope=scope, validator=widened, belongs_to=lambda item: item)
    assert "outside its scope" in str(error.value)


def test_a_channel_adapter_resolves_from_the_product_s_own_manifest_at_move_time() -> None:
    product_manifest = manifest("fictional-app")
    assert (
        resolve_adapter(
            credential_scopes=dict(product_manifest.credential_scopes),
            move_type="post_update",
            channel_key="fictional-channel",
        )
        == "fictional-channel"
    )
    # A move type the manifest never permitted on that channel resolves to nothing.
    assert (
        resolve_adapter(
            credential_scopes=dict(product_manifest.credential_scopes),
            move_type="capture_coverage",
            channel_key="fictional-channel",
        )
        is None
    )


def test_the_idempotency_key_is_stable_across_equal_inputs_in_any_order() -> None:
    first = move_idempotency_key(
        product_slug="fictional-app",
        move_type="capture_coverage",
        as_of=TODAY,
        args_digest=stable_fingerprint({"a": 1}),
        data_snapshot_refs=("s2", "s1"),
        rulepack_version="r@1",
    )
    second = move_idempotency_key(
        product_slug="fictional-app",
        move_type="capture_coverage",
        as_of=TODAY,
        args_digest=stable_fingerprint({"a": 1}),
        data_snapshot_refs=("s1", "s2"),
        rulepack_version="r@1",
    )
    assert first == second
