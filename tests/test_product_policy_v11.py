"""O07-WEMA-ALERT-SLA-R2: exact v11 alert targets over immutable v10 policy."""

from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel.product_policy import ManifestContractError
from aeos_kernel.product_policy_v2 import REQUIRED_SWEEP_HOST_CAPABILITIES_V2
from aeos_kernel.product_policy_v5 import REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
from aeos_kernel.product_policy_v6 import REQUIRED_WLG_HOST_CAPABILITIES_V6
from aeos_kernel.product_policy_v10 import (
    load_canonical_manifest_v10,
    policy_leaf_paths_v10,
    purpose_principal_classes_v10,
    section_authority_classes_v10,
    section_paths_v10,
)
from aeos_kernel.product_policy_v11 import (
    READER_CAPABILITIES_V11,
    canonical_manifest_bytes_v11,
    load_canonical_manifest_v11,
    normalize_manifest_payload_v11,
    policy_leaf_paths_v11,
    purpose_principal_classes_v11,
    section_authority_classes_v11,
    section_paths_v11,
)

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")
SEVERITIES = ("critical", "high", "moderate", "low")


def candidate(profile: str = "base") -> dict[str, Any]:
    return json.loads(SCHEMAS.joinpath(f"canonical_manifest_v11_{profile}.json").read_text())


def schema() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(SCHEMAS.joinpath("product_manifest_v11.schema.json").read_text())
    )


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_packaged_vectors_exact_round_trip_and_inherited_maps(profile: str) -> None:
    raw = candidate(profile)
    policy = load_canonical_manifest_v11(raw)
    vector = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v11_{profile}.vectors.json").read_text()
    )
    assert policy.canonical_bytes == SCHEMAS.joinpath(vector["canonical_bytes"]).read_bytes()
    assert policy.manifest_digest == vector["manifest_sha256"]
    assert policy.grant_set_digest == vector["grant_set_sha256"]
    assert load_canonical_manifest_v11(policy.canonical_bytes) == policy
    assert canonical_manifest_bytes_v11(policy.payload) == policy.canonical_bytes
    assert normalize_manifest_payload_v11(policy.payload) == json.loads(policy.canonical_bytes)
    assert (
        policy.product_security("wema").audit_retention_days
        == raw["security"]["slo_targets"]["audit_retention_days"]
    )
    assert (
        policy.section("product_security")["security"]["alert_sla"]
        == policy.payload["security"]["alert_sla"]
    )
    assert policy.reader_compatible(
        available_capabilities=(
            REQUIRED_SWEEP_HOST_CAPABILITIES_V2
            | REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
            | REQUIRED_WLG_HOST_CAPABILITIES_V6
        )
    )
    assert section_paths_v11(profile) == section_paths_v10(profile)
    assert section_authority_classes_v11(profile) == section_authority_classes_v10(profile)
    assert purpose_principal_classes_v11(profile) == purpose_principal_classes_v10(profile)
    assert policy_leaf_paths_v11(policy.payload) == policy_leaf_paths_v10(policy.payload)
    schema().validate(raw)
    with pytest.raises(ManifestContractError):
        load_canonical_manifest_v10(policy.canonical_bytes)


@pytest.mark.parametrize("severity", SEVERITIES)
@pytest.mark.parametrize("token", ["1", "1.0000000000000001", "1e-400", "1e400"])
def test_seconds_keep_exact_json_value_and_digest(severity: str, token: str) -> None:
    raw = SCHEMAS.joinpath("canonical_manifest_v11_base.canonical").read_bytes()
    original = f'"{severity}":'.encode() + str(SEVERITIES.index(severity) + 1).encode()
    assert raw.count(original) == 1
    policy = load_canonical_manifest_v11(raw.replace(original, f'"{severity}":{token}'.encode()))
    assert policy.payload["security"]["alert_sla"]["seconds_by_severity"][severity] == Decimal(
        token
    )
    assert load_canonical_manifest_v11(policy.canonical_bytes) == policy
    assert canonical_manifest_bytes_v11(policy.payload) == policy.canonical_bytes
    if token != str(SEVERITIES.index(severity) + 1):
        assert policy.manifest_digest != load_canonical_manifest_v11(candidate()).manifest_digest


@pytest.mark.parametrize(
    "value", [True, False, None, "1", {}, [], 0, -1, float("inf"), float("nan")]
)
def test_seconds_refuse_nonpositive_or_nonfinite(value: Any) -> None:
    raw = candidate()
    raw["security"]["alert_sla"]["seconds_by_severity"]["critical"] = value
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v11(raw)
    assert caught.value.path == "manifest.security.alert_sla.seconds_by_severity.critical"
    if value not in (float("inf"),) and not (isinstance(value, float) and value != value):
        with pytest.raises(ValidationError):
            schema().validate(raw)


@pytest.mark.parametrize("value", [None, True, 0, 1439, 1441, 1440.0, "1440"])
def test_window_is_literal_json_integer(value: Any) -> None:
    raw = candidate()
    raw["security"]["alert_sla"]["window_minutes"] = value
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v11(raw)
    assert caught.value.path == "manifest.security.alert_sla.window_minutes"


@pytest.mark.parametrize("path", ["alert_sla", "window_minutes", "seconds_by_severity", "critical"])
def test_closed_shape_refuses_missing_or_extra_fields(path: str) -> None:
    raw = candidate()
    alert = raw["security"]["alert_sla"]
    if path == "alert_sla":
        del raw["security"]["alert_sla"]
    elif path == "critical":
        del alert["seconds_by_severity"][path]
    else:
        del alert[path]
    with pytest.raises(ManifestContractError):
        load_canonical_manifest_v11(raw)
    raw = candidate()
    if path == "alert_sla":
        raw["alert_sla"] = raw["security"]["alert_sla"]
    elif path == "critical":
        raw["security"]["alert_sla"]["seconds_by_severity"]["urgent"] = 1
    else:
        raw["security"]["alert_sla"]["extra"] = 1
    with pytest.raises(ManifestContractError):
        load_canonical_manifest_v11(raw)


def test_v11_capability_is_required_without_changing_v10() -> None:
    raw = candidate()
    raw["compatibility"]["required_capabilities"].remove("canonical_manifest_bytes_v11")
    with pytest.raises(ManifestContractError):
        load_canonical_manifest_v11(raw)
    v10 = json.loads(SCHEMAS.joinpath("canonical_manifest_v10_base.json").read_text())
    before = SCHEMAS.joinpath("canonical_manifest_v10_base.canonical").read_bytes()
    assert load_canonical_manifest_v10(v10).canonical_bytes == before
    assert (
        frozenset(
            {
                "aeos.product-manifest.v11",
                "canonical_manifest_bytes_v11",
            }
        )
        == READER_CAPABILITIES_V11
    )
