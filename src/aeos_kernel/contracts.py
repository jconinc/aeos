"""Compatibility export surface for AEOS public contracts.

New code may import from the focused modules; this module keeps one stable discoverable
surface without collecting their implementations into an oversized file.
"""

from aeos_kernel.attestation import HumanAttestation
from aeos_kernel.decision import (
    Candidate,
    EffectTemplate,
    EntailmentProof,
    ModelCallIdentity,
    ModelDecision,
    Recommendation,
    candidate_set_digest,
)
from aeos_kernel.evidence import (
    AuthorityPolicy,
    DecisionPacket,
    DecisionSubject,
    EvidenceItem,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
)
from aeos_kernel.vocabulary import (
    AuthorityLevel,
    DecisionIntensity,
    DecisionStatus,
    HumanResponse,
    PrivacyClass,
)

__all__ = [
    "AuthorityLevel",
    "AuthorityPolicy",
    "Candidate",
    "DecisionIntensity",
    "DecisionPacket",
    "DecisionStatus",
    "DecisionSubject",
    "EffectTemplate",
    "EntailmentProof",
    "EvidenceItem",
    "HumanAttestation",
    "HumanResponse",
    "ModelCallIdentity",
    "ModelDecision",
    "PrivacyClass",
    "Recommendation",
    "SourceRef",
    "build_decision_packet",
    "build_evidence_item",
    "candidate_set_digest",
]
