"""Host-neutral AEOS ports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aeos_kernel.attestation import HumanAttestation
from aeos_kernel.decision import Candidate, ModelDecision, Recommendation
from aeos_kernel.effects import AuthorizedEffect, EffectReceipt, OutcomeEvidence
from aeos_kernel.errors import Refusal
from aeos_kernel.evidence import DecisionPacket, DecisionSubject, EvidenceItem
from aeos_kernel.lifecycle import DecisionRecord


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


class EvidenceSource(Protocol):
    def build_packet(self, subject_ref: str) -> DecisionPacket: ...


class CandidateSource(Protocol):
    def enumerate(self, packet: DecisionPacket) -> Sequence[Candidate]: ...


class RecommendationRepository(Protocol):
    def put(self, recommendation: Recommendation) -> Recommendation: ...

    def get(self, decision_id: str, revision: int) -> Recommendation | None: ...


class AttestationRepository(Protocol):
    def record(self, attestation: HumanAttestation) -> HumanAttestation: ...


class DecisionRepository(Protocol):
    def append(self, record: DecisionRecord) -> DecisionRecord: ...

    def latest(self, decision_id: str) -> DecisionRecord | None: ...


class EffectAuthorizer(Protocol):
    def authorize(
        self,
        recommendation: Recommendation,
        candidate: Candidate,
        packet: DecisionPacket,
        attestation: HumanAttestation | None,
    ) -> AuthorizedEffect | Refusal: ...


class EffectExecutor(Protocol):
    def execute(self, effect: AuthorizedEffect) -> EffectReceipt: ...


class OutcomeSource(Protocol):
    def observe(self, receipt: EffectReceipt) -> Sequence[OutcomeEvidence]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
