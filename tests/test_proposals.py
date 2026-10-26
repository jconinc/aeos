"""Revision 4 §3.3 / AC-05: bounded callbacks and exact correction evidence."""

from dataclasses import replace

import pytest

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.evidence import DecisionSubject, SourceRef
from aeos_kernel.proposals import (
    CorrectionContext,
    ProposalCall,
    ProposalCallFailure,
    ProposalDefect,
    ProposalObjection,
    ProposalReview,
    ValidatedProposal,
    run_proposal_review,
)

DIGEST = stable_fingerprint("source")
SUBJECT = DecisionSubject("test", "tenant", "answer", "return", "1", DIGEST,
                          source_refs=(SourceRef("test", "return", "1", DIGEST),))
OBJECTION = ProposalObjection(("fidelity",), "Capacity is 10", ("Source says 5",),
                              "Correct capacity to 5")


class Verifier:
    current = True

    def verify_source_heads(self, pins: dict[str, str]) -> bool:
        return self.current and pins == {"source": DIGEST}

    def current_subject_revision(self, subject: DecisionSubject) -> str | None:
        return subject.revision if self.current else None

    def verify_authority_bundle(self, digest: str) -> bool:
        return True

    def verify_research_receipt(self, evidence: object) -> bool:
        return True


class Host:
    def __init__(self) -> None:
        self.verifier = Verifier()
        self.contexts: list[tuple[str, CorrectionContext[str] | None]] = []
        self.verdicts = ["pass", "pass"]
        self.authors = self.reviewers = 0
        self.defect: ProposalDefect | None = None
        self.change = ("Capacity changed from 10 to 5",)

    def author(self, correction: CorrectionContext[str] | None) -> ProposalCall[str]:
        self.contexts.append(("author", correction))
        self.authors += 1
        return ProposalCall("Capacity is 10" if self.authors == 1 else "Capacity is 5",
                            f"author-{self.authors}")

    def validate(self, proposal: str, correction: CorrectionContext[str] | None
                 ) -> ValidatedProposal[str] | ProposalDefect:
        self.contexts.append(("validate", correction))
        if self.defect is not None:
            defect, self.defect = self.defect, None
            return defect
        return ValidatedProposal(proposal, stable_fingerprint(proposal), "native-safe-ref",
                                 self.change if correction else ())

    def review(self, proposal: str, digest: str, correction: CorrectionContext[str] | None
               ) -> ProposalReview[str]:
        self.contexts.append(("review", correction))
        verdict = self.verdicts[self.reviewers]
        self.reviewers += 1
        return ProposalReview("native review", verdict, digest, f"review-{self.reviewers}",
                              ("Compared to source",), OBJECTION, True,
                              "Capacity now agrees with source" if correction else "")  # type: ignore[arg-type]

    def run(self):  # type: ignore[no-untyped-def]
        return run_proposal_review(
            subject=SUBJECT, source_head_pins={"source": DIGEST}, context_digest=DIGEST,
            proposal_contract_version="1", verifier=self.verifier, author=self.author,
            validate=self.validate, review=self.review)


def test_success_preserves_native_references_and_safe_output() -> None:
    host = Host()
    result = host.run()
    assert result.status == "review_passed"
    assert result.proposal == "Capacity is 10"
    assert [item.call_ref for item in result.attempts] == ["author-1", "review-1"]
    assert result.attempts[0].safe_output_ref == "native-safe-ref"
    assert result.correction_count == 0


def test_supported_decline_passes_same_full_context_to_all_correction_callbacks() -> None:
    host = Host()
    host.verdicts = ["decline", "pass"]
    result = host.run()
    correction = result.correction
    assert result.status == "review_passed" and result.correction_count == 1
    assert correction and correction.rejected_proposal == "Capacity is 10"
    assert correction.objection == OBJECTION
    assert all(context is correction for _, context in host.contexts[3:])
    assert host.authors == host.reviewers == 2 and len(result.attempts) == 4


def test_repeated_decline_is_terminal_at_four_callbacks() -> None:
    host = Host()
    host.verdicts = ["decline", "decline"]
    assert host.run().reason == "review_declined"
    assert host.authors == host.reviewers == 2


@pytest.mark.parametrize("verdict,reason", [("abstain", "review_abstained"),
                                           ("broken", "invalid_review")])
def test_uncertainty_and_malformed_review_do_not_open_correction(verdict: str, reason: str) -> None:
    host = Host()
    host.verdicts = [verdict]
    assert host.run().reason == reason
    assert host.authors == host.reviewers == 1


def test_deterministic_defect_never_retains_unsafe_proposal() -> None:
    host = Host()
    host.defect = ProposalDefect("body_shape", "body must be a nonempty string", True)
    result = host.run()
    assert result.status == "review_passed"
    assert result.correction and result.correction.rejected_proposal is None
    assert result.correction.rejected_digest is None
    assert result.correction.call_ref == "author-1"
    assert result.correction.defect and result.correction.defect.code == "body_shape"
    assert host.authors == 2 and host.reviewers == 1


def test_hard_constraint_stops_without_review() -> None:
    host = Host()
    host.defect = ProposalDefect("forbidden_data", "Privacy check failed")
    assert host.run().reason == "forbidden_data"
    assert host.authors == 1 and host.reviewers == 0


def test_cosmetic_change_without_defect_specific_evidence_stops_before_second_review() -> None:
    host = Host()
    host.verdicts = ["decline", "pass"]
    host.change = ()
    assert host.run().reason == "correction_unproved"
    assert host.authors == 2 and host.reviewers == 1


@pytest.mark.parametrize("mutation,reason", [
    ({"reviewed_digest": DIGEST}, "review_digest_mismatch"),
    ({"call_ref": "author-1"}, "invalid_call_reference"),
    ({"evidence": ()}, "unsupported_pass"),
    ({"verdict": "decline", "objection": None}, "unsupported_objection"),
])
def test_unbound_or_unsupported_review_refuses(mutation: dict[str, object], reason: str) -> None:
    host = Host()
    original = host.review
    host.review = lambda *args: replace(original(*args), **mutation)  # type: ignore[assignment,arg-type]
    assert host.run().reason == reason
    assert host.authors == 1


def test_unknown_call_outcome_retains_failure_reference_and_never_retries() -> None:
    host = Host()

    def unknown(correction: CorrectionContext[str] | None) -> ProposalCall[str]:
        raise ProposalCallFailure("outcome_unknown", "reservation-uuid")

    host.author = unknown  # type: ignore[method-assign]
    result = host.run()
    assert result.reason == "outcome_unknown"
    assert len(result.attempts) == 1 and result.attempts[0].call_ref == "reservation-uuid"


def test_source_change_before_start_uses_zero_callbacks_and_before_success_refuses() -> None:
    host = Host()
    host.verifier.current = False
    assert host.run().reason == "source_changed" and not host.contexts
    host.verifier.current = True
    original = host.review

    def change_source(*args):  # type: ignore[no-untyped-def]
        host.verifier.current = False
        return original(*args)

    host.review = change_source  # type: ignore[method-assign]
    assert host.run().reason == "source_changed"
