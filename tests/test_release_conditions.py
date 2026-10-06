"""PB-199 C21-6.1: stable blockers distinguish changed problems from changed wording."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from aeos_kernel import BLOCKING_CONDITION_SCHEMA, BlockingCondition
from aeos_kernel.errors import ContractError
from aeos_kernel.pipeline import (
    CoverageSnapshot,
    GateManifestEntry,
    GateStatus,
    PredicateKind,
    ProductGateManifest,
    Readiness,
    ReleaseReadiness,
    ValidationSnapshot,
    evaluate_release_readiness,
)
from aeos_kernel.registry import LiabilityClass
from tests.factories_control_plane import NOW, manifest

SLUG = "fictional-app"


def coverage(**changes: Any) -> CoverageSnapshot:
    return replace(
        CoverageSnapshot(
            snapshot_id="coverage-1",
            binding_id="binding-1",
            product_slug=SLUG,
            snapshot_ref="fictional:coverage",
            captured_at=NOW,
            total_requirements=10,
            covered_requirements=10,
            uncovered_requirement_ids=(),
        ),
        **changes,
    )


def validation(**changes: Any) -> ValidationSnapshot:
    return replace(
        ValidationSnapshot(
            snapshot_id="validation-1",
            binding_id="binding-1",
            product_slug=SLUG,
            snapshot_ref="fictional:validation",
            captured_at=NOW,
            error_gap_count=0,
            warning_gap_count=0,
            prior_warning_gap_count=0,
            gate_status={"build": True},
        ),
        **changes,
    )


def read(**changes: Any) -> ReleaseReadiness:
    values: dict[str, Any] = dict(
        manifest=manifest(SLUG),
        coverage=coverage(),
        validation=validation(),
        gate_manifest=ProductGateManifest(
            manifest_id="gates-1",
            product_slug=SLUG,
            gates=(),
            source_ref="fictional:requirements",
            captured_at=NOW,
            snapshot_ref="fictional:gates",
        ),
        family_coverage_thresholds={"min_overall": 0.9},
        now=NOW,
    )
    values.update(changes)
    return evaluate_release_readiness(**values)


def keys(reading: ReleaseReadiness) -> tuple[str, ...]:
    return tuple(condition.key for condition in reading.blocking_conditions)


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("coverage_snapshot_missing", ()),
        ("coverage_below_minimum", ()),
        ("coverage_kind_unmeasured", ("Screen",)),
        ("coverage_kind_short", ("Screen",)),
        ("coverage_error_gaps", ()),
        ("validation_snapshot_missing", ()),
        ("validation_stale", ()),
        ("warning_gaps_rose", ()),
        ("build_gate_failed", ("closure_valid",)),
        ("validation_rule_errors", ("references_missing_role",)),
        ("validation_error_gaps_unattributed", ()),
        ("gate_manifest_missing", ()),
        ("liability_gate_missing", ("C", "insurance")),
        ("launch_bar_open", ("pilot", "")),
    ],
)
def test_closed_condition_identity_ignores_display_text(kind: str, params: tuple[str, ...]) -> None:
    before = BlockingCondition(kind, params, "Before: 2 remaining")
    after = BlockingCondition(kind, params, "After: 1 remaining")
    assert before.key == after.key
    assert before.as_dict() == {"kind": kind, "params": list(params), "reason": before.reason}
    assert BLOCKING_CONDITION_SCHEMA == "aeos.release-conditions@1"


@pytest.mark.parametrize(
    ("kind", "params", "reason"),
    [
        ("unknown", (), "Unknown"),
        (True, (), "Invalid kind"),
        ("coverage_below_minimum", ("70%",), "Counts are not parameters"),
        ("validation_rule_errors", [], "Mutable params"),
        ("validation_rule_errors", ("",), "Empty rule"),
        ("validation_rule_errors", (" rule",), "Padded rule"),
        ("validation_rule_errors", (3,), "Count instead of rule"),
        ("validation_rule_errors", ("rule\x00",), "Control character in rule"),
        ("validation_rule_errors", ("rule\nnext",), "Control character in rule"),
        ("coverage_snapshot_missing", (), "reason\x1bcontrol"),
        ("launch_bar_open", ("", ""), "Empty gate"),
        ("launch_bar_open", ("pilot", " "), "Padded regime"),
        ("coverage_snapshot_missing", (), ""),
        ("coverage_snapshot_missing", (), " padded "),
    ],
)
def test_malformed_condition_is_not_a_usable_identity(kind: Any, params: Any, reason: Any) -> None:
    with pytest.raises(ContractError):
        BlockingCondition(kind, params, reason)


def test_canonical_key_keeps_the_complete_json_tuple() -> None:
    condition = BlockingCondition("launch_bar_open", ('bar:é"', "region-a"), "Open")
    assert condition.key == '["launch_bar_open","bar:é\\"","region-a"]'
    assert condition.key != BlockingCondition("launch_bar_open", ('bar:é"', "region-b"), "Open").key


def test_missing_inputs_are_each_named_and_green_has_no_conditions() -> None:
    result = read(coverage=None, validation=None, gate_manifest=None)
    assert keys(result) == (
        '["coverage_snapshot_missing"]',
        '["gate_manifest_missing"]',
        '["validation_snapshot_missing"]',
    )
    assert {condition.reason for condition in result.blocking_conditions} == set(
        result.blocking_reasons
    )
    assert read().readiness is Readiness.GREEN
    assert read().blocking_conditions == ()


def test_coverage_counts_and_snapshot_ids_change_reasons_without_changing_identity() -> None:
    first = read(coverage=coverage(covered_requirements=7))
    second = read(coverage=coverage(covered_requirements=8, snapshot_id="coverage-2"))
    assert first.blocking_reasons != second.blocking_reasons
    assert keys(first) == keys(second) == ('["coverage_below_minimum"]',)


def test_kind_shortfalls_and_uncovered_requirements_have_source_owned_identities() -> None:
    result = read(
        coverage=coverage(
            coverage_by_kind={"Screen": {"satisfied": 1}},
            covered_requirements=9,
            uncovered_requirement_ids=("REQ-1",),
        ),
        family_coverage_thresholds={"Screen": 2, "API": 1},
    )
    assert keys(result) == (
        '["coverage_error_gaps"]',
        '["coverage_kind_short","Screen"]',
        '["coverage_kind_unmeasured","API"]',
    )


def test_staleness_warning_delta_and_failed_components_have_stable_conditions() -> None:
    result = read(
        validation=validation(
            captured_at=NOW - timedelta(days=3),
            warning_gap_count=2,
            gate_status={"z": False, "a": False},
        )
    )
    assert result.readiness is Readiness.PARKED
    assert keys(result) == (
        '["build_gate_failed","a"]',
        '["build_gate_failed","z"]',
        '["validation_stale"]',
        '["warning_gaps_rose"]',
    )
    assert result.blocking_conditions[0].reason == result.blocking_conditions[1].reason
    assert len(result.blocking_reasons) == 3


def test_same_total_different_error_rule_changes_condition_identity() -> None:
    before = read(validation=validation(error_gap_count=1, gaps_by_rule={"rule-a": {"error": 1}}))
    after = read(validation=validation(error_gap_count=1, gaps_by_rule={"rule-b": {"error": 1}}))
    assert keys(before) == ('["validation_rule_errors","rule-a"]',)
    assert keys(after) == ('["validation_rule_errors","rule-b"]',)
    assert keys(before) != keys(after)


def test_explicit_rule_and_aggregate_block_share_one_condition_and_reason() -> None:
    result = read(
        manifest=manifest(
            SLUG,
            release_policy={"max_open_error_gaps": 0, "block_on_error_rules": ["rule-a", "rule-a"]},
        ),
        validation=validation(
            error_gap_count=3,
            gaps_by_rule={
                "rule-a": {"error": 1},
                "rule-b": {"error": 2},
                "clear": {"error": 0},
            },
        ),
    )
    assert keys(result) == (
        '["validation_rule_errors","rule-a"]',
        '["validation_rule_errors","rule-b"]',
    )
    assert result.blocking_reasons == ("rule-a has 1 error gap(s)", "rule-b has 2 error gap(s)")
    assert len(result.as_dict()["blocking_conditions"]) == 2


@pytest.mark.parametrize("attributed", [0, 1, 4])
def test_unexplained_aggregate_stays_blocked(attributed: int) -> None:
    result = read(
        validation=validation(error_gap_count=3, gaps_by_rule={"rule": {"error": attributed}})
    )
    assert result.readiness is Readiness.BLOCKED
    assert '["validation_error_gaps_unattributed"]' in keys(result)
    assert "3 build error gap(s); at most 0 permitted" in result.blocking_reasons


def test_policy_permitted_rule_counts_do_not_become_new_blockers() -> None:
    result = read(
        manifest=manifest(SLUG, release_policy={"max_open_error_gaps": 2}),
        validation=validation(error_gap_count=1, gaps_by_rule={"rule": {"error": 1}}),
    )
    assert result.is_green
    explicit = read(
        manifest=manifest(
            SLUG, release_policy={"max_open_error_gaps": 2, "block_on_error_rules": ["rule"]}
        ),
        validation=validation(error_gap_count=1, gaps_by_rule={"rule": {"error": 1}}),
    )
    assert keys(explicit) == ('["validation_rule_errors","rule"]',)


@pytest.mark.parametrize(
    "attribution",
    [
        {"rule": None},
        {"rule": 3},
        {"rule": {"error": "bad"}},
        {"rule": {"error": True}},
        {"rule": {"error": -1}},
        {"rule": {"error": 1.0}},
        {" rule ": {"error": 1}},
        {"rule\x00": {"error": 1}},
        {"": {"error": 1}},
    ],
)
def test_malformed_attribution_keeps_the_aggregate_blocker(attribution: Any) -> None:
    """PB-199 C21-6.1 / kernel review R2: bad source detail cannot erase a known block."""

    result = read(validation=validation(error_gap_count=1, gaps_by_rule=attribution))
    assert result.readiness is Readiness.BLOCKED
    assert keys(result) == ('["validation_error_gaps_unattributed"]',)
    assert result.blocking_reasons == ("1 build error gap(s); at most 0 permitted",)


def test_malformed_and_valid_rule_attribution_retain_both_blockers() -> None:
    result = read(
        validation=validation(
            error_gap_count=2,
            gaps_by_rule={"known": {"error": 2}, "unreadable": {"error": "bad"}},
        )
    )
    assert keys(result) == (
        '["validation_error_gaps_unattributed"]',
        '["validation_rule_errors","known"]',
    )
    assert set(result.blocking_reasons) == {
        "2 build error gap(s); at most 0 permitted",
        "known has 2 error gap(s)",
    }


def test_malformed_attribution_below_the_aggregate_threshold_still_refuses() -> None:
    with pytest.raises(ContractError, match="attribution is malformed"):
        read(
            manifest=manifest(SLUG, release_policy={"max_open_error_gaps": 2}),
            validation=validation(error_gap_count=1, gaps_by_rule={"rule": {"error": "bad"}}),
        )


def test_liability_and_regime_parameters_use_the_actual_gate_source() -> None:
    gate = GateManifestEntry(
        gate_id="pilot",
        description="Pilot complete",
        predicate_kind=PredicateKind.PILOT_COUNT,
        status=GateStatus.OPEN,
        launch_blocking=True,
        regime_id="region-a",
    )
    gates = ProductGateManifest(
        manifest_id="gates-1",
        product_slug=SLUG,
        gates=(gate,),
        source_ref="fictional:requirements",
        captured_at=NOW,
        snapshot_ref="fictional:gates",
    )
    result = read(manifest=manifest(SLUG, liability_class=LiabilityClass.C), gate_manifest=gates)
    assert keys(result) == (
        '["launch_bar_open","pilot","region-a"]',
        '["liability_gate_missing","C","counsel_signoff"]',
        '["liability_gate_missing","C","custom"]',
        '["liability_gate_missing","C","insurance"]',
    )
    assert '["launch_bar_open","pilot","region-a"]' not in keys(
        read(gate_manifest=gates, regime_id="region-b")
    )


@pytest.mark.parametrize(
    "conditions",
    [
        None,
        [],
        (),
        (BlockingCondition("coverage_snapshot_missing", (), "Different reason"),),
        (
            BlockingCondition(
                "validation_snapshot_missing", (), "no coverage snapshot has been captured"
            ),
            BlockingCondition(
                "coverage_snapshot_missing", (), "no coverage snapshot has been captured"
            ),
        ),
        (
            BlockingCondition(
                "coverage_snapshot_missing", (), "no coverage snapshot has been captured"
            ),
        )
        * 2,
    ],
)
def test_current_reading_refuses_missing_mismatched_unsorted_or_duplicate_conditions(
    conditions: Any,
) -> None:
    with pytest.raises(ContractError):
        replace(read(coverage=None), blocking_conditions=conditions)


def test_legacy_reason_only_constructor_is_not_silently_admitted() -> None:
    with pytest.raises(TypeError, match="blocking_conditions"):
        ReleaseReadiness(  # type: ignore[call-arg]
            product_slug=SLUG,
            readiness=Readiness.GREEN,
            blocking_reasons=(),
            evaluated_at=NOW,
            coverage_snapshot_id="old-c",
            validation_snapshot_id="old-v",
            gate_manifest_id="old-g",
        )


def test_a_green_reading_cannot_carry_hidden_conditions() -> None:
    with pytest.raises(ContractError, match="cover exactly"):
        replace(read(), blocking_conditions=(BlockingCondition("validation_stale", (), "Stale"),))
