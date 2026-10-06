"""PB-235: native convergence changes readiness before any consumer can observe green."""
from __future__ import annotations

from dataclasses import replace

import pytest

from aeos_kernel import (
    BLOCKING_CONDITION_SCHEMA,
    BLOCKING_CONDITION_SCHEMA_V2,
    BlockingCondition,
    Run,
    RunStatus,
    Stage,
    WlgConvergenceEvidence,
    WlgConvergenceScope,
    WLGStage,
    decode_blocking_conditions,
    encode_blocking_conditions,
)
from aeos_kernel.errors import ContractError
from aeos_kernel.pipeline import Readiness
from tests.factories_control_plane import NOW
from tests.test_release_conditions import SLUG, read, validation


def convergence(**changes) -> WlgConvergenceEvidence:
    original = WlgConvergenceEvidence(
        scope=WlgConvergenceScope(SLUG, "binding-1", "native-project", "run-1", 2,
            "a" * 64, "adopted-native-policy", 1, "b" * 64, "c" * 64),
        current_validation_snapshot_id="validation-1", current_bundle_id="bundle-1",
        current_census_digest="d" * 64, prior_validation_snapshot_id="validation-0",
        prior_bundle_id="bundle-0", prior_census_digest="e" * 64,
        convergence_digest="f" * 64, comparison_state="comparable",
        carried_gap_keys=(), targets_closed=True, commit_interval_complete=True,
        prior_scope_unresolved=())
    return replace(original, **changes)


def test_new_native_problem_blocks_before_readiness_is_returned() -> None:
    reading = read(wlg_convergence=convergence(carried_gap_keys=("1" * 64,)))
    assert reading.readiness is Readiness.BLOCKED
    assert reading.condition_schema == BLOCKING_CONDITION_SCHEMA_V2
    assert reading.blocking_reasons == ("A new validation problem appeared after the repair.",)
    assert reading.blocking_conditions[0].key == '["validation_new_gap"]'
    # Equal native counts and all existing native gates green cannot hide a changed key.
    assert read(wlg_convergence=convergence()).readiness is Readiness.GREEN


@pytest.mark.parametrize(("changes", "kind"), [
    ({"comparison_state": "incomparable"}, "validation_convergence_unavailable"),
    ({"targets_closed": False}, "validation_targets_open"),
    ({"commit_interval_complete": False}, "validation_commit_interval_incomplete"),
    ({"prior_scope_unresolved": ("2" * 64,)}, "validation_prior_obligations_open"),
])
def test_incomplete_native_convergence_never_becomes_green(changes, kind) -> None:
    reading = read(wlg_convergence=convergence(**changes))
    assert reading.readiness is Readiness.BLOCKED
    assert kind in {condition.kind for condition in reading.blocking_conditions}


def test_genesis_is_a_baseline_and_retains_independent_native_blockers() -> None:
    source = convergence(comparison_state="genesis", prior_validation_snapshot_id=None,
        prior_bundle_id=None, prior_census_digest=None,
        targets_closed=False, commit_interval_complete=False)
    reading = read(wlg_convergence=source, validation=validation(warning_gap_count=1))
    assert reading.readiness is Readiness.BLOCKED
    assert {condition.kind for condition in reading.blocking_conditions} == {
        "validation_convergence_unavailable", "validation_targets_open",
        "validation_commit_interval_incomplete", "warning_gaps_rose"}


def test_convergence_refuses_cross_product_binding_or_validation() -> None:
    base = convergence()
    for source in (replace(base, scope=replace(base.scope, product_slug="other")),
                   replace(base, scope=replace(base.scope, binding_key="other")),
                   replace(base, current_validation_snapshot_id="other")):
        with pytest.raises(ContractError, match="current readiness sources"):
            read(wlg_convergence=source)


def test_scope_excludes_reading_ids_but_binds_native_scope_and_schema() -> None:
    original = convergence()
    later = replace(original, current_bundle_id="later", current_validation_snapshot_id="later",
        current_census_digest="0" * 64)
    assert later.scope.scope_digest == original.scope.scope_digest
    changed = replace(original.scope, registry_digest="0" * 64)
    assert changed.scope_digest != original.scope.scope_digest
    assert replace(original.scope, run_stage_version=3).scope_digest != original.scope.scope_digest


def test_versioned_condition_codec_preserves_archived_v1_and_refuses_wrong_schema() -> None:
    archived = (BlockingCondition("validation_stale", (), "Archived stale result"),)
    assert decode_blocking_conditions(encode_blocking_conditions(archived)) == archived
    condition = (BlockingCondition("validation_new_gap", (),
        "A new validation problem appeared after the repair."),)
    current = encode_blocking_conditions(condition, schema=BLOCKING_CONDITION_SCHEMA_V2)
    assert decode_blocking_conditions(current) == condition
    with pytest.raises(ContractError, match="belong to this schema"):
        encode_blocking_conditions(condition)
    with pytest.raises(ContractError, match="belong to this schema"):
        decode_blocking_conditions({**current, "schema": BLOCKING_CONDITION_SCHEMA})
    assert read().condition_schema == BLOCKING_CONDITION_SCHEMA


def test_wlg_runs_use_actual_module_stages_and_marketing_retains_its_stages() -> None:
    wlg = Run("wlg-run", SLUG, "prod_wlg", WLGStage.BUILDING, RunStatus.RUNNING, NOW)
    marketing = Run("marketing-run", SLUG, "marketing", Stage.SEED, RunStatus.RUNNING, NOW)
    assert wlg.stage is WLGStage.BUILDING
    assert marketing.stage is Stage.SEED
    with pytest.raises(ContractError):
        Run("wlg-run", SLUG, "prod_wlg", Stage.SEED, RunStatus.RUNNING, NOW)
    with pytest.raises(ContractError):
        Run("marketing-run", SLUG, "marketing", WLGStage.BUILDING, RunStatus.RUNNING, NOW)
