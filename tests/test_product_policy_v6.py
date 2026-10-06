"""PB-219/PB-226: WLG native capture and operation never borrow a readback grant."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import command_section
from aeos_kernel.product_policy_v2 import REQUIRED_SWEEP_HOST_CAPABILITIES_V2
from aeos_kernel.product_policy_v5 import (
    REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5,
    load_canonical_manifest_v5,
)
from aeos_kernel.product_policy_v6 import (
    READER_CAPABILITIES_V6,
    REQUIRED_WLG_HOST_CAPABILITIES_V6,
    SCHEMA_VERSION_V6,
    WLG_PURPOSE_PRINCIPAL_CLASSES,
    load_canonical_manifest_v6,
)

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")


def candidate(profile: str = "base") -> dict[str, Any]:
    payload = json.loads(SCHEMAS.joinpath(f"canonical_manifest_v5_{profile}.json").read_text())
    payload["schema_version"] = SCHEMA_VERSION_V6
    payload["compatibility"]["min_reader"] = "6.0.0"
    payload["compatibility"]["max_reader"] = "6.9.0"
    payload["compatibility"]["required_capabilities"] = sorted(
        set(payload["compatibility"]["required_capabilities"])
        | READER_CAPABILITIES_V6
        | REQUIRED_WLG_HOST_CAPABILITIES_V6
    )
    payload["service_principal_grants"].extend(
        {
            "purpose": purpose,
            "principal_id": f"fictional:{purpose}",
            "principal_class": principal_class,
        }
        for purpose, principal_class in WLG_PURPOSE_PRINCIPAL_CLASSES.items()
    )
    return payload


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_distinct_grants_preserve_complete_prior_policy(profile: str) -> None:
    payload = candidate(profile)
    policy = load_canonical_manifest_v6(payload)
    assert load_canonical_manifest_v6(policy.canonical_bytes) == policy
    capabilities = (
        REQUIRED_SWEEP_HOST_CAPABILITIES_V2 | REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
    )
    assert not policy.reader_compatible(available_capabilities=capabilities)
    assert policy.reader_compatible(
        available_capabilities=capabilities | REQUIRED_WLG_HOST_CAPABILITIES_V6
    )
    assert not policy.reader_compatible(
        "5.0.0", available_capabilities=capabilities | REQUIRED_WLG_HOST_CAPABILITIES_V6
    )
    assert (
        policy.support_measure_policy_binding
        == payload["source_bindings"]["support_measure_policy"]
    )
    assert policy.cac_ltv_thresholds == payload["commercial"]["cac_ltv_thresholds"]
    assert policy.grants_principal(
        purpose="wlg_capture_admission",
        principal_id="fictional:wlg_capture_admission",
        principal_class="wlg_capture_service",
    )
    assert not policy.grants_principal(
        purpose="wlg_operation_admission",
        principal_id="fictional:wlg_capture_admission",
        principal_class="wlg_capture_service",
    )
    assert (
        command_section(
            "record_manifest_decision", "service_principal_grants", schema_version=SCHEMA_VERSION_V6
        )
        == "service_principal_grants"
    )
    Draft202012Validator(
        json.loads(SCHEMAS.joinpath("product_manifest_v6.schema.json").read_text())
    ).validate(payload)
    with pytest.raises(ContractError):
        load_canonical_manifest_v5(payload)


@pytest.mark.parametrize(
    "change", ["wrong_class", "readback_class", "unknown_purpose", "missing_host_capability"]
)
def test_wrong_or_incomplete_native_authority_refuses(change: str) -> None:
    payload = candidate()
    grant = payload["service_principal_grants"][-1]
    if change == "missing_host_capability":
        payload["compatibility"]["required_capabilities"].remove("wlg_native_source_admission_v1")
    elif change == "unknown_purpose":
        grant["purpose"] = "native_write"
    else:
        grant["principal_class"] = (
            "wlg_capture_service" if change == "wrong_class" else "product_policy_read_client"
        )
    with pytest.raises(ContractError):
        load_canonical_manifest_v6(payload)


def test_no_native_grants_are_invented_and_grant_digest_changes() -> None:
    payload = candidate()
    granted = load_canonical_manifest_v6(payload)
    payload["service_principal_grants"] = [
        row
        for row in payload["service_principal_grants"]
        if row["purpose"] not in WLG_PURPOSE_PRINCIPAL_CLASSES
    ]
    payload["compatibility"]["required_capabilities"].remove("wlg_native_source_admission_v1")
    absent = load_canonical_manifest_v6(payload)
    assert absent.grant_set_digest != granted.grant_set_digest
    assert not absent.grants_principal(
        purpose="wlg_capture_admission",
        principal_id="fictional:wlg_capture_admission",
        principal_class="wlg_capture_service",
    )
