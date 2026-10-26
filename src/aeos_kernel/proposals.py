"""Bounded proposal review; hosts retain content, authority, calls and durable outcomes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from aeos_kernel._validation import digest as require_digest
from aeos_kernel._validation import required
from aeos_kernel.evidence import DecisionSubject
from aeos_kernel.ports import TrustVerifier


@dataclass(frozen=True, slots=True)
class ProposalCall[P]:
    proposal: P
    call_ref: str


@dataclass(frozen=True, slots=True)
class ProposalDefect:
    code: str
    detail: str
    repairable: bool = False


@dataclass(frozen=True, slots=True)
class ValidatedProposal[P]:
    proposal: P
    digest: str
    safe_output_ref: str
    change_evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposalObjection:
    issue_codes: tuple[str, ...]
    offending_claim: str
    supporting_evidence: tuple[str, ...]
    resolution_condition: str

    def supported(self) -> bool:
        return bool(self.issue_codes and all(self.issue_codes) and self.offending_claim.strip()
                    and self.supporting_evidence and all(self.supporting_evidence)
                    and self.resolution_condition.strip())


@dataclass(frozen=True, slots=True)
class CorrectionContext[P]:
    rejected_proposal: P | None
    rejected_digest: str | None
    verdict: str
    defect: ProposalDefect | None
    objection: ProposalObjection | None
    reviewed_digest: str | None
    call_ref: str


@dataclass(frozen=True, slots=True)
class ProposalReview[R]:
    review: R
    verdict: Literal["pass", "decline", "abstain"]
    reviewed_digest: str
    call_ref: str
    evidence: tuple[str, ...]
    objection: ProposalObjection | None = None
    repairable: bool = False
    correction_resolution: str = ""


@dataclass(frozen=True, slots=True)
class ProposalAttempt:
    stage: Literal["author", "review"]
    outcome: str
    call_ref: str | None
    proposal_digest: str | None = None
    safe_output_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalResult[P, R]:
    status: Literal["review_passed", "refused"]
    reason: str
    proposal: P | None
    review: R | None
    attempts: tuple[ProposalAttempt, ...]
    correction_count: int
    correction: CorrectionContext[P] | None = None


class ProposalCallFailure(Exception):
    """A host-classified call failure, including a reservation ref when one exists."""

    def __init__(self, reason: str, call_ref: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.call_ref = call_ref


def run_proposal_review[P, R](
    *,
    subject: DecisionSubject,
    source_head_pins: dict[str, str],
    context_digest: str,
    proposal_contract_version: str,
    verifier: TrustVerifier,
    author: Callable[[CorrectionContext[P] | None], ProposalCall[P]],
    validate: Callable[[P, CorrectionContext[P] | None], ValidatedProposal[P] | ProposalDefect],
    review: Callable[[P, str, CorrectionContext[P] | None], ProposalReview[R]],
) -> ProposalResult[P, R]:
    """Run at most two author and two reviewer callbacks, with one specific correction.

    Each model callback must dispatch at most one call and persist its native result before
    returning. This function's counters do not replace the host's cross-invocation hold.
    Unexpected infrastructure exceptions propagate; they are never interpreted as a decline.
    """
    require_digest(context_digest, "context_digest")
    required(proposal_contract_version, "proposal_contract_version")
    if not source_head_pins or any(not key or not value for key, value in source_head_pins.items()):
        raise ValueError("source_head_pins must be nonempty")
    source_head_pins = dict(source_head_pins)
    attempts: list[ProposalAttempt] = []
    correction: CorrectionContext[P] | None = None
    call_refs: set[str] = set()
    authors = reviewers = 0

    def refused(reason: str) -> ProposalResult[P, R]:
        return ProposalResult("refused", reason, None, None, tuple(attempts),
                              int(correction is not None), correction)

    def current() -> bool:
        return (verifier.verify_source_heads(source_head_pins)
                and verifier.current_subject_revision(subject) == subject.revision)

    if not current():
        return refused("source_changed")
    while authors < 2 and len(attempts) < 4:
        authors += 1  # Count dispatch before entering host code, including failures.
        attempts.append(ProposalAttempt("author", "started", None))
        try:
            authored = author(correction)
        except ProposalCallFailure as exc:
            attempts[-1] = ProposalAttempt("author", exc.reason, exc.call_ref)
            return refused(exc.reason)
        if not authored.call_ref or authored.call_ref in call_refs:
            attempts[-1] = ProposalAttempt("author", "invalid_call_reference", authored.call_ref)
            return refused("invalid_call_reference")
        call_refs.add(authored.call_ref)
        checked = validate(authored.proposal, correction)
        if isinstance(checked, ProposalDefect):
            attempts[-1] = ProposalAttempt("author", checked.code, authored.call_ref)
            if not checked.repairable or correction is not None:
                return refused(checked.code)
            correction = CorrectionContext(None, None, "validation_defect", checked, None,
                                           None, authored.call_ref)
            continue
        require_digest(checked.digest, "proposal digest")
        required(checked.safe_output_ref, "safe_output_ref")
        attempts[-1] = ProposalAttempt("author", "validated", authored.call_ref,
                                      checked.digest, checked.safe_output_ref)
        if correction is not None and not checked.change_evidence:
            return refused("correction_unproved")
        if reviewers >= 2 or len(attempts) >= 4:
            return refused("attempt_limit")
        reviewers += 1
        attempts.append(ProposalAttempt("review", "started", None, checked.digest,
                                        checked.safe_output_ref))
        try:
            reviewed = review(checked.proposal, checked.digest, correction)
        except ProposalCallFailure as exc:
            attempts[-1] = ProposalAttempt("review", exc.reason, exc.call_ref, checked.digest,
                                          checked.safe_output_ref)
            return refused(exc.reason)
        attempts[-1] = ProposalAttempt("review", reviewed.verdict, reviewed.call_ref,
                                      checked.digest, checked.safe_output_ref)
        if not reviewed.call_ref or reviewed.call_ref in call_refs:
            return refused("invalid_call_reference")
        call_refs.add(reviewed.call_ref)
        if reviewed.reviewed_digest != checked.digest:
            return refused("review_digest_mismatch")
        if reviewed.verdict == "abstain":
            return refused("review_abstained")
        if reviewed.verdict == "pass":
            if not reviewed.evidence or not all(item.strip() for item in reviewed.evidence):
                return refused("unsupported_pass")
            if correction is not None and not reviewed.correction_resolution.strip():
                return refused("correction_unproved")
            if not current():
                return refused("source_changed")
            return ProposalResult("review_passed", "review_passed", checked.proposal,
                                  reviewed.review, tuple(attempts), int(correction is not None),
                                  correction)
        if reviewed.verdict != "decline":
            return refused("invalid_review")
        objection = reviewed.objection
        if objection is None or not objection.supported():
            return refused("unsupported_objection")
        if correction is not None or not reviewed.repairable:
            return refused("review_declined")
        correction = CorrectionContext(checked.proposal, checked.digest, "decline", None,
                                       objection, reviewed.reviewed_digest, reviewed.call_ref)
    return refused("attempt_limit")
