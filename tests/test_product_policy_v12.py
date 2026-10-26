"""O08-WEMA-SURFACES-R4: three closed serving declarations over immutable v11 policy."""

from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel.product_policy import ManifestContractError, decode_strict_json
from aeos_kernel.product_policy_v2 import REQUIRED_SWEEP_HOST_CAPABILITIES_V2
from aeos_kernel.product_policy_v5 import REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
from aeos_kernel.product_policy_v6 import REQUIRED_WLG_HOST_CAPABILITIES_V6
from aeos_kernel.product_policy_v11 import (
    load_canonical_manifest_v11,
    policy_leaf_paths_v11,
    purpose_principal_classes_v11,
    section_authority_classes_v11,
    section_paths_v11,
)
from aeos_kernel.product_policy_v12 import (
    READER_CAPABILITIES_V12,
    SERVING_SURFACE_KEYS_V12,
    canonical_manifest_bytes_v12,
    load_canonical_manifest_v12,
    normalize_manifest_payload_v12,
    policy_leaf_paths_v12,
    purpose_principal_classes_v12,
    section_authority_classes_v12,
    section_paths_v12,
)

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")


def candidate(profile: str = "base") -> dict[str, Any]:
    return json.loads(SCHEMAS.joinpath(f"canonical_manifest_v12_{profile}.json").read_text())


def schema() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(SCHEMAS.joinpath("product_manifest_v12.schema.json").read_text())
    )


def refused(raw: dict[str, Any]) -> ManifestContractError:
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v12(raw)
    return caught.value


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_packaged_vectors_exact_round_trip_and_inherited_maps(profile: str) -> None:
    raw = candidate(profile)
    policy = load_canonical_manifest_v12(raw)
    vector = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v12_{profile}.vectors.json").read_text()
    )
    assert policy.canonical_bytes == SCHEMAS.joinpath(vector["canonical_bytes"]).read_bytes()
    assert policy.manifest_digest == vector["manifest_sha256"]
    assert policy.grant_set_digest == vector["grant_set_sha256"]
    assert load_canonical_manifest_v12(policy.canonical_bytes) == policy
    assert canonical_manifest_bytes_v12(policy.payload) == policy.canonical_bytes
    assert normalize_manifest_payload_v12(policy.payload) == decode_strict_json(
        policy.canonical_bytes
    )
    assert (
        policy.product_security("wema").audit_retention_days
        == raw["security"]["slo_targets"]["audit_retention_days"]
    )
    section = policy.section("product_security")["security"]
    assert section["serving_surfaces"] == policy.payload["security"]["serving_surfaces"]
    assert section["alert_sla"] == policy.payload["security"]["alert_sla"]
    assert [item["surface_key"] for item in section["serving_surfaces"]] == list(
        SERVING_SURFACE_KEYS_V12
    )
    assert policy.reader_compatible(
        available_capabilities=(
            REQUIRED_SWEEP_HOST_CAPABILITIES_V2
            | REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
            | REQUIRED_WLG_HOST_CAPABILITIES_V6
        )
    )
    assert section_paths_v12(profile) == section_paths_v11(profile)
    assert section_authority_classes_v12(profile) == section_authority_classes_v11(profile)
    assert purpose_principal_classes_v12(profile) == purpose_principal_classes_v11(profile)
    assert policy_leaf_paths_v12(policy.payload) == policy_leaf_paths_v11(policy.payload)
    schema().validate(raw)
    with pytest.raises(ManifestContractError):
        load_canonical_manifest_v11(policy.canonical_bytes)


@pytest.mark.parametrize("token", ["100", "99.9990", "0.0000000000000000001", "1e2", "5E-1"])
def test_uptime_target_keeps_exact_json_value_and_digest(token: str) -> None:
    raw = SCHEMAS.joinpath("canonical_manifest_v12_base.canonical").read_bytes()
    original = b'"uptime_target_pct":99.5'
    assert raw.count(original) == 1
    policy = load_canonical_manifest_v12(
        raw.replace(original, f'"uptime_target_pct":{token}'.encode())
    )
    assert policy.payload["security"]["serving_surfaces"][0]["uptime_target_pct"] == Decimal(token)
    assert load_canonical_manifest_v12(policy.canonical_bytes) == policy
    assert canonical_manifest_bytes_v12(policy.payload) == policy.canonical_bytes
    assert policy.manifest_digest != load_canonical_manifest_v12(candidate()).manifest_digest


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        None,
        "99.5",
        {},
        [],
        0,
        -1,
        Decimal("100.0000000001"),
        101,
        float("inf"),
        float("nan"),
    ],
)
def test_uptime_target_refuses_out_of_range_nonnumeric_or_nonfinite(value: Any) -> None:
    raw = candidate()
    raw["security"]["serving_surfaces"][1]["uptime_target_pct"] = value
    assert refused(raw).path == "manifest.security.serving_surfaces[1].uptime_target_pct"
    if not isinstance(value, float | Decimal):
        with pytest.raises(ValidationError):
            schema().validate(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("p95_latency_target_ms", 499),
        ("p95_latency_target_ms", 500.0),
        ("p95_latency_target_ms", "500"),
        ("p95_latency_target_ms", True),
        ("p95_window_seconds", 600),
        ("p95_window_seconds", None),
        ("p95_breach_windows", 2),
        ("p95_breach_windows", 3.0),
        ("probe_interval_seconds", 60),
        ("probe_interval_seconds", "300"),
        ("uptime_window_seconds", 0),
        ("uptime_window_seconds", 301),
        ("uptime_window_seconds", -300),
        ("uptime_window_seconds", 600.0),
        ("uptime_window_seconds", True),
        ("uptime_window_seconds", "86400"),
        ("auth_posture", "authenticated"),
        ("auth_posture", None),
        ("runtime_ref", ""),
        ("runtime_ref", "  "),
        ("runtime_ref", " runtime"),
        ("decision_ref", None),
        ("decision_ref", 7),
    ],
)
def test_literals_windows_posture_and_refs_refuse_substitutes(field: str, value: Any) -> None:
    raw = candidate()
    raw["security"]["serving_surfaces"][2][field] = value
    assert refused(raw).path == f"manifest.security.serving_surfaces[2].{field}"
    if not isinstance(value, float):  # JSON Schema counts 500.0 as the integer 500.
        with pytest.raises(ValidationError):
            schema().validate(raw)


