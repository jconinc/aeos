"""Reference fail-closed authorization for host-registered effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aeos_kernel.attestation import HumanAttestation
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate, Recommendation
from aeos_kernel.effects import AuthorizedEffect
from aeos_kernel.errors import Refusal, RefusalCode
from aeos_kernel.evidence import DecisionPacket
from aeos_kernel.vocabulary import HumanResponse


@dataclass(frozen=True, slots=True)
class RegisteredOperation:
    operation: str
    allowed_parameter_names: frozenset[str]
    boundary_tags: frozenset[str]
    requires_external_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    current_subject_revision: str
    current_subject_digest: str
    effects_enabled: bool
    provider_ready: bool
    available_cost_minor_units: int


def authorize_effect(
    *,
    packet: DecisionPacket,
    recommendation: Recommendation,
    candidate: Candidate,
    attestation: HumanAttestation | None,
    operation: RegisteredOperation | None,
    context: AuthorizationContext,
    idempotency_key: str,
    authorized_at: datetime,
) -> AuthorizedEffect | Refusal:
    effect = candidate.effect
    if effect is None or operation is None or operation.operation != effect.operation:
        return Refusal(RefusalCode.EFFECT_NOT_REGISTERED, "the selected effect is not registered")
    if recommendation.packet_digest != packet.packet_digest:
        return Refusal(RefusalCode.STALE_INPUT, "recommendation does not bind this packet")
    if recommendation.selected_candidate_id != candidate.candidate_id:
        return Refusal(
            RefusalCode.CONFLICT, "candidate is not the recommendation's selected choice"
        )
    if not context.effects_enabled or not context.provider_ready:
        return Refusal(RefusalCode.EFFECT_PRECONDITION_FAILED, "host effect controls are not ready")
    if (
        context.current_subject_revision != packet.subject.revision
        or context.current_subject_digest != packet.subject.content_digest
    ):
        return Refusal(RefusalCode.STALE_INPUT, "subject changed before effect authorization")
    if set(effect.parameters) - operation.allowed_parameter_names:
        return Refusal(RefusalCode.EFFECT_NOT_REGISTERED, "effect contains unregistered parameters")
    if set(effect.boundary_tags) != set(operation.boundary_tags):
        return Refusal(RefusalCode.BOUNDARY_NOT_AUTHORIZED, "effect boundary declaration drifted")
    if set(effect.boundary_tags) - set(packet.policy.allowed_boundary_tags):
        return Refusal(
            RefusalCode.BOUNDARY_NOT_AUTHORIZED, "policy does not authorize effect boundaries"
        )
    if effect.cost_ceiling_minor_units > context.available_cost_minor_units:
        return Refusal(
            RefusalCode.EFFECT_PRECONDITION_FAILED, "effect cost ceiling exceeds available budget"
        )
    if packet.policy.requires_human_attestation:
        refusal = _verify_attestation(packet, recommendation, attestation)
        if refusal is not None:
            return refusal
    policy_digest = stable_fingerprint(packet.policy.as_dict())
    authorization_id = (
        "authorization_"
        + stable_fingerprint(
            {
                "decision_id": recommendation.decision_id,
                "decision_revision": recommendation.decision_revision,
                "operation": effect.operation,
                "parameters": effect.parameters,
                "idempotency_key": idempotency_key,
                "policy_digest": policy_digest,
            }
        )[:24]
    )
    return AuthorizedEffect(
        authorization_id=authorization_id,
        decision_id=recommendation.decision_id,
        decision_revision=recommendation.decision_revision,
        operation=effect.operation,
        parameters=effect.parameters,
        boundary_tags=effect.boundary_tags,
        precondition_digest=packet.subject.content_digest,
        expected_postcondition=effect.expected_postcondition,
        idempotency_key=idempotency_key,
        authorized_at=authorized_at,
        authority_policy_digest=policy_digest,
        attestation_id=attestation.attestation_id if attestation else "",
        compensation_ref=effect.compensation_ref,
        cost_ceiling_minor_units=effect.cost_ceiling_minor_units,
    )


def _verify_attestation(
    packet: DecisionPacket,
    recommendation: Recommendation,
    attestation: HumanAttestation | None,
) -> Refusal | None:
    if attestation is None:
        return Refusal(RefusalCode.HUMAN_REQUIRED, "the required human attestation is absent")
    if attestation.capacity != packet.policy.required_capacity:
        return Refusal(
            RefusalCode.HUMAN_ATTESTATION_INVALID, "attestation capacity is not authorized"
        )
    if (
        attestation.decision_id != recommendation.decision_id
        or attestation.decision_revision != recommendation.decision_revision
        or attestation.recommendation_digest != recommendation.digest
        or attestation.subject_digest != packet.subject.content_digest
    ):
        return Refusal(RefusalCode.HUMAN_ATTESTATION_INVALID, "attestation binds different bytes")
    if attestation.response is not HumanResponse.USE_THIS:
        return Refusal(RefusalCode.HUMAN_ATTESTATION_INVALID, "only Use this authorizes the effect")
    return None
