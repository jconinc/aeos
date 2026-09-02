from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aeos_kernel import (
    AuthorityLayer,
    AuthorityRecord,
    AuthorityStatus,
    ScopeSelector,
    SelectorType,
    resolve_authority,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def record(
    authority_id: str,
    *,
    layer: str,
    value: str,
    selector: ScopeSelector | None = None,
    active_until: datetime | None = None,
) -> AuthorityRecord:
    return AuthorityRecord(
        authority_id=authority_id,
        vertical_id="wema",
        tenant_id="wema",
        layer=layer,
        status=AuthorityStatus.CONFIRMED_AUTHORITY.value,
        selector=selector or ScopeSelector(SelectorType.SUBJECT_KIND, {"kind": "article"}),
        value={"voice": value},
        active_until=active_until,
    )


def test_more_specific_higher_layer_authority_wins() -> None:
    general = record("general", layer=AuthorityLayer.DESIGN_PRINCIPLE, value="general")
    exact = record(
        "exact",
        layer=AuthorityLayer.DESIGN_DECISION,
        value="article-specific",
        selector=ScopeSelector(SelectorType.SUBJECT_ID, {"subject_id": "article-1"}),
    )
    result = resolve_authority(
        [general, exact],
        vertical_id="wema",
        tenant_id="wema",
        scope={"kind": "article", "subject_id": "article-1"},
        at=NOW,
    )
    assert result.status == "authorized"
    assert result.selected == (exact,)


def test_same_rank_conflicting_authority_fails_closed() -> None:
    first = record("first", layer=AuthorityLayer.DESIGN_DECISION, value="one")
    second = record("second", layer=AuthorityLayer.DESIGN_DECISION, value="two")
    result = resolve_authority(
        [first, second],
        vertical_id="wema",
        tenant_id="wema",
        scope={"kind": "article"},
        at=NOW,
    )
    assert result.status == "authority_conflict"
    assert {item.authority_id for item in result.conflicts} == {"first", "second"}


def test_expired_authority_is_not_runtime_authority() -> None:
    expired = record(
        "expired",
        layer=AuthorityLayer.DESIGN_DECISION,
        value="old",
        active_until=NOW - timedelta(seconds=1),
    )
    result = resolve_authority(
        [expired],
        vertical_id="wema",
        tenant_id="wema",
        scope={"kind": "article"},
        at=NOW,
    )
    assert result.status == "authority_gap"


def test_wlg_rule_wildcard_compatibility() -> None:
    selector = ScopeSelector(SelectorType.RULE_SCOPE, {"rule_id": "*", "domain": "care"})
    authority = record(
        "wlg-compatible",
        layer="Convention",
        value="value",
        selector=selector,
    )
    result = resolve_authority(
        [authority],
        vertical_id="wema",
        tenant_id="wema",
        scope={"rule_id": "any_registered_rule", "domain": "care"},
        at=NOW,
    )
    assert result.status == "authorized"


def test_cross_tenant_authority_is_a_typed_scope_violation() -> None:
    foreign = record("foreign", layer=AuthorityLayer.DESIGN_DECISION, value="foreign")
    result = resolve_authority(
        [foreign],
        vertical_id="wema",
        tenant_id="another-tenant",
        scope={"kind": "article"},
        at=NOW,
    )
    assert result.status == "authority_scope_violation"
    assert result.conflicts == (foreign,)
