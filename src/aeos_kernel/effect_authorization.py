"""Fail-closed authorization and receipt verification for host-registered effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aeos_kernel._validation import (
    digest,
    immutable_json_object,
    required,
    thaw_json,
    utc,
)
from aeos_kernel.attestation import HumanAttestation
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate, Recommendation, candidate_set_digest
from aeos_kernel.effects import AuthorizedEffect, EffectReceipt, EffectStatus
from aeos_kernel.errors import Refusal, RefusalCode
from aeos_kernel.evidence import DecisionPacket
from aeos_kernel.vocabulary import DecisionIntensity, HumanResponse


@dataclass(frozen=True, slots=True)
class RegisteredOperation:
    """The exact current host operation contract, resolved from a closed registry."""

    operation: str
    operation_version: str
    parameter_names: frozenset[str]
    boundary_tags: frozenset[str]
    expected_postcondition: str
    intensity: DecisionIntensity
    requires_external_confirmation: bool = False
    fanout_ceiling: int = 1

    def __post_init__(self) -> None:
        required(self.operation, "operation")
        required(self.operation_version, "operation_version")
        required(self.expected_postcondition, "expected_postcondition")
        if not self.parameter_names:
            raise ValueError("registered operation parameter_names must be nonempty")
        for name in self.parameter_names:
            required(name, "registered operation parameter name")
        for tag in self.boundary_tags:
            required(tag, "registered operation boundary tag")
        if not isinstance(self.intensity, DecisionIntensity):
            raise ValueError("registered operation intensity is not recognized")
        if self.intensity is DecisionIntensity.ADVISORY:
            raise ValueError("an advisory decision cannot register an effect operation")
        if (
            self.requires_external_confirmation
            and self.intensity is not DecisionIntensity.OUTWARD_OR_IRREVERSIBLE
        ):
            raise ValueError("external confirmation belongs to an outward operation")
        if self.fanout_ceiling <= 0:
            raise ValueError("registered operation fanout ceiling must be positive")

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "operation_version": self.operation_version,
            "parameter_names": sorted(self.parameter_names),
            "boundary_tags": sorted(self.boundary_tags),
            "expected_postcondition": self.expected_postcondition,
            "intensity": int(self.intensity),
            "requires_external_confirmation": self.requires_external_confirmation,
            "fanout_ceiling": self.fanout_ceiling,
        }

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Current facts independently resolved by the host immediately before execution."""

    current_subject_revision: str
    current_subject_digest: str
    current_packet_digest: str
    current_recommendation_digest: str
    current_candidate_set_digest: str
    current_projection_digest: str
    current_authority_bundle_digest: str
    current_policy_digest: str
    current_operation_digest: str
    current_source_head_pins: dict[str, str]
    current_adapter_id: str
    current_adapter_version: str
    verified_actor_id: str
    verified_capacity: str
    effects_enabled: bool
    provider_ready: bool
    available_cost_minor_units: int

    def __post_init__(self) -> None:
        for name in (
            "current_subject_revision",
            "current_adapter_id",
            "current_adapter_version",
            "verified_actor_id",
            "verified_capacity",
        ):
            required(str(getattr(self, name)), name)
        for name in (
            "current_subject_digest",
            "current_packet_digest",
            "current_recommendation_digest",
            "current_candidate_set_digest",
            "current_projection_digest",
            "current_authority_bundle_digest",
            "current_policy_digest",
            "current_operation_digest",
        ):
            digest(str(getattr(self, name)), name)
        if self.available_cost_minor_units < 0:
            raise ValueError("available effect cost must be nonnegative")
        object.__setattr__(
            self,
            "current_source_head_pins",
            immutable_json_object(self.current_source_head_pins, "current_source_head_pins"),
        )
        if not self.current_source_head_pins:
            raise ValueError("current_source_head_pins must be nonempty")

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_subject_revision": self.current_subject_revision,
            "current_subject_digest": self.current_subject_digest,
            "current_packet_digest": self.current_packet_digest,
            "current_recommendation_digest": self.current_recommendation_digest,
            "current_candidate_set_digest": self.current_candidate_set_digest,
            "current_projection_digest": self.current_projection_digest,
            "current_authority_bundle_digest": self.current_authority_bundle_digest,
            "current_policy_digest": self.current_policy_digest,
            "current_operation_digest": self.current_operation_digest,
            "current_source_head_pins": thaw_json(self.current_source_head_pins),
            "current_adapter_id": self.current_adapter_id,
            "current_adapter_version": self.current_adapter_version,
            "verified_actor_id": self.verified_actor_id,
            "verified_capacity": self.verified_capacity,
            "effects_enabled": self.effects_enabled,
            "provider_ready": self.provider_ready,
            "available_cost_minor_units": self.available_cost_minor_units,
        }