@pytest.mark.parametrize(
    "value",
    [
        "http://example.test/",
        "https://example.test",
        "https://user@example.test/",
        "https://example.test/?q=1",
        "https://example.test/#top",
        "ftp://example.test/",
        "example.test/",
        "https:///",
        " https://example.test/",
        "",
        "https://example.test/?",
        "https://example.test/a b",
    ],
)
def test_endpoint_must_be_a_plain_absolute_https_url(value: str) -> None:
    raw = candidate()
    raw["security"]["serving_surfaces"][0]["endpoint_ref"] = value
    assert refused(raw).path == "manifest.security.serving_surfaces[0].endpoint_ref"
    with pytest.raises(ValidationError):
        schema().validate(raw)


def test_declarations_are_exactly_one_per_surface_in_canonical_order() -> None:
    raw = candidate()
    raw["security"]["serving_surfaces"].reverse()
    assert load_canonical_manifest_v12(raw) == load_canonical_manifest_v12(candidate())
    schema().validate(raw)

    raw = candidate()
    raw["security"]["serving_surfaces"][2] = dict(raw["security"]["serving_surfaces"][0])
    assert refused(raw).path == "manifest.security.serving_surfaces[2].surface_key"
    with pytest.raises(ValidationError):
        schema().validate(raw)

    raw = candidate()
    raw["security"]["serving_surfaces"][0]["surface_type"] = "operator_desk"
    assert refused(raw).path == "manifest.security.serving_surfaces[0].surface_type"
    with pytest.raises(ValidationError):
        schema().validate(raw)

    raw = candidate()
    raw["security"]["serving_surfaces"][0]["surface_key"] = "status_page"
    assert refused(raw).path == "manifest.security.serving_surfaces[0].surface_key"


@pytest.mark.parametrize("length", [0, 2, 4])
def test_array_length_and_shape_are_closed(length: int) -> None:
    raw = candidate()
    surfaces = raw["security"]["serving_surfaces"]
    raw["security"]["serving_surfaces"] = (surfaces * 2)[:length]
    assert refused(raw).path == "manifest.security.serving_surfaces"
    with pytest.raises(ValidationError):
        schema().validate(raw)


@pytest.mark.parametrize("field", ["serving_surfaces", "endpoint_ref", "decision_ref", "extra"])
def test_missing_or_extra_fields_refuse(field: str) -> None:
    raw = candidate()
    if field == "serving_surfaces":
        del raw["security"]["serving_surfaces"]
    elif field == "extra":
        raw["security"]["serving_surfaces"][0]["latency_source"] = "cloudfront"
    else:
        del raw["security"]["serving_surfaces"][0][field]
    refused(raw)
    with pytest.raises(ValidationError):
        schema().validate(raw)
    raw = candidate()
    raw["serving_surfaces"] = raw["security"]["serving_surfaces"]
    refused(raw)


def test_v12_capability_is_required_without_changing_v11() -> None:
    raw = candidate()
    raw["compatibility"]["required_capabilities"].remove("canonical_manifest_bytes_v12")
    with pytest.raises(ManifestContractError):
        load_canonical_manifest_v12(raw)
    v11 = json.loads(SCHEMAS.joinpath("canonical_manifest_v11_base.json").read_text())
    before = SCHEMAS.joinpath("canonical_manifest_v11_base.canonical").read_bytes()
    assert load_canonical_manifest_v11(v11).canonical_bytes == before
    assert (
        frozenset({"aeos.product-manifest.v12", "canonical_manifest_bytes_v12"})
        == READER_CAPABILITIES_V12
    )
