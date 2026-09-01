"""Host-neutral AEOS ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aeos_kernel.decision import Candidate, ModelDecision
from aeos_kernel.evidence import DecisionPacket, DecisionSubject, EvidenceItem


@dataclass(frozen=True, slots=True)
class ModelChoiceRequest:
    packet: DecisionPacket
    candidates: tuple[Candidate, ...]
    candidate_order: tuple[str, ...]
    attempt: int


class TrustVerifier(Protocol):
    def verify_authority_bundle(self, digest: str) -> bool: ...

    def verify_source_heads(self, source_head_pins: dict[str, str]) -> bool: ...

    def current_subject_revision(self, subject: DecisionSubject) -> str | None: ...

    def verify_research_receipt(self, evidence: EvidenceItem) -> bool: ...


class ModelGateway(Protocol):
    def choose(self, request: ModelChoiceRequest) -> ModelDecision: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