def authorize_effect(
    *,
    packet: DecisionPacket,
    recommendation: Recommendation,
    candidates: tuple[Candidate, ...],
    attestation: HumanAttestation | None,
    operation: RegisteredOperation | None,
    context: AuthorizationContext,
    idempotency_key: str,
    authorized_at: datetime,
) -> AuthorizedEffect | Refusal:
    """Authorize only the exact currently registered, presented and attested effect."""

    required(idempotency_key, "idempotency_key")
    utc(authorized_at, "authorized_at")
    if operation is None:
        return Refusal(RefusalCode.EFFECT_NOT_REGISTERED, "the selected effect is not registered")
    if not packet.has_canonical_digest() or packet.packet_digest != context.current_packet_digest:
        return Refusal(RefusalCode.STALE_INPUT, "packet is not the current canonical packet")
    if recommendation.digest != context.current_recommendation_digest:
        return Refusal(RefusalCode.STALE_INPUT, "recommendation is not the current exact record")
    if recommendation.packet_digest != packet.packet_digest:
        return Refusal(RefusalCode.STALE_INPUT, "recommendation does not bind this packet")
    exact_candidate_digest = candidate_set_digest(candidates)
    if (
        exact_candidate_digest != recommendation.candidate_set_digest
        or exact_candidate_digest != context.current_candidate_set_digest
    ):
        return Refusal(RefusalCode.CONFLICT, "candidate set does not bind the recommendation")
    selected = tuple(
        candidate
        for candidate in candidates
        if candidate.candidate_id == recommendation.selected_candidate_id
    )
    if len(selected) != 1:
        return Refusal(RefusalCode.CONFLICT, "selected candidate is absent or ambiguous")
    candidate = selected[0]
    effect = candidate.effect
    if (
        effect is None
        or operation.operation != effect.operation
        or operation.operation_version != effect.operation_version
    ):
        return Refusal(RefusalCode.EFFECT_NOT_REGISTERED, "the selected effect is not registered")
    current_policy_digest = stable_fingerprint(packet.policy.as_dict())
    if (
        packet.authority_bundle_digest != context.current_authority_bundle_digest
        or current_policy_digest != context.current_policy_digest
        or operation.digest != context.current_operation_digest
        or dict(packet.source_head_pins) != dict(context.current_source_head_pins)
        or packet.adapter_id != context.current_adapter_id
        or packet.adapter_version != context.current_adapter_version
    ):
        return Refusal(
            RefusalCode.STALE_INPUT,
            "authority, policy, operation or source pins changed",
        )
    if not context.effects_enabled or not context.provider_ready:
        return Refusal(RefusalCode.EFFECT_PRECONDITION_FAILED, "host effect controls are not ready")
    if (
        context.current_subject_revision != packet.subject.revision
        or context.current_subject_digest != packet.subject.content_digest
    ):
        return Refusal(RefusalCode.STALE_INPUT, "subject changed before effect authorization")
    if set(effect.parameters) != set(operation.parameter_names):
        return Refusal(RefusalCode.EFFECT_NOT_REGISTERED, "effect parameter contract drifted")
    if set(effect.boundary_tags) != set(operation.boundary_tags):
        return Refusal(RefusalCode.BOUNDARY_NOT_AUTHORIZED, "effect boundary declaration drifted")
    if set(effect.boundary_tags) - set(packet.policy.allowed_boundary_tags):
        return Refusal(
            RefusalCode.BOUNDARY_NOT_AUTHORIZED,
            "policy does not authorize effect boundaries",
        )
    if (
        effect.expected_postcondition != operation.expected_postcondition
        or packet.policy.intensity is not operation.intensity
        or effect.fanout_ceiling > operation.fanout_ceiling
    ):
        return Refusal(RefusalCode.EFFECT_NOT_REGISTERED, "effect result contract drifted")
    if effect.cost_ceiling_minor_units > context.available_cost_minor_units:
        return Refusal(
            RefusalCode.EFFECT_PRECONDITION_FAILED,
            "effect cost ceiling exceeds available budget",
        )
    if packet.policy.requires_human_attestation:
        refusal = _verify_attestation(
            packet,
            recommendation,
            attestation,
            context=context,
            idempotency_key=idempotency_key,
            authorized_at=authorized_at,
        )
        if refusal is not None:
            return refusal
    policy_digest = stable_fingerprint(packet.policy.as_dict())
    authorization_id = "authorization_" + stable_fingerprint(
        {
            "decision_id": recommendation.decision_id,
            "decision_revision": recommendation.decision_revision,
            "packet_digest": packet.packet_digest,
            "recommendation_digest": recommendation.digest,
            "candidate_set_digest": exact_candidate_digest,
            "projection_digest": context.current_projection_digest,
            "operation_digest": operation.digest,
            "parameters": thaw_json(effect.parameters),
            "idempotency_key": idempotency_key,
            "policy_digest": policy_digest,
        }
    )[:24]
    return AuthorizedEffect(
        authorization_id=authorization_id,
        decision_id=recommendation.decision_id,
        decision_revision=recommendation.decision_revision,
        operation=effect.operation,
        operation_version=effect.operation_version,
        operation_contract_digest=operation.digest,
        parameters=thaw_json(effect.parameters),
        boundary_tags=effect.boundary_tags,
        precondition_digest=packet.subject.content_digest,
        expected_postcondition=effect.expected_postcondition,
        idempotency_key=idempotency_key,
        authorized_at=authorized_at,
        authority_policy_digest=policy_digest,
        recommendation_digest=recommendation.digest,
        candidate_set_digest=exact_candidate_digest,
        projection_digest=context.current_projection_digest,
        source_head_pins_digest=stable_fingerprint(thaw_json(packet.source_head_pins)),
        attestation_id=attestation.attestation_id if attestation else "",
        attestation_digest=attestation.digest if attestation else "",
        compensation_ref=effect.compensation_ref,
        cost_ceiling_minor_units=effect.cost_ceiling_minor_units,
    )


