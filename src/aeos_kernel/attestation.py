"""Digest-bound human decision contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from aeos_kernel._validation import digest, required, utc
from aeos_kernel.errors import ContractError
from aeos_kernel.vocabulary import HumanResponse


@dataclass(frozen=True, slots=True)
class HumanAttestation:
    attestation_id: str
    actor_id: str
    capacity: str
    decision_id: str
    decision_revision: int
    recommendation_digest: str
    subject_digest: str
    projection_digest: str
    response: HumanResponse
    idempotency_key: str
    decided_at: datetime
    note: str = ""
    snooze_until: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("attestation_id", "actor_id", "capacity", "decision_id", "idempotency_key"):
            required(str(getattr(self, name)), name)
        for name in ("recommendation_digest", "subject_digest", "projection_digest"):
            digest(str(getattr(self, name)), name)
        if self.decision_revision <= 0:
            raise ContractError("decision_revision must be positive")
        utc(self.decided_at, "decided_at")
        if self.snooze_until is not None:
            utc(self.snooze_until, "snooze_until")
        if self.response is HumanResponse.SNOOZE and self.snooze_until is None:
            raise ContractError("snooze response requires snooze_until")
        if self.response is not HumanResponse.SNOOZE and self.snooze_until is not None:
            raise ContractError("snooze_until is only valid for a snooze response")

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["response"] = self.response.value
        value["decided_at"] = self.decided_at.isoformat()
        value["snooze_until"] = self.snooze_until.isoformat() if self.snooze_until else None
        return value
