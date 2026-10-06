"""Stable release blockers from PB-199 C21-6.1, independent of display wording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aeos_kernel._validation import required
from aeos_kernel.canonical import canonical_json
from aeos_kernel.errors import ContractError

BLOCKING_CONDITION_SCHEMA = "aeos.release-conditions@1"
BLOCKING_CONDITION_SCHEMA_V2 = "aeos.release-conditions@2"

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
_V2_ARITIES = {
    "validation_new_gap": 0,
    "validation_convergence_unavailable": 0,
    "validation_targets_open": 0,
    "validation_commit_interval_incomplete": 0,
    "validation_prior_obligations_open": 0,
}
_ALL_ARITIES = {**_ARITIES, **_V2_ARITIES}


def _schema_arities(schema: str) -> dict[str, int]:
    if schema == BLOCKING_CONDITION_SCHEMA:
        return _ARITIES
    if schema == BLOCKING_CONDITION_SCHEMA_V2:
        return _ALL_ARITIES
    raise ContractError("release blocking condition schema is not recognized")


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
        if not isinstance(self.kind, str) or self.kind not in _ALL_ARITIES:
            raise ContractError("release blocking condition kind is not recognized")
        if not isinstance(self.params, tuple) or len(self.params) != _ALL_ARITIES[self.kind]:
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
    reasons: tuple[str, ...], conditions: tuple[BlockingCondition, ...], *,
    schema: str = BLOCKING_CONDITION_SCHEMA,
) -> None:
    """Reject legacy or inconsistent readings instead of deriving identity from prose."""

    arities = _schema_arities(schema)
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
    if any(condition.kind not in arities for condition in conditions):
        raise ContractError("release blocking condition does not belong to this schema")


def encode_blocking_conditions(
    conditions: tuple[BlockingCondition, ...], *, schema: str = BLOCKING_CONDITION_SCHEMA,
) -> dict[str, Any]:
    validate_blocking_conditions(tuple(condition.reason for condition in conditions), conditions,
                                 schema=schema)
    return {"schema": schema, "conditions": [condition.as_dict() for condition in conditions]}


def decode_blocking_conditions(value: Any) -> tuple[BlockingCondition, ...]:
    """Decode archived @1 or current @2 without changing their semantic identities."""
    if (not isinstance(value, dict) or set(value) != {"schema", "conditions"}
        or not isinstance(value["schema"], str) or not isinstance(value["conditions"], list)):
        raise ContractError("release blocking condition document has the wrong shape")
    _schema_arities(value["schema"])
    decoded = []
    for item in value["conditions"]:
        if (not isinstance(item, dict) or set(item) != {"kind", "params", "reason"}
            or not isinstance(item["params"], list)):
            raise ContractError("release blocking condition document has the wrong shape")
        decoded.append(BlockingCondition(item["kind"], tuple(item["params"]), item["reason"]))
    result = tuple(decoded)
    validate_blocking_conditions(tuple(condition.reason for condition in result), result,
                                 schema=value["schema"])
    return result
