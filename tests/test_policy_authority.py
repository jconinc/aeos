"""Policy commands are authorized by exact confirmed grants, never by inference."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aeos_kernel.authority import AuthorityRecord, ScopeSelector
from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import (
    PolicyAuthorityStatus,
    authorize_policy_command,
    command_section,
)

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)
PRODUCT = "0190f2a4-1b2c-7d3e-8f40-5a6b7c8d9e0f"


def grant(**overrides: Any) -> AuthorityRecord:
    args = {
        "subject_id": PRODUCT,
        "command": "record_manifest_decision",
        "section": "budget",
        "principal_id": "example-finance-reviewer",
    }
    args.update(overrides.pop("args", {}))
    values: dict[str, Any] = {
        "authority_id": overrides.pop("authority_id", "grant-1"),
        "vertical_id": "example",
        "tenant_id": "example-tenant",
        "layer": "law_or_policy",
        "status": "confirmed_authority",
        "selector": ScopeSelector("exact_attributes", args),
        "value": {"authority_class": "finance_owner", "decision_ref": "example://decision/grant-1"},
    }
    values.update(overrides)
    return AuthorityRecord(**values)


def decide(*records: AuthorityRecord, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "vertical_id": "example",
        "tenant_id": "example-tenant",
        "subject_id": PRODUCT,
        "command": "record_manifest_decision",
        "section": "budget",
        "principal_id": "example-finance-reviewer",
        "at": NOW,
    }
    values.update(overrides)
    return authorize_policy_command(records, **values)


def test_no_records_is_missing_authority() -> None:
    assert decide().status is PolicyAuthorityStatus.MISSING


def test_an_exact_confirmed_grant_authorizes_with_its_class_and_decision() -> None:
    decision = decide(grant())
    assert decision.authorized
    assert decision.authority_class == "finance_owner"
    assert decision.decision_ref == "example://decision/grant-1"


def test_a_different_principal_product_or_section_is_not_covered() -> None:
    assert decide(grant(), principal_id="someone-else").status is PolicyAuthorityStatus.MISSING
    assert (
        decide(grant(), subject_id="0190f2a4-1b2c-7d3e-8f40-000000000000").status
        is PolicyAuthorityStatus.MISSING
    )
    assert decide(grant(), section="paid_fence").status is PolicyAuthorityStatus.MISSING


def test_a_partial_selector_cannot_broaden_into_a_grant() -> None:
    broad = AuthorityRecord(
        authority_id="broad",
        vertical_id="example",
        tenant_id="example-tenant",
        layer="law_or_policy",
        status="confirmed_authority",
        selector=ScopeSelector("exact_attributes", {"subject_id": PRODUCT}),
        value={"authority_class": "finance_owner", "decision_ref": "example://broad"},
    )
    assert decide(broad).status is PolicyAuthorityStatus.MISSING


def test_expired_or_future_authority_is_stale() -> None:
    assert decide(grant(active_until=NOW)).status is PolicyAuthorityStatus.STALE
    assert (
        decide(grant(active_from=NOW + timedelta(seconds=1))).status is PolicyAuthorityStatus.STALE
    )


@pytest.mark.parametrize("status", ["retired", "rejected", "superseded"])
def test_withdrawn_authority_is_revoked(status: str) -> None:
    assert decide(grant(status=status)).status is PolicyAuthorityStatus.REVOKED
    assert decide(grant(superseded_by="grant-2")).status is PolicyAuthorityStatus.REVOKED


def test_unconfirmed_authority_is_missing() -> None:
    assert decide(grant(status="extracted_tentative")).status is PolicyAuthorityStatus.MISSING


def test_a_section_decision_needs_the_sections_authority_class() -> None:
    wrong = grant(value={"authority_class": "brand_owner", "decision_ref": "example://d"})
    assert decide(wrong).status is PolicyAuthorityStatus.CLASS_MISMATCH
    no_ref = grant(value={"authority_class": "finance_owner"})
    assert decide(no_ref).status is PolicyAuthorityStatus.MISSING


def test_conflicting_equal_grants_and_foreign_tenants_refuse() -> None:
    other = grant(
        authority_id="grant-2",
        value={"authority_class": "finance_owner", "decision_ref": "example://other"},
    )
    assert decide(grant(), other).status is PolicyAuthorityStatus.CONFLICT
    assert decide(grant(tenant_id="elsewhere")).status is PolicyAuthorityStatus.SCOPE_VIOLATION


def test_every_command_has_one_fixed_scope_label() -> None:
    assert command_section("revoke_manifest", None) == "whole_manifest"
    assert command_section("select_phase", None) == "portfolio_phase"
    assert command_section("activate_manifest", None) == "manifest_selection"
    assert command_section("propose_manifest", None) == "manifest_proposal"
    with pytest.raises(ContractError):
        command_section("record_manifest_decision", "whole_manifest")
    with pytest.raises(ContractError):
        command_section("activate_manifest", "budget")
    with pytest.raises(ContractError):
        command_section("approve_everything", None)
