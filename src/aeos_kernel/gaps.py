"""Gap rows: the one shape every unmet obligation takes.

A gap is what the control plane could not derive, stated so an operator can read it. Rails,
module loading, coverage capture and release gates all emit this kind rather than each
keeping private bookkeeping, so "what is unresolved for this product" stays a single query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from aeos_kernel._validation import required, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError


class GapSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class GapRow:
    """One unmet obligation, scoped to the product it is about."""

    gap_type: str
    severity: GapSeverity
    product_slug: str
    subject_ref: str
    reason: str
    detected_at: datetime
    move_id: str = ""
    rulepack_version: str = ""
    data_snapshot_ref: str = ""
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("gap_type", "product_slug", "subject_ref", "reason"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.severity, GapSeverity):
            raise ContractError("gap severity is not recognized")
        utc(self.detected_at, "detected_at")
        for name in ("move_id", "rulepack_version", "data_snapshot_ref"):
            value = str(getattr(self, name))
            if value:
                required(value, name)
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ContractError("gap evidence references must be unique")
        for reference in self.evidence_refs:
            required(reference, "gap evidence reference")

    @property
    def identity(self) -> str:
        """Gap identity is the move, rulepack and snapshot it was found under.

        A dispute re-run under the same three dedups against the original; a re-run under a
        new snapshot is a new gap, never a silent no-op.
        """

        return stable_fingerprint(
            {
                "gap_type": self.gap_type,
                "product_slug": self.product_slug,
                "subject_ref": self.subject_ref,
                "move_id": self.move_id,
                "rulepack_version": self.rulepack_version,
                "data_snapshot_ref": self.data_snapshot_ref,
            }
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "gap_id": self.identity,
            "gap_type": self.gap_type,
            "severity": self.severity.value,
            "product_slug": self.product_slug,
            "subject_ref": self.subject_ref,
            "reason": self.reason,
            "detected_at": self.detected_at.isoformat(),
            "move_id": self.move_id,
            "rulepack_version": self.rulepack_version,
            "data_snapshot_ref": self.data_snapshot_ref,
            "evidence_refs": list(self.evidence_refs),
        }


def error_gaps(gaps: tuple[GapRow, ...]) -> tuple[GapRow, ...]:
    return tuple(gap for gap in gaps if gap.severity is GapSeverity.ERROR)


def gaps_in_scope(gaps: tuple[GapRow, ...], *, product_slug: str) -> tuple[GapRow, ...]:
    """Scope a gap set to one product.

    Every gate reads its gaps through this, so a gate can never widen into an archive-wide
    scan as the ledger grows.
    """

    return tuple(gap for gap in gaps if gap.product_slug == product_slug)
