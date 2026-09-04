"""Evidence-ranked fail-closed unique candidate resolution.

Extracted from MultiAgentCommunication ``decision_engine/candidate_resolvers.py`` at
d99002a1903a56b5601d7ec3455e5dfa43028935. Product-specific route, screen, field, and
endpoint projections remain in the WLG adapter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

EVIDENCE_RANK: dict[str, int] = {
    "existing_edge": 60,
    "unique_scalar_ref": 50,
    "same_domain_structural": 40,
    "same_domain_name_match": 30,
    "locale_variant_base": 25,
    "path_token_overlap": 20,
    "name_similarity": 1,
}

INSUFFICIENT_ALONE = frozenset({"name_similarity", "same_domain_name_match"})
PLACEHOLDER_TARGET_IDS = frozenset(
    {"screen", "entity", "parent", "target", "route", "endpoint", "state"}
)


@dataclass(frozen=True, slots=True)
class ResolvedCandidate:
    id: str
    kind: str
    evidence: str
    domain: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    status: str
    candidate: ResolvedCandidate | None = None
    reason: str = ""
    considered: tuple[ResolvedCandidate, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"


def resolve_unique(candidates: Iterable[ResolvedCandidate]) -> ResolutionResult:
    original = tuple(candidates)
    rows = tuple(
        candidate
        for candidate in original
        if candidate.id and candidate.id not in PLACEHOLDER_TARGET_IDS
    )
    if not rows:
        return ResolutionResult(status="declined", reason="no_exact_target", considered=original)
    scored = tuple(
        candidate
        for candidate in rows
        if candidate.evidence not in INSUFFICIENT_ALONE and candidate.evidence in EVIDENCE_RANK
    )
    if not scored:
        return ResolutionResult(status="declined", reason="insufficient_evidence", considered=rows)
    best_rank = max(EVIDENCE_RANK[candidate.evidence] for candidate in scored)
    top = tuple(candidate for candidate in scored if EVIDENCE_RANK[candidate.evidence] == best_rank)
    if len(top) > 1:
        domains = {candidate.domain for candidate in top if candidate.domain}
        reason = "cross_domain_conflict" if len(domains) > 1 else "ambiguous_candidates"
        return ResolutionResult(status="declined", reason=reason, considered=rows)
    return ResolutionResult(status="resolved", candidate=top[0], considered=rows)
