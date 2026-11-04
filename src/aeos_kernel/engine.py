"""The bounded, evidence- and authority-gated AEOS decision compiler."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import (
    Candidate,
    ModelDecision,
    ModelReview,
    ModelReviewIssue,
    Recommendation,
    candidate_set_digest,
)
from aeos_kernel.errors import Refusal, RefusalCode
from aeos_kernel.evidence import DecisionPacket
from aeos_kernel.ports import (
    Clock,
    ModelChoiceRequest,
    ModelGateway,
    ModelReviewGateway,
    ModelReviewRequest,
    TrustVerifier,
)
from aeos_kernel.principles import PrincipleResult, apply_principles
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
    review_gateway: ModelReviewGateway | None = None

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
        principled = apply_principles(packet, eligible)
        if isinstance(principled, Refusal):
            return self._refusal(decision_id, packet, set_digest, principled)
        eligible = principled.pool
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
                principled=principled,
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
        return self._model_selected(
            decision_id, packet, set_digest, model_pool, ordered, principled
        )

    def _model_selected(
        self,
        decision_id: str,
        packet: DecisionPacket,
        set_digest: str,
        eligible: tuple[Candidate, ...],
        all_candidates: tuple[Candidate, ...],
        principled: PrincipleResult,
    ) -> Recommendation:
        if self.model_gateway is None:
            return self._refused(
                decision_id,
                packet,
                set_digest,
                RefusalCode.MODEL_REQUIRED,
                "policy permits a bounded model choice but no model gateway is configured",
            )
        if packet.policy.require_model_review:
            return self._reviewed_selected(
                decision_id, packet, set_digest, eligible, all_candidates, principled
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
            principled=principled,
        )
        first = self.model_gateway.choose(first_request)
        rejection = self._validate_model_decision(first, eligible, packet, request=first_request)
        if rejection is not None:
            return self._refusal(decision_id, packet, set_digest, rejection)
        if first.escalation is not None:
            return self._escalated(decision_id, packet, set_digest, (first,))
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
                principled=principled,
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
            if second.escalation is not None:
                return self._escalated(decision_id, packet, set_digest, (first, second))
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
            principled=principled,
        )

    def _reviewed_selected(
        self,
        decision_id: str,
        packet: DecisionPacket,
        set_digest: str,
        eligible: tuple[Candidate, ...],
        all_candidates: tuple[Candidate, ...],
        principled: PrincipleResult,
    ) -> Recommendation:
        if self.review_gateway is None or self.model_gateway is None:
            return self._refused(
                decision_id,
                packet,
                set_digest,
                RefusalCode.MODEL_REQUIRED,
                "reviewed choice requires chooser and review gateways",
            )
        calls: list[ModelDecision | ModelReview] = []
        purposes: list[str] = []
        digests: list[str] = []

        def attach(result: Recommendation) -> Recommendation:
            return replace(
                result,
                model_calls=tuple(c.identity for c in calls),
                model_outputs=tuple(dict(c.retained_output) for c in calls),
                model_protocol_version="aeos.reviewed-choice@1",
                model_call_purposes=tuple(purposes),
                model_request_digests=tuple(digests),
            )

        def refuse(refusal: Refusal) -> Recommendation:
            return attach(self._refusal(decision_id, packet, set_digest, refusal))

        issues: tuple[ModelReviewIssue, ...] = ()
        for round_index in range(2):
            # A phase is useful only if its pair and mandatory review can all fit.
            if len(calls) + 3 > packet.policy.max_model_calls:
                return refuse(
                    Refusal(
                        RefusalCode.MODEL_BUDGET_EXCEEDED,
                        "remaining budget cannot cover a complete review phase",
                    )
                )
            stale = verify_packet(packet, verifier=self.verifier, now=self.clock.now())
            if stale is not None:
                return refuse(stale)
            pair: list[ModelDecision] = []
            for offset in range(2):
                stale = verify_packet(packet, verifier=self.verifier, now=self.clock.now())
                if stale is not None:
                    return refuse(stale)
                remaining = packet.policy.max_model_cost_minor_units - sum(
                    c.identity.cost_minor_units for c in calls
                )
                request = self._model_request(
                    packet,
                    eligible,
                    set_digest=set_digest,
                    candidate_order=tuple(
                        c.candidate_id for c in (eligible if offset == 0 else reversed(eligible))
                    ),
                    attempt=round_index * 3 + offset + 1,
                    cost_ceiling_minor_units=remaining,
                    principled=principled,
                    correction_issues=issues,
                )
                result = self.model_gateway.choose(request)
                calls.append(result)
                purposes.append("choose")
                digests.append(request.prompt_digest)
                rejection = self._validate_model_decision(result, eligible, packet, request=request)
                if rejection is not None:
                    return refuse(rejection)
                if result.escalation is not None:
                    return refuse(
                        Refusal(
                            result.escalation,
                            "the model named a missing premise instead of choosing",
                            result.missing_premise,
                        )
                    )
                pair.append(result)
            if pair[0].candidate_id != pair[1].candidate_id:
                return refuse(
                    Refusal(
                        RefusalCode.MODEL_DISAGREEMENT,
                        "model selection changed when candidate order was reversed",
                    )
                )
            stale = verify_packet(packet, verifier=self.verifier, now=self.clock.now())
            if stale is not None:
                return refuse(stale)
            attempt = round_index * 3 + 3
            refs = tuple(item.evidence_id for item in packet.evidence)
            order = tuple(item.candidate_id for item in all_candidates)
            data = {
                "contract": "aeos.model-review@1",
                "purpose": "review",
                "attempt": attempt,
                "packet_digest": packet.packet_digest,
                "candidate_set_digest": set_digest,
                "candidate_order": list(order),
                "proposed_candidate_id": pair[0].candidate_id,
                "proposed_citations": list(pair[0].citations),
                "principles": [asdict(p) for p in principled.all_principles],
                "deterministic_rule_results": [list(row) for row in principled.rule_results],
                "allowed_fact_refs": list(refs),
                "context_classification": packet.policy.model_context_classification,
            }
            request_review = ModelReviewRequest(
                packet=packet,
                candidates=all_candidates,
                candidate_order=order,
                principles=principled.all_principles,
                deterministic_rule_results=principled.rule_results,
                proposed_candidate_id=pair[0].candidate_id,
                proposed_citations=pair[0].citations,
                allowed_fact_refs=refs,
                contract_version="aeos.model-review@1",
                attempt=attempt,
                provider=packet.policy.model_provider,
                model_id=packet.policy.model_id,
                prompt_digest=stable_fingerprint(data),
                generation_parameters_digest=packet.policy.model_generation_parameters_digest,
                context_classification=packet.policy.model_context_classification,
                cost_ceiling_minor_units=packet.policy.max_model_cost_minor_units
                - sum(c.identity.cost_minor_units for c in calls),
            )
            review = self.review_gateway.review(request_review)
            calls.append(review)
            purposes.append("review")
            digests.append(request_review.prompt_digest)
            invalid = self._validate_review(review, request_review)
            if invalid is not None:
                return refuse(invalid)
            if review.verdict in {"missing_fact", "missing_principle"}:
                return refuse(
                    Refusal(
                        RefusalCode(review.verdict),
                        "the reviewer named a missing premise",
                        review.missing_premise or "",
                    )
                )
            if review.verdict == "correct":
                if round_index:
                    return refuse(
                        Refusal(
                            RefusalCode.MODEL_INVALID, "final review requires further correction"
                        )
                    )
                issues = review.issues
                continue
            stale = verify_packet(packet, verifier=self.verifier, now=self.clock.now())
            if stale is not None:
                return refuse(stale)
            selected = next(c for c in eligible if c.candidate_id == pair[0].candidate_id)
            return attach(
                self._selected(
                    decision_id,
                    packet,
                    set_digest,
                    selected,
                    all_candidates,
                    selection_mode="model_eligible",
                    model_rationale=pair[0].rationale,
                    principled=principled,
                )
            )
        raise AssertionError("review protocol exhausted unexpectedly")

    @staticmethod
    def _validate_review(result: ModelReview, request: ModelReviewRequest) -> Refusal | None:
        identity = result.identity
        if (
            identity.attempt != request.attempt
            or identity.provider != request.provider
            or identity.model_id != request.model_id
            or identity.prompt_digest != request.prompt_digest
            or identity.generation_parameters_digest != request.generation_parameters_digest
            or identity.context_classification != request.context_classification
        ):
            return Refusal(RefusalCode.MODEL_INVALID, "review call identity is not authorized")
        if identity.cost_minor_units > request.cost_ceiling_minor_units:
            return Refusal(RefusalCode.MODEL_BUDGET_EXCEEDED, "review exceeded its reservation")
        expected = {
            "verdict": result.verdict,
            "issues": [{**asdict(i), "fact_refs": list(i.fact_refs)} for i in result.issues],
            "missing_premise": result.missing_premise,
        }
        if dict(result.retained_output) != expected:
            return Refusal(
                RefusalCode.MODEL_INVALID, "review output does not match its typed result"
            )
        if result.verdict not in {"accept", "correct", "missing_fact", "missing_principle"}:
            return Refusal(RefusalCode.MODEL_INVALID, "unknown review verdict")
        if len(result.issues) > 16:
            return Refusal(RefusalCode.MODEL_INVALID, "too many review issues")
        if result.verdict == "accept" and (result.issues or result.missing_premise is not None):
            return Refusal(RefusalCode.MODEL_INVALID, "accept cannot contain unresolved issues")
        if result.verdict == "correct" and (
            not result.issues or result.missing_premise is not None
        ):
            return Refusal(RefusalCode.MODEL_INVALID, "correction requires concrete issues")
        if result.verdict in {"missing_fact", "missing_principle"} and (
            result.issues
            or not isinstance(result.missing_premise, str)
            or not result.missing_premise.strip()
            or len(result.missing_premise) > 300
        ):
            return Refusal(
                RefusalCode.MODEL_INVALID, "missing premise must be specific and unaccompanied"
            )
        seen: set[tuple[str, str, str]] = set()
        for issue in result.issues:
            key = (issue.principle_id, issue.candidate_id, issue.code)
            if (
                issue.code
                not in {
                    "rule_conflict",
                    "unsupported_fact",
                    "wrong_remedy",
                    "missed_alternative",
                    "scope_mismatch",
                    "authority_overreach",
                }
                or issue.principle_id not in {p.principle_id for p in request.principles}
                or issue.candidate_id not in request.candidate_order
                or not 1 <= len(issue.fact_refs) <= 16
                or not set(issue.fact_refs) <= set(request.allowed_fact_refs)
                or len(set(issue.fact_refs)) != len(issue.fact_refs)
                or not issue.explanation.strip()
                or len(issue.explanation) > 300
                or key in seen
            ):
                return Refusal(RefusalCode.MODEL_INVALID, "review issue is invalid or ungrounded")
            seen.add(key)
        return None

    @classmethod
    def _escalated(
        cls,
        decision_id: str,
        packet: DecisionPacket,
        set_digest: str,
        calls: tuple[ModelDecision, ...],
    ) -> Recommendation:
        named = calls[-1]
        assert named.escalation is not None
        return cls._refusal(
            decision_id,
            packet,
            set_digest,
            Refusal(
                named.escalation,
                "the model named a missing premise instead of choosing",
                named.missing_premise,
            ),
            model_calls=calls,
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
        principled: PrincipleResult,
        correction_issues: tuple[ModelReviewIssue, ...] = (),
    ) -> ModelChoiceRequest:
        contract = "aeos.model-choice@3" if principled.evidence_ids else "aeos.model-choice@2"
        prompt_data = {
            "contract": contract,
            "packet_digest": packet.packet_digest,
            "candidate_set_digest": set_digest,
            "candidate_order": list(candidate_order),
            "attempt": attempt,
            "context_classification": packet.policy.model_context_classification,
        }
        if packet.policy.require_model_review:
            prompt_data["contract"] = "aeos.reviewed-choice@1"
            prompt_data["purpose"] = "choose"
            prompt_data["correction_issues"] = [
                {**asdict(issue), "fact_refs": list(issue.fact_refs)} for issue in correction_issues
            ]
        prompt_digest = stable_fingerprint(prompt_data)
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
            principles=principled.judge,
            conflict_order=principled.conflict_order,
            correction_issues=correction_issues,
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
        if result.escalation is not None:
            return None
        named = set(result.principle_ids)
        in_force = {brief.principle_id for brief in request.principles}
        if not named <= in_force:
            return Refusal(
                RefusalCode.MODEL_INVALID, "model named a principle that is not in force"
            )
        if in_force and not named:
            return Refusal(
                RefusalCode.MODEL_INVALID, "model did not name the principles it applied"
            )
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
        principled: PrincipleResult | None = None,
    ) -> Recommendation:
        explanation = selected.explanation
        if model_rationale:
            explanation = f"{explanation} {model_rationale}".strip()
        evidence_ids = selected.proof.cited_evidence_ids
        if principled is not None and principled.evidence_ids:
            evidence_ids = tuple(dict.fromkeys((*evidence_ids, *principled.evidence_ids)))
            if principled.ruled_out:
                ruled = "; ".join(
                    f"{key} ({value})" for key, value in sorted(principled.ruled_out.items())
                )
                explanation = f"{explanation} Ruled out by principles: {ruled}."
        return Recommendation(
            decision_id=decision_id,
            decision_revision=1,
            status=DecisionStatus.PROPOSED,
            packet_digest=packet.packet_digest,
            candidate_set_digest=set_digest,
            selected_candidate_id=selected.candidate_id,
            selection_mode=selection_mode,
            explanation=explanation,
            evidence_ids=evidence_ids,
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
