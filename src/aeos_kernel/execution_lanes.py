"""Project-neutral ordered lane declarations for Move families (PB-194 §3)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aeos_kernel._validation import required
from aeos_kernel.errors import ContractError


class ExecutionLane(StrEnum):
    DETERMINISTIC = "deterministic"
    JUDGMENT = "judgment"


@dataclass(frozen=True, slots=True)
class MoveTaskLane:
    """One ordered step and the judgment tasks it alone may issue.

    Wema owns entrypoints, automata, graph proof, and durable admissions. This
    declaration carries no authority to call a model on its own.
    """

    step_key: str
    lane: ExecutionLane
    permitted_judgment_tasks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required(self.step_key, "execution step key")
        if not isinstance(self.lane, ExecutionLane):
            raise ContractError("execution lane is not recognized")
        if not isinstance(self.permitted_judgment_tasks, tuple):
            raise ContractError("judgment tasks must be an ordered tuple")
        if len(set(self.permitted_judgment_tasks)) != len(self.permitted_judgment_tasks):
            raise ContractError("judgment tasks must be unique within a step")
        for task in self.permitted_judgment_tasks:
            required(task, "judgment task")
        if self.lane is ExecutionLane.DETERMINISTIC and self.permitted_judgment_tasks:
            raise ContractError("deterministic steps cannot issue judgment tasks")
        if self.lane is ExecutionLane.JUDGMENT and not self.permitted_judgment_tasks:
            raise ContractError("judgment steps must declare their tasks")

    def as_dict(self) -> dict[str, object]:
        return {
            "step_key": self.step_key,
            "lane": self.lane.value,
            "permitted_judgment_tasks": list(self.permitted_judgment_tasks),
        }
