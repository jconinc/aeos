"""The bounded, evidence- and authority-gated AEOS decision compiler."""

from __future__ import annotations

from dataclasses import dataclass

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate, ModelDecision, Recommendation, candidate_set_digest
from aeos_kernel.errors import Refusal, RefusalCode
from aeos_kernel.evidence import DecisionPacket
from aeos_kernel.ports import Clock, ModelChoiceRequest, ModelGateway, TrustVerifier
from aeos_kernel.verification import (
    eligible_candidates,
    highest_authority_candidates,
    validated_entailed,
    verify_packet,
)
from aeos_kernel.vocabulary import DecisionStatus


@dataclass(frozen=True, slots=True)
class DecisionEngine:
    verifier: TrustVerifier
    clock: Clock
    model_gateway: ModelGateway | None = None
    minimum_model_confidence: float = 0.75

    def decide(self, packet: DecisionPacket, candidates: tuple[Candidate, ...]) -> Recommendation:
        ordered = tuple(sorted(candidates, key=lambda item: item.candidate_id))
        set_digest = candidate_set_digest(ordered)
        decision_id = (
            "decision_"
            + stable_fingerprint(
                {"packet_digest": packet.packet_digest, "candidate_set_digest": set_digest}
            )[:24]
        )
        if len({candidate.candidate_id for candidate in ordered}) != len(ordered):
            return self._refused(
                decision_id,
                packet,
                set_digest,
                RefusalCode.INVALID_PACKET,
                "candidate IDs are not unique",
            )
        packet_refusal = verify_packet(packet, verifier=self.verifier, now=self.clock.now())
        if packet_refusal is not None:
            return self._refusal(decision_id, packet, set_digest, packet_refusal)

        eligible, rejected = eligible_candidates(ordered, packet)
        if not eligible:
            detail = "; ".join(f"{key}: {value}" for key, value in sorted(rejected.items()))
            return self._refused(
                decision_id,
                packet,
                set_digest,
                RefusalCode.NO_ELIGIBLE_CANDIDATE,
                detail or "no candidate was provided",
            )
        entailed = tuple(
            candidate for candidate in eligible if validated_entailed(candidate, packet)
        )
        top_entailed = highest_authority_candidates(entailed)
        if len(top_entailed) == 1:
            return self._selected(
                decision_id,
                packet,
                set_digest,
                top_entailed[0],
                ordered,
                selection_mode="auto_entailed",
            )
        if len(top_entailed) > 1:
            return self._refused(
                decision_id,
                packet,
                set_digest,
                RefusalCode.AMBIGUOUS_ENTAILMENT,
                "multiple candidates are independently entailed at the highest authority tier",
            )
        if not packet.policy.permits_model_choice:
            code = (
                RefusalCode.HUMAN_REQUIRED
                if packet.policy.level.value == "human_required"
                else RefusalCode.MODEL_REQUIRED
            )
            status = (
                DecisionStatus.HUMAN_REQUIRED
                if code is RefusalCode.HUMAN_REQUIRED
                else DecisionStatus.REFUSED
            )
            return self._refused(
                decision_id,
                packet,
                set_digest,
                code,
                "eligible choices exist but no authority may select among them",
                status=status,
            )
        model_pool = highest_authority_candidates(eligible)
        return self._model_selected(decision_id, packet, set_digest, model_pool, ordered)

    def _model_selected(
        self,
        decision_id: str,
        packet: DecisionPacket,
        set_digest: str,
        eligible: tuple[Candidate, ...],
        all_candidates: tuple[Candidate, ...],
    ) -> Recommendation:
        if self.model_gateway is None:
            return self._refused(
                decision_id,
                packet,
                set_digest,
                RefusalCode.MODEL_REQUIRED,
                "policy permits a bounded model choice but no model gateway is configured",
            )
        required_calls = 2 if len(eligible) > 1 else 1
        if packet.policy.max_model_calls < required_calls:
            return self._refused(
                decision_id,
                packet,
                set_digest,
                RefusalCode.MODEL_BUDGET_EXCEEDED,
                "model choice requires "
                f"{required_calls} call(s), policy permits {packet.policy.max_model_calls}",
            )
        first_request = self._model_request(
            packet,
            eligible,
            set_digest=set_digest,
            candidate_order=tuple(item.candidate_id for item in eligible),
            attempt=1,
            cost_ceiling_minor_units=packet.policy.max_model_cost_minor_units,
        )
        first = self.model_gateway.choose(first_request)
        rejection = self._validate_model_decision(first, eligible, packet, request=first_request)
        if rejection is not None:
            return self._refusal(decision_id, packet, set_digest, rejection)
        calls = [first]
        if len(eligible) > 1:
            remaining_cost = (
                packet.policy.max_model_cost_minor_units - first.identity.cost_minor_units
            )
            second_request = self._model_request(
                packet,
                eligible,
                set_digest=set_digest,
                candidate_order=tuple(item.candidate_id for item in reversed(eligible)),
                attempt=2,
                cost_ceiling_minor_units=remaining_cost,
            )
            second = self.model_gateway.choose(second_request)
            rejection = self._validate_model_decision(
                second,
                eligible,
                packet,
                request=second_request,
            )
            if rejection is not None:
                return self._refusal(
                    decision_id, packet, set_digest, rejection, model_calls=tuple(calls)
                )
            calls.append(second)
            if second.candidate_id != first.candidate_id:
                return self._refused(
                    decision_id,
                    packet,
                    set_digest,
                    RefusalCode.MODEL_DISAGREEMENT,
                    "model selection changed when candidate order was reversed",
                    model_calls=tuple(calls),
                )
        cost = sum(call.identity.cost_minor_units for call in calls)
        if cost > packet.policy.max_model_cost_minor_units:
            return self._refused(
                decision_id,
                packet,
                set_digest,
                RefusalCode.MODEL_BUDGET_EXCEEDED,
                "validated model calls exceeded the declared cost ceiling",
                model_calls=tuple(calls),
            )
        chosen = next(item for item in eligible if item.candidate_id == first.candidate_id)
        return self._selected(
            decision_id,
            packet,
            set_digest,
            chosen,
            all_candidates,
            selection_mode="model_eligible",
            model_calls=tuple(calls),
            model_rationale=first.rationale,
        )

    @staticmethod
    def _model_request(
        packet: DecisionPacket,
        eligible: tuple[Candidate, ...],
        *,
        set_digest: str,
        candidate_order: tuple[str, ...],
        attempt: int,
        cost_ceiling_minor_units: int,
    ) -> ModelChoiceRequest:
        prompt_digest = stable_fingerprint(
            {
                "contract": "aeos.model-choice@2",
                "packet_digest": packet.packet_digest,
                "candidate_set_digest": set_digest,
                "candidate_order": list(candidate_order),
                "attempt": attempt,
                "context_classification": packet.policy.model_context_classification,
            }
        )
        return ModelChoiceRequest(
            packet=packet,
            candidates=eligible,
            candidate_order=candidate_order,
            attempt=attempt,
            provider=packet.policy.model_provider,
            model_id=packet.policy.model_id,
            prompt_digest=prompt_digest,
            generation_parameters_digest=packet.policy.model_generation_parameters_digest,
            context_classification=packet.policy.model_context_classification,
            cost_ceiling_minor_units=cost_ceiling_minor_units,
        )

    def _validate_model_decision(
        self,
        result: ModelDecision,
        eligible: tuple[Candidate, ...],
        packet: DecisionPacket,
        *,
        request: ModelChoiceRequest,
    ) -> Refusal | None:
        allowed = {candidate.candidate_id: candidate for candidate in eligible}
        identity = result.identity
        if (
            identity.attempt != request.attempt
            or identity.provider != request.provider
            or identity.model_id != request.model_id
            or identity.prompt_digest != request.prompt_digest
            or identity.generation_parameters_digest != request.generation_parameters_digest
            or identity.context_classification != request.context_classification
        ):
            return Refusal(RefusalCode.MODEL_INVALID, "model call identity is not authorized")
        if identity.cost_minor_units > request.cost_ceiling_minor_units:
            return Refusal(RefusalCode.MODEL_BUDGET_EXCEEDED, "model call exceeded its reservation")
        if result.candidate_id not in allowed:
            return Refusal(
                RefusalCode.MODEL_INVALID, "model invented or selected an ineligible candidate"
            )
        if result.confidence < self.minimum_model_confidence:
            return Refusal(
                RefusalCode.MODEL_INVALID, "model confidence is below the configured threshold"
            )
        evidence_ids = {item.evidence_id for item in packet.evidence}
        if not set(result.citations) <= evidence_ids:
            return Refusal(RefusalCode.MODEL_INVALID, "model cited evidence outside the packet")
        chosen = allowed[result.candidate_id]
        if not set(chosen.proof.cited_evidence_ids) <= set(result.citations):
            return Refusal(
                RefusalCode.MODEL_INVALID, "model citations do not cover the candidate proof"
            )
        return None

    @staticmethod
    def _selected(
        decision_id: str,
        packet: DecisionPacket,
        set_digest: str,
        selected: Candidate,
        all_candidates: tuple[Candidate, ...],
        *,
        selection_mode: str,
        model_calls: tuple[ModelDecision, ...] = (),
        model_rationale: str = "",
    ) -> Recommendation:
        explanation = selected.explanation
        if model_rationale:
            explanation = f"{explanation} {model_rationale}".strip()
        return Recommendation(
            decision_id=decision_id,
            decision_revision=1,
            status=DecisionStatus.PROPOSED,
            packet_digest=packet.packet_digest,
            candidate_set_digest=set_digest,
            selected_candidate_id=selected.candidate_id,
            selection_mode=selection_mode,
            explanation=explanation,
            evidence_ids=selected.proof.cited_evidence_ids,
            rejected_alternatives=tuple(
                candidate.candidate_id
                for candidate in all_candidates
                if candidate.candidate_id != selected.candidate_id
            ),
            model_calls=tuple(call.identity for call in model_calls),
            model_outputs=tuple(dict(call.retained_output) for call in model_calls),
        )

    @classmethod
    def _refused(
        cls,
        decision_id: str,
        packet: DecisionPacket,
        set_digest: str,
        code: RefusalCode,
        reason: str,
        *,
        status: DecisionStatus = DecisionStatus.REFUSED,
        model_calls: tuple[ModelDecision, ...] = (),
    ) -> Recommendation:
        return cls._refusal(
            decision_id,
            packet,
            set_digest,
            Refusal(code, reason),
            status=status,
            model_calls=model_calls,
        )

    @staticmethod
    def _refusal(
        decision_id: str,
        packet: DecisionPacket,
        set_digest: str,
        refusal: Refusal,
        *,
        status: DecisionStatus = DecisionStatus.REFUSED,
        model_calls: tuple[ModelDecision, ...] = (),
    ) -> Recommendation:
        return Recommendation(
            decision_id=decision_id,
            decision_revision=1,
            status=status,
            packet_digest=packet.packet_digest,
            candidate_set_digest=set_digest,
            refusal=refusal,
            model_calls=tuple(call.identity for call in model_calls),
            model_outputs=tuple(dict(call.retained_output) for call in model_calls),
        )