def _verify_attestation(
    packet: DecisionPacket,
    recommendation: Recommendation,
    attestation: HumanAttestation | None,
    *,
    context: AuthorizationContext,
    idempotency_key: str,
    authorized_at: datetime,
) -> Refusal | None:
    if attestation is None:
        return Refusal(RefusalCode.HUMAN_REQUIRED, "the required human attestation is absent")
    if (
        attestation.actor_id != context.verified_actor_id
        or attestation.capacity != context.verified_capacity
        or attestation.capacity != packet.policy.required_capacity
    ):
        return Refusal(
            RefusalCode.HUMAN_ATTESTATION_INVALID,
            "attestation actor or capacity was not independently authorized",
        )
    if (
        attestation.decision_id != recommendation.decision_id
        or attestation.decision_revision != recommendation.decision_revision
        or attestation.recommendation_digest != recommendation.digest
        or attestation.subject_digest != packet.subject.content_digest
        or attestation.projection_digest != context.current_projection_digest
        or attestation.idempotency_key != idempotency_key
        or attestation.decided_at > authorized_at
    ):
        return Refusal(RefusalCode.HUMAN_ATTESTATION_INVALID, "attestation binds different bytes")
    if attestation.response is not HumanResponse.USE_THIS:
        return Refusal(RefusalCode.HUMAN_ATTESTATION_INVALID, "only Use this authorizes the effect")
    return None


def verify_effect_receipt(
    *,
    authorized: AuthorizedEffect,
    receipt: EffectReceipt,
    operation: RegisteredOperation,
) -> Refusal | None:
    """Verify that the affected system supplied the receipt required by the operation."""

    if (
        receipt.authorization_id != authorized.authorization_id
        or receipt.decision_id != authorized.decision_id
        or receipt.decision_revision != authorized.decision_revision
        or receipt.operation != authorized.operation
        or receipt.operation_version != authorized.operation_version
        or receipt.request_digest != authorized.request_digest
        or operation.operation != authorized.operation
        or operation.operation_version != authorized.operation_version
        or operation.digest != authorized.operation_contract_digest
    ):
        return Refusal(RefusalCode.EFFECT_RECEIPT_INVALID, "receipt binds a different effect")
    if receipt.status is not EffectStatus.APPLIED:
        return Refusal(RefusalCode.EFFECT_RECEIPT_INVALID, "receipt does not prove application")
    if operation.requires_external_confirmation and not receipt.external_confirmation_ref:
        return Refusal(
            RefusalCode.EXTERNAL_CONFIRMATION_MISSING,
            "outward effect lacks confirmation from the affected system",
        )
    return None
