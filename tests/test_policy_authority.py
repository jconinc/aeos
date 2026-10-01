"""Policy commands are authorized by exact confirmed grants, never by inference."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aeos_kernel.authority import AuthorityRecord, ScopeSelector
from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import (
    COMMAND_AUTHORITY_CLASSES,
    POLICY_COMMANDS,
    PolicyAuthorityStatus,
    authorize_policy_command,
    command_section,
)
from aeos_kernel.product_policy_v2 import SCHEMA_VERSION_V2

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


def test_v2_sweep_section_requires_its_exact_owner_and_v1_stays_closed() -> None:
    scope = {"section": "source_sweep_calendar"}
    with pytest.raises(ContractError):
        command_section("record_manifest_decision", scope["section"])
    correct = grant(
        args=scope,
        value={"authority_class": "calendar_policy_owner", "decision_ref": "example://calendar"},
    )
    assert decide(correct, section=scope["section"], schema_version=SCHEMA_VERSION_V2).authorized
    wrong = grant(
        args=scope,
        value={"authority_class": "finance_owner", "decision_ref": "example://wrong"},
    )
    assert (
        decide(wrong, section=scope["section"], schema_version=SCHEMA_VERSION_V2).status
        is PolicyAuthorityStatus.CLASS_MISMATCH
    )


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
    with pytest.raises(ContractError):
        command_section("withdraw_latest_service_grant_set", "whole_manifest")
    assert command_section("withdraw_latest_service_grant_set", None) == "service_grant_withdrawal"
    assert command_section("revoke_manifest", "service_grant_withdrawal") == (
        "service_grant_withdrawal"
    )


#: The literal class table. Swapping any two rows must fail this test.
EXPECTED_COMMAND_CLASSES = {
    "propose_phase": "portfolio_owner",
    "record_phase_decision": "portfolio_owner",
    "select_phase": "portfolio_owner",
    "deactivate_phase": "portfolio_owner",
    "retire_phase": "portfolio_owner",
    "propose_manifest": None,
    "activate_manifest": "release_owner",
    "replace_manifest": "product_owner",
    "revoke_manifest": "product_owner",
    "rollback_manifest": "release_owner",
    "deactivate_manifest": "release_owner",
    "withdraw_latest_service_grant_set": "security_role",
}


def test_every_command_names_its_required_class() -> None:
    assert dict(COMMAND_AUTHORITY_CLASSES) == EXPECTED_COMMAND_CLASSES
    assert set(POLICY_COMMANDS) == set(EXPECTED_COMMAND_CLASSES) | {"record_manifest_decision"}


def command_grant(command: str, section: str, authority_class: str) -> AuthorityRecord:
    return grant(
        args={"command": command, "section": section},
        value={"authority_class": authority_class, "decision_ref": "example://decision/cmd"},
    )


@pytest.mark.parametrize(
    ("command", "section", "label", "required"),
    [
        ("revoke_manifest", None, "whole_manifest", "product_owner"),
        (
            "withdraw_latest_service_grant_set",
            None,
            "service_grant_withdrawal",
            "security_role",
        ),
        ("select_phase", None, "portfolio_phase", "portfolio_owner"),
        ("activate_manifest", None, "manifest_selection", "release_owner"),
        ("replace_manifest", None, "manifest_selection", "product_owner"),
        ("rollback_manifest", None, "manifest_selection", "release_owner"),
        ("record_manifest_decision", "product_legal", "product_legal", "product_legal_owner"),
        ("record_manifest_decision", "brand_tone", "brand_tone", "brand_owner"),
    ],
)
def test_a_command_grant_of_the_wrong_class_does_not_authorize(
    command: str, section: str | None, label: str, required: str
) -> None:
    for authority_class in ("brand_owner", "product_owner", "security_role", "release_owner"):
        decision = decide(
            command_grant(command, label, authority_class), command=command, section=section
        )
        if authority_class == required:
            assert decision.authorized, (command, authority_class)
        else:
            assert decision.status is PolicyAuthorityStatus.CLASS_MISMATCH, (
                command,
                authority_class,
            )
    right = decide(command_grant(command, label, required), command=command, section=section)
    assert right.authorized and right.authority_class == required


def test_a_proposal_needs_only_its_exact_grant() -> None:
    proposal = command_grant("propose_manifest", "manifest_proposal", "support_move_service")
    assert decide(proposal, command="propose_manifest", section=None).authorized
    assert (
        decide(proposal, command="activate_manifest", section=None).status
        is PolicyAuthorityStatus.MISSING
    )


def test_a_grant_withdrawing_revocation_needs_both_exact_grants() -> None:
    whole = command_grant("revoke_manifest", "whole_manifest", "product_owner")
    security = grant(
        authority_id="grant-security",
        args={"command": "revoke_manifest", "section": "service_grant_withdrawal"},
        value={"authority_class": "security_role", "decision_ref": "example://decision/sec"},
    )
    scoped = {"command": "revoke_manifest", "section": "service_grant_withdrawal"}
    assert decide(security, **scoped).status is PolicyAuthorityStatus.MISSING
    assert decide(whole, **scoped).status is PolicyAuthorityStatus.MISSING
    both = decide(whole, security, **scoped)
    assert both.authorized and both.authority_class == "product_owner"
    assert both.grant_withdrawal is not None
    assert both.grant_withdrawal.authority_class == "security_role"
    assert both.grant_withdrawal.decision_ref == "example://decision/sec"
    wrong = grant(
        authority_id="grant-wrong",
        args={"command": "revoke_manifest", "section": "service_grant_withdrawal"},
        value={"authority_class": "product_owner", "decision_ref": "example://decision/x"},
    )
    assert decide(whole, wrong, **scoped).status is PolicyAuthorityStatus.CLASS_MISMATCH
    plain = decide(whole, security, command="revoke_manifest", section=None)
    assert plain.authorized and plain.grant_withdrawal is None
