"""Material dependency drift classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aeos_kernel._validation import digest, required
from aeos_kernel.canonical import stable_fingerprint


class DriftReason(StrEnum):
    SUBJECT_CHANGED = "subject_changed"
    EVIDENCE_CHANGED_OR_EXPIRED = "evidence_changed_or_expired"
    CANON_CHANGED = "canon_changed"
    AUTHORITY_CHANGED = "authority_changed"
    CANDIDATE_CONTRACT_CHANGED = "candidate_contract_changed"
    HOST_POLICY_CHANGED = "host_policy_changed"
    EXPECTED_POSTIMAGE_MISMATCH = "expected_postimage_mismatch"
    OUTCOME_WINDOW_ELAPSED = "outcome_window_elapsed"


@dataclass(frozen=True, slots=True)
class DependencySnapshot:
    subject_digest: str
    evidence_digest: str
    canon_digest: str
    authority_digest: str
    candidate_contract_digest: str
    host_policy_digest: str
    expected_postimage_digest: str = ""
    outcome_window_digest: str = ""
    schema_version: str = "1"

    def __post_init__(self) -> None:
        required(self.schema_version, "schema_version")
        for name in (
            "subject_digest",
            "evidence_digest",
            "canon_digest",
            "authority_digest",
            "candidate_contract_digest",
            "host_policy_digest",
        ):
            digest(str(getattr(self, name)), name)
        for name in ("expected_postimage_digest", "outcome_window_digest"):
            value = str(getattr(self, name))
            if value:
                digest(value, name)

    def as_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "subject_digest": self.subject_digest,
            "evidence_digest": self.evidence_digest,
            "canon_digest": self.canon_digest,
            "authority_digest": self.authority_digest,
            "candidate_contract_digest": self.candidate_contract_digest,
            "host_policy_digest": self.host_policy_digest,
            "expected_postimage_digest": self.expected_postimage_digest,
            "outcome_window_digest": self.outcome_window_digest,
        }

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())


def classify_drift(
    previous: DependencySnapshot, current: DependencySnapshot
) -> tuple[DriftReason, ...]:
    mapping = (
        ("subject_digest", DriftReason.SUBJECT_CHANGED),
        ("evidence_digest", DriftReason.EVIDENCE_CHANGED_OR_EXPIRED),
        ("canon_digest", DriftReason.CANON_CHANGED),
        ("authority_digest", DriftReason.AUTHORITY_CHANGED),
        ("candidate_contract_digest", DriftReason.CANDIDATE_CONTRACT_CHANGED),
        ("host_policy_digest", DriftReason.HOST_POLICY_CHANGED),
        ("expected_postimage_digest", DriftReason.EXPECTED_POSTIMAGE_MISMATCH),
        ("outcome_window_digest", DriftReason.OUTCOME_WINDOW_ELAPSED),
    )
    return tuple(
        reason
        for field_name, reason in mapping
        if getattr(previous, field_name) != getattr(current, field_name)
    )
