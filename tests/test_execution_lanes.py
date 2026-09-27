"""PB-194: a Move family binds an ordered lane and task declaration."""

from __future__ import annotations

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.execution_lanes import ExecutionLane, MoveTaskLane
from aeos_kernel.modules import MoveFamily, PriorityClass


def _family(steps: tuple[MoveTaskLane, ...]) -> MoveFamily:
    return MoveFamily(
        move_type="example_move",
        module_key="example",
        priority_class=PriorityClass.NORMAL,
        owner_role="operator",
        approval_policy="review",
        evidence_kinds=("example",),
        rails=("example_rail",),
        execution_lanes=steps,
    )


def test_ordered_lane_tuple_is_serialized_without_reordering() -> None:
    steps = (
        MoveTaskLane("prepare", ExecutionLane.DETERMINISTIC),
        MoveTaskLane("draft", ExecutionLane.JUDGMENT, ("draft_text", "score_text")),
        MoveTaskLane("record", ExecutionLane.DETERMINISTIC),
    )
    family = _family(steps)
    assert family.require_execution_lanes() == steps
    assert family.as_dict()["execution_lanes"] == [step.as_dict() for step in steps]


def test_missing_lane_declaration_cannot_activate() -> None:
    with pytest.raises(ContractError, match="has no execution lanes"):
        _family(()).require_execution_lanes()


def test_existing_positional_family_arguments_keep_their_meaning() -> None:
    family = MoveFamily(
        "example_move", "example", PriorityClass.NORMAL, "operator", "review",
        ("example",), ("example_rail",), True,
    )
    assert family.human_override is True
    assert family.execution_lanes == ()


def test_duplicate_step_key_is_refused() -> None:
    with pytest.raises(ContractError, match="step keys must be unique"):
        _family(
            (
                MoveTaskLane("execute", ExecutionLane.DETERMINISTIC),
                MoveTaskLane("execute", ExecutionLane.JUDGMENT, ("draft",)),
            )
        )


def test_deterministic_step_cannot_declare_judgment_task() -> None:
    with pytest.raises(ContractError, match="cannot issue judgment"):
        MoveTaskLane("prepare", ExecutionLane.DETERMINISTIC, ("draft",))


def test_judgment_step_requires_task_and_unique_order() -> None:
    with pytest.raises(ContractError, match="must declare their tasks"):
        MoveTaskLane("draft", ExecutionLane.JUDGMENT)
    with pytest.raises(ContractError, match="must be unique"):
        MoveTaskLane("draft", ExecutionLane.JUDGMENT, ("draft", "draft"))
