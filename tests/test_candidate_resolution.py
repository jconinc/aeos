from aeos_kernel import ResolvedCandidate, resolve_unique


def row(
    candidate_id: str,
    evidence: str,
    *,
    domain: str = "care",
) -> ResolvedCandidate:
    return ResolvedCandidate(candidate_id, "Screen", evidence, domain)


def test_strictly_dominant_structural_evidence_resolves() -> None:
    result = resolve_unique([row("one", "existing_edge"), row("two", "same_domain_structural")])
    assert result.resolved
    assert result.candidate == row("one", "existing_edge")


def test_name_only_placeholder_zero_and_tied_candidates_decline() -> None:
    assert resolve_unique([row("one", "name_similarity")]).reason == "insufficient_evidence"
    assert resolve_unique([row("screen", "existing_edge")]).reason == "no_exact_target"
    assert (
        resolve_unique(
            [row("one", "same_domain_structural"), row("two", "same_domain_structural")]
        ).reason
        == "ambiguous_candidates"
    )
    assert (
        resolve_unique(
            [
                row("one", "same_domain_structural", domain="care"),
                row("two", "same_domain_structural", domain="practice"),
            ]
        ).reason
        == "cross_domain_conflict"
    )
