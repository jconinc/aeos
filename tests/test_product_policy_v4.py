"""PB-211: closed thresholds/purposes retain E3 security and C15 sweep identity."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import command_section, required_authority_class
from aeos_kernel.product_policy import load_canonical_manifest
from aeos_kernel.product_policy_v2 import (
    REQUIRED_SWEEP_HOST_CAPABILITIES_V2,
    load_canonical_manifest_v2,
)
from aeos_kernel.product_policy_v3 import CanonicalProductManifestV3, load_canonical_manifest_v3
from aeos_kernel.product_policy_v4 import (
    COMMERCIAL_PURPOSE_PRINCIPAL_CLASSES,
    READER_CAPABILITIES_V4,
    SCHEMA_VERSION_V4,
    load_canonical_manifest_v4,
    policy_leaf_paths_v4,
    purpose_principal_classes_v4,
    section_authority_classes_v4,
    section_paths_v4,
)


def candidate(profile: str = "base") -> dict[str, Any]:
    source = files("aeos_kernel.schemas").joinpath(
        "product_policy", f"canonical_manifest_v3_{profile}.json"
    )
    payload = json.loads(source.read_text())
    payload["schema_version"] = SCHEMA_VERSION_V4
    payload["commercial"]["cac_ltv_thresholds"] = {
        "max_cac_usd": "0",
        "min_ltv_cac_ratio": "3",
        "payback_months_max": "12",
    }
    payload["compatibility"].update(min_reader="4.0.0", max_reader="4.9.0")
    payload["compatibility"]["required_capabilities"] += list(READER_CAPABILITIES_V4)
    payload["service_principal_grants"] += [
        {"purpose": purpose, "principal_class": capacity, "principal_id": f"fictional:{purpose}"}
        for purpose, capacity in COMMERCIAL_PURPOSE_PRINCIPAL_CLASSES.items()
    ]
    return dict(payload)


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_v4_roundtrip_keeps_security_sweep_and_exact_section_coverage(profile: str) -> None:
    policy = load_canonical_manifest_v4(candidate(profile))
    assert isinstance(policy, CanonicalProductManifestV3)
    assert policy.reader_compatible(available_capabilities=REQUIRED_SWEEP_HOST_CAPABILITIES_V2)
    assert not policy.reader_compatible("3.0.0")
    assert policy.cac_ltv_thresholds["max_cac_usd"] == "0"
    assert load_canonical_manifest_v4(policy.canonical_bytes) == policy
    paths = [path for section in section_paths_v4(profile).values() for path in section]
    assert len(paths) == len(set(paths))
    assert set(paths) == set(policy_leaf_paths_v4(policy.payload))
    assert section_authority_classes_v4(profile)["commercial_terms"] == "commercial_owner"
    assert section_authority_classes_v4(profile)["product_security"] == "security_role"
    assert policy.product_security("fictional").manifest_digest == policy.manifest_digest
    assert "commercial.cac_ltv_thresholds" in policy.section("commercial_terms")
    assert (
        command_section(
            "record_manifest_decision", "commercial_terms", schema_version=SCHEMA_VERSION_V4
        )
        == "commercial_terms"
    )
    assert (
        required_authority_class(
            "record_manifest_decision", "product_security", schema_version=SCHEMA_VERSION_V4
        )
        == "security_role"
    )
    assert ("correction_sweep" in purpose_principal_classes_v4(profile)) == (
        profile == "correction_sweep"
    )
    if profile == "correction_sweep":
        assert policy.correction_sweep and not policy.reader_compatible()


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_cac_usd", "-1"),
        ("min_ltv_cac_ratio", "0"),
        ("payback_months_max", "0"),
        ("min_ltv_cac_ratio", "NaN"),
        ("payback_months_max", "Infinity"),
        ("max_cac_usd", 2),
        ("min_ltv_cac_ratio", None),
        ("payback_months_max", True),
        ("max_cac_usd", "1e2"),
    ],
)
def test_invalid_thresholds_refuse(field: str, value: Any) -> None:
    payload = candidate()
    payload["commercial"]["cac_ltv_thresholds"][field] = value
    with pytest.raises(ContractError):
        load_canonical_manifest_v4(payload)


@pytest.mark.parametrize("change", ["missing", "unknown", "capability", "security", "profile"])
def test_required_closed_fields_and_capability_refuse(change: str) -> None:
    payload = candidate()
    if change == "missing":
        del payload["commercial"]["cac_ltv_thresholds"]
    elif change == "unknown":
        payload["commercial"]["cac_ltv_thresholds"]["source_default"] = "3"
    elif change == "capability":
        payload["compatibility"]["required_capabilities"].remove("commercial_thresholds_v1")
    elif change == "security":
        del payload["security"]
    else:
        payload["manifest_profile"] = "unknown"
    with pytest.raises(ContractError):
        load_canonical_manifest_v4(payload)


@pytest.mark.parametrize(
    "purpose,capacity",
    [
        ("commercial_paid_effect", "marketing_effects_worker"),
        ("commercial_scale_admission", "commercial_paid_effect_worker"),
        ("correction_sweep", "correction_sweep_service"),
        ("unknown", "commercial_scale_admission_service"),
    ],
)
def test_grants_cannot_alias_or_cross_profile(purpose: str, capacity: str) -> None:
    payload = candidate()
    payload["service_principal_grants"].append(
        {
            "purpose": purpose,
            "principal_class": capacity,
            "principal_id": "fictional:wrong",
        }
    )
    with pytest.raises(ContractError):
        load_canonical_manifest_v4(payload)


@pytest.mark.parametrize(
    "loader",
    [
        load_canonical_manifest,
        load_canonical_manifest_v2,
        load_canonical_manifest_v3,
    ],
)
def test_old_readers_never_accept_v4(loader: Any) -> None:
    with pytest.raises(ContractError):
        loader(candidate())


def test_identity_threshold_and_new_grant_digest_bindings() -> None:
    payload = candidate()
    first = load_canonical_manifest_v4(payload)
    with pytest.raises(ContractError):
        load_canonical_manifest_v4(payload, manifest_version="wrong")
    payload["commercial"]["cac_ltv_thresholds"]["min_ltv_cac_ratio"] = "4"
    changed = load_canonical_manifest_v4(payload)
    assert changed.manifest_digest != first.manifest_digest
    assert changed.grant_set_digest == first.grant_set_digest
    payload["service_principal_grants"][-1]["principal_id"] = "fictional:changed"
    assert load_canonical_manifest_v4(payload).grant_set_digest != first.grant_set_digest
    payload["security"]["selected_hosts"] = None
    assert load_canonical_manifest_v4(payload).product_security("fictional").selected_hosts is None
    payload["security"]["selected_hosts"] = []
    assert load_canonical_manifest_v4(payload).product_security("fictional").selected_hosts == ()
