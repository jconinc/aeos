"""AEOS public API."""

from aeos_kernel.attestation import HumanAttestation
from aeos_kernel.authority import (
    AuthorityLayer,
    AuthorityRecord,
    AuthorityResolution,
    AuthorityResolutionStatus,
    AuthorityStatus,
    ScopeSelector,
    SelectorType,
    resolve_authority,
    selector_matches,
    selector_specificity,
)
from aeos_kernel.candidate_resolution import (
    EVIDENCE_RANK,
    PLACEHOLDER_TARGET_IDS,
    ResolutionResult,
    ResolvedCandidate,
    resolve_unique,
)
from aeos_kernel.canonical import canonical_json, content_digest, stable_fingerprint
from aeos_kernel.decision import (
    Candidate,
    EffectTemplate,
    EntailmentProof,
    ModelCallIdentity,
    ModelDecision,
    Recommendation,
    candidate_set_digest,
)
from aeos_kernel.drift import DependencySnapshot, DriftReason, classify_drift
from aeos_kernel.effect_authorization import (
    AuthorizationContext,
    RegisteredOperation,
    authorize_effect,
    verify_effect_receipt,
)
from aeos_kernel.effects import (
    AuthorizedEffect,
    EffectReceipt,
    EffectStatus,
    OutcomeEvidence,
    OutcomeStatus,
    build_outcome_evidence,
)
from aeos_kernel.engine import DecisionEngine
from aeos_kernel.errors import ContractError, Refusal, RefusalCode
from aeos_kernel.evidence import (
    AuthorityPolicy,
    DecisionPacket,
    DecisionSubject,
    EvidenceItem,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
)
from aeos_kernel.graph import GraphEdge, GraphNode, GraphSnapshot
from aeos_kernel.graph_builder import build_graph_snapshot
from aeos_kernel.graph_vocabulary import GraphVocabulary
from aeos_kernel.lifecycle import DecisionRecord, reopen_record, transition_record
from aeos_kernel.vocabulary import (
    AuthorityLevel,
    DecisionIntensity,
    DecisionStatus,
    HumanResponse,
    PrivacyClass,
)

__version__ = "0.3.1"

__all__ = [
    "EVIDENCE_RANK",
    "PLACEHOLDER_TARGET_IDS",
    "AuthorityLayer",
    "AuthorityLevel",
    "AuthorityPolicy",
    "AuthorityRecord",
    "AuthorityResolution",
    "AuthorityResolutionStatus",
    "AuthorityStatus",
    "AuthorizationContext",
    "AuthorizedEffect",
    "Candidate",
    "ContractError",
    "DecisionEngine",
    "DecisionIntensity",
    "DecisionPacket",
    "DecisionRecord",
    "DecisionStatus",
    "DecisionSubject",
    "DependencySnapshot",
    "DriftReason",
    "EffectReceipt",
    "EffectStatus",
    "EffectTemplate",
    "EntailmentProof",
    "EvidenceItem",
    "GraphEdge",
    "GraphNode",
    "GraphSnapshot",
    "GraphVocabulary",
    "HumanAttestation",
    "HumanResponse",
    "ModelCallIdentity",
    "ModelDecision",
    "OutcomeEvidence",
    "OutcomeStatus",
    "PrivacyClass",
    "Recommendation",
    "Refusal",
    "RefusalCode",
    "RegisteredOperation",
    "ResolutionResult",
    "ResolvedCandidate",
    "ScopeSelector",
    "SelectorType",
    "SourceRef",
    "authorize_effect",
    "build_decision_packet",
    "build_evidence_item",
    "build_graph_snapshot",
    "build_outcome_evidence",
    "candidate_set_digest",
    "canonical_json",
    "classify_drift",
    "content_digest",
    "reopen_record",
    "resolve_authority",
    "resolve_unique",
    "selector_matches",
    "selector_specificity",
    "stable_fingerprint",
    "transition_record",
    "verify_effect_receipt",
]
