"""PB-233 §5: a retained key proof goes stale at policy, source or vault drift."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from uuid import UUID

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.key_proof import (
    CurrentKeyProof,
    CurrentKeyState,
    KeyDomainEvidence,
    SourceEvidenceReference,
    verify_current_key_proof,
)
from aeos_kernel.runtime_policy import EffectiveRuntimePolicy, PermissionLaneIdentity

NOW = dt.datetime(2026, 9, 27, 17, 0, tzinfo=dt.UTC)
ISSUED = NOW - dt.timedelta(hours=1)
PROOF_ID = UUID("00000000-0000-4000-8000-000000000001")
POLICY_ID = UUID("00000000-0000-4000-8000-000000000002")
KEY_ID = UUID("00000000-0000-4000-8000-000000000003")
EVIDENCE_ID = UUID("00000000-0000-4000-8000-000000000004")


def _lane() -> PermissionLaneIdentity:
    return PermissionLaneIdentity(
        permission_id=UUID("00000000-0000-4000-8000-000000000010"),
        binding_id=UUID("00000000-0000-4000-8000-000000000011"),
        binding_generation=2,
        permission_generation=3,
        product_slug="care",
        tool_key="model",
        move_types=("draft_reply",),
        egress_reference="guarded_http",
        role_scope_epoch=4,
    )


def _refs() -> tuple[SourceEvidenceReference, ...]:
    return (SourceEvidenceReference("source_inventory", EVIDENCE_ID, "e" * 64),)


def _policy() -> EffectiveRuntimePolicy:
    return EffectiveRuntimePolicy(
        platform_policy_id=POLICY_ID,
        platform_generation=2,
        manifest_digest="a" * 64,
        permission_generation=3,
        permission_lane=_lane(),
        allowed_hosts=(),
        untrusted_sources=(),
        go_live_mode="staging",
        at_rest_required=True,
        in_transit_required=True,
        key_rotation_days=30,
        audit_retention_days=60,
    )


def _domain(*, readback_at: dt.datetime = ISSUED) -> KeyDomainEvidence:
    return KeyDomainEvidence(
        domain_id="care_records",
        secret_ref_id=KEY_ID,
        secret_version=4,
        purpose="encryption_key",
        state="active",
        provider_version="version_4",
        provider_readback_at=readback_at,
        rotated_at=NOW - dt.timedelta(days=10),
        rotation_deadline=NOW + dt.timedelta(days=20),
        expires_at=NOW + dt.timedelta(days=40),
        at_rest_covered=True,
        in_transit_covered=True,
        ciphertext_reader_compatible=True,
    )


def _proof() -> CurrentKeyProof:
    return CurrentKeyProof(
        proof_id=PROOF_ID,
        product_slug="care",
        runtime_root="api",
        platform_policy_id=POLICY_ID,
        platform_generation=2,
        manifest_digest="a" * 64,
        permission_generation=3,
        permission_lane=_lane(),
        source_generation=7,
        inventory_digest="b" * 64,
        declaration_digest="c" * 64,
        domain_census_digest="d" * 64,
        domain_census_complete=True,
        domains=(_domain(),),
        source_evidence_refs=_refs(),
        issued_at=ISSUED,
        expires_at=NOW + dt.timedelta(hours=1),
    )


def _current() -> CurrentKeyState:
    return CurrentKeyState(
        product_slug="care",
        runtime_root="api",
        permission_lane=_lane(),
        source_generation=7,
        inventory_digest="b" * 64,
        declaration_digest="c" * 64,
        domain_census_digest="d" * 64,
        domain_census_complete=True,
        required_domain_ids=("care_records",),
        domains=(_domain(readback_at=NOW),),
        source_evidence_refs=_refs(),
    )


class Reader:
    def __init__(self, state: CurrentKeyState | None) -> None:
        self.state = state

    def read_current(self, *, product_slug: str, runtime_root: str) -> CurrentKeyState | None:
        assert (product_slug, runtime_root) == ("care", "api")
        return self.state


def _verify(
    *,
    proof: CurrentKeyProof | None = None,
    policy: EffectiveRuntimePolicy | None = None,
    current: CurrentKeyState | None = None,
    now: dt.datetime = NOW,
) -> UUID:
    return verify_current_key_proof(
        proof=_proof() if proof is None else proof,
        policy=_policy() if policy is None else policy,
        reader=Reader(_current() if current is None else current),
        product_slug="care",
        runtime_root="api",
        db_now=now,
    )


def test_exact_current_proof_matches_but_carries_no_live_mode() -> None:
    assert _verify() == PROOF_ID
    assert _policy().go_live_mode == "staging"


def test_equal_generation_different_permission_lane_refuses() -> None:
    other_binding = replace(_lane(), binding_id=UUID("00000000-0000-4000-8000-000000000099"))
    other_role_scope = replace(_lane(), role_scope_epoch=5)
    for different in (other_binding, other_role_scope):
        assert different.permission_generation == _lane().permission_generation
        with pytest.raises(ContractError, match="stale policy or source"):
            _verify(policy=replace(_policy(), permission_lane=different))
        with pytest.raises(ContractError, match="stale policy or source"):
            _verify(current=replace(_current(), permission_lane=different))
    assert (
        _verify(
            proof=replace(_proof(), permission_lane=other_binding),
            policy=replace(_policy(), permission_lane=other_binding),
            current=replace(_current(), permission_lane=other_binding),
        )
        == PROOF_ID
    )


def test_source_evidence_refs_match_exactly_and_are_required() -> None:
    extra = SourceEvidenceReference(
        "domain_census", UUID("00000000-0000-4000-8000-000000000005"), "f" * 64
    )
    refs = (extra, *_refs())
    assert (
        _verify(
            proof=replace(_proof(), source_evidence_refs=refs),
            current=replace(_current(), source_evidence_refs=refs),
        )
        == PROOF_ID
    )
    with pytest.raises(ContractError, match="stale policy or source"):
        _verify(proof=replace(_proof(), source_evidence_refs=refs))
    changed = (replace(_refs()[0], evidence_digest="f" * 64),)
    with pytest.raises(ContractError, match="stale policy or source"):
        _verify(current=replace(_current(), source_evidence_refs=changed))
    with pytest.raises(ContractError, match="nonempty immutable reference set"):
        replace(_proof(), source_evidence_refs=())
    with pytest.raises(ContractError, match="canonical and unique"):
        replace(_proof(), source_evidence_refs=(*_refs(), *_refs()))


def test_missing_proof_or_reader_state_refuses() -> None:
    with pytest.raises(ContractError, match="unavailable"):
        verify_current_key_proof(
            proof=None,
            policy=_policy(),
            reader=Reader(_current()),
            product_slug="care",
            runtime_root="api",
            db_now=NOW,
        )
    with pytest.raises(ContractError, match="unavailable"):
        verify_current_key_proof(
            proof=_proof(),
            policy=_policy(),
            reader=Reader(None),
            product_slug="care",
            runtime_root="api",
            db_now=NOW,
        )


@pytest.mark.parametrize(
    ("proof_change", "policy_change", "current_change"),
    [
        ({"platform_generation": 1}, {}, {}),
        ({"manifest_digest": "e" * 64}, {}, {}),
        ({"source_generation": 6}, {}, {}),
        ({"inventory_digest": "e" * 64}, {}, {}),
        ({"declaration_digest": "e" * 64}, {}, {}),
        ({"domain_census_digest": "e" * 64}, {}, {}),
        ({}, {"platform_generation": 3}, {}),
        ({}, {}, {"source_generation": 8}),
        ({}, {}, {"inventory_digest": "e" * 64}),
    ],
)
def test_any_policy_or_source_generation_change_invalidates_proof(
    proof_change: dict[str, object],
    policy_change: dict[str, object],
    current_change: dict[str, object],
) -> None:
    with pytest.raises(ContractError, match="stale policy or source"):
        _verify(
            proof=replace(_proof(), **proof_change),
            policy=replace(_policy(), **policy_change),
            current=replace(_current(), **current_change),
        )


@pytest.mark.parametrize(
    "current",
    [
        replace(_current(), domain_census_complete=False),
        replace(_current(), required_domain_ids=("care_records", "payments")),
        replace(_current(), required_domain_ids=()),
        replace(_current(), domains=()),
    ],
)
def test_incomplete_or_empty_domain_census_never_goes_green(current: CurrentKeyState) -> None:
    with pytest.raises(ContractError, match=r"domain census|domain coverage"):
        _verify(current=current)


@pytest.mark.parametrize(
    "domain",
    [
        replace(_domain(readback_at=NOW), secret_version=5),
        replace(_domain(readback_at=NOW), provider_version="version_5"),
        replace(_domain(readback_at=NOW), state="rotating"),
        replace(_domain(readback_at=NOW), state="revoked"),
        replace(_domain(readback_at=NOW), purpose="signing_key"),
        replace(_domain(readback_at=NOW), at_rest_covered=False),
        replace(_domain(readback_at=NOW), in_transit_covered=False),
        replace(_domain(readback_at=NOW), ciphertext_reader_compatible=False),
        replace(_domain(readback_at=NOW), provider_readback_at=ISSUED - dt.timedelta(seconds=1)),
    ],
)
def test_current_key_or_coverage_drift_refuses(domain: KeyDomainEvidence) -> None:
    with pytest.raises(ContractError, match="key or coverage"):
        _verify(current=replace(_current(), domains=(domain,)))


def test_proof_expiry_and_policy_rotation_deadline_refuse() -> None:
    with pytest.raises(ContractError, match="valid time"):
        _verify(now=NOW + dt.timedelta(hours=1))
    overdue = replace(_domain(), rotated_at=NOW - dt.timedelta(days=30))
    with pytest.raises(ContractError, match="key or coverage"):
        _verify(proof=replace(_proof(), domains=(overdue,)))


def test_proof_rejects_duplicate_domains_and_nonopaque_version() -> None:
    with pytest.raises(ContractError, match="proof permission lane is invalid"):
        replace(_proof(), permission_generation=2)
    with pytest.raises(ContractError, match="duplicates"):
        replace(_proof(), domains=(_domain(), _domain()))
    with pytest.raises(ContractError, match="opaque safe token"):
        replace(_domain(), provider_version="vault/path#secret")
