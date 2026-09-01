from __future__ import annotations

from datetime import timedelta

from aeos_kernel import (
    AuthorityLayer,
    AuthorityRecord,
    AuthorityStatus,
    ScopeSelector,
    SelectorType,
    resolve_authority,
    selector_matches,
    selector_specificity,
)
from tests.factories import NOW


def test_all_generic_selector_families_have_deterministic_matching_and_specificity() -> None:
    exact = ScopeSelector(SelectorType.EXACT_ATTRIBUTES, {"locale": "en", "kind": "article"})
    path = ScopeSelector(
        SelectorType.PATH_PATTERN_METHOD,
        {"domain": "desk", "method": "GET", "path_glob": "/articles/*", "locale": "en"},
    )
    assert selector_matches(exact, {"locale": "en", "kind": "article"})
    assert not selector_matches(exact, {"locale": "sw", "kind": "article"})
    assert selector_matches(
        path,
        {"domain": "desk", "method": "GET", "path": "/articles/one", "locale": "en"},
    )
    assert not selector_matches(
        path,
        {"domain": "desk", "method": "POST", "path": "/articles/one", "locale": "en"},
    )
    assert selector_specificity(exact) > selector_specificity(
        ScopeSelector(SelectorType.SUBJECT_KIND, {"kind": "article"})
    )
    assert selector_specificity(ScopeSelector("unknown", {})) == (0,)
    assert not selector_matches(ScopeSelector("unknown", {}), {})


def test_future_superseded_and_unconfirmed_rows_do_not_become_authority() -> None:
    base = dict(
        vertical_id="wema",
        tenant_id="wema",
        layer=AuthorityLayer.DESIGN_DECISION,
        selector=ScopeSelector(SelectorType.SUBJECT_KIND, {"kind": "article"}),
        value={"choice": "one"},
    )
    future = AuthorityRecord(
        authority_id="future",
        status=AuthorityStatus.CONFIRMED_AUTHORITY,
        active_from=NOW + timedelta(days=1),
        **base,
    )
    superseded = AuthorityRecord(
        authority_id="superseded",
        status=AuthorityStatus.CONFIRMED_AUTHORITY,
        superseded_by="new",
        **base,
    )
    tentative = AuthorityRecord(
        authority_id="tentative",
        status=AuthorityStatus.EXTRACTED_TENTATIVE,
        **base,
    )
    result = resolve_authority([future, superseded, tentative], scope={"kind": "article"}, at=NOW)
    assert result.status == "authority_gap"


def test_principle_priority_breaks_only_principle_ties() -> None:
    selector = ScopeSelector(SelectorType.SUBJECT_KIND, {"kind": "article"})
    low = AuthorityRecord(
        "low",
        "wema",
        "wema",
        AuthorityLayer.DESIGN_PRINCIPLE,
        AuthorityStatus.CONFIRMED_AUTHORITY,
        selector,
        {"choice": "low"},
        priority=1,
    )
    high = AuthorityRecord(
        "high",
        "wema",
        "wema",
        AuthorityLayer.DESIGN_PRINCIPLE,
        AuthorityStatus.CONFIRMED_AUTHORITY,
        selector,
        {"choice": "high"},
        priority=2,
    )
    result = resolve_authority([low, high], scope={"kind": "article"}, at=NOW)
    assert result.selected == (high,)
