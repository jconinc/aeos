"""Stable release blockers from PB-199 C21-6.1, independent of display wording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aeos_kernel._validation import required
from aeos_kernel.canonical import canonical_json
from aeos_kernel.errors import ContractError

BLOCKING_CONDITION_SCHEMA = "aeos.release-conditions@1"

_ARITIES = {
    "coverage_snapshot_missing": 0,
    "coverage_below_minimum": 0,
    "coverage_kind_unmeasured": 1,
    "coverage_kind_short": 1,
    "coverage_error_gaps": 0,
    "validation_snapshot_missing": 0,
    "validation_stale": 0,
    "warning_gaps_rose": 0,
    "build_gate_failed": 1,
    "validation_rule_errors": 1,
    "validation_error_gaps_unattributed": 0,
    "gate_manifest_missing": 0,
    "liability_gate_missing": 2,
    "launch_bar_open": 2,
}


@dataclass(frozen=True, slots=True)
class BlockingCondition:
    """One closed semantic identity and its current human-readable reason.

    Counts, timestamps, snapshots and display text are deliberately absent from the key.
    A product-wide launch bar uses the empty string as its explicit regime parameter.
    """

    kind: str
    params: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _ARITIES:
            raise ContractError("release blocking condition kind is not recognized")
        if not isinstance(self.params, tuple) or len(self.params) != _ARITIES[self.kind]:
            raise ContractError("release blocking condition params have the wrong shape")
        for index, value in enumerate(self.params):
            if self.kind == "launch_bar_open" and index == 1 and value == "":
                continue
            required(value, "release blocking condition param")
        required(self.reason, "release blocking condition reason")

    @property
    def key(self) -> str:
        return canonical_json([self.kind, *self.params])

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": list(self.params), "reason": self.reason}


def validate_blocking_conditions(
    reasons: tuple[str, ...], conditions: tuple[BlockingCondition, ...]
) -> None:
    """Reject legacy or inconsistent readings instead of deriving identity from prose."""

    if not isinstance(reasons, tuple):
        raise ContractError("release blocking reasons must be a tuple of clean strings")
    for reason in reasons:
        required(reason, "release blocking reason")
    if not isinstance(conditions, tuple) or any(
        not isinstance(condition, BlockingCondition) for condition in conditions
    ):
        raise ContractError("release blocking conditions must be a tuple of BlockingCondition")
    keys = [condition.key for condition in conditions]
    if keys != sorted(set(keys)):
        raise ContractError("release blocking conditions must have unique sorted keys")
    if {condition.reason for condition in conditions} != set(reasons):
        raise ContractError("release blocking conditions must cover exactly the blocking reasons")
