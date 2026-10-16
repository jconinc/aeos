"""O01 / REQ-SEC-011/034/055: canonical objectives with immutable prior readers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel.authority import AuthorityRecord, ScopeSelector
from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import (
    PolicyAuthorityStatus,
    authorize_policy_command,
    command_section,
    required_authority_class,
)
from aeos_kernel.product_policy import ManifestContractError
from aeos_kernel.product_policy_v2 import REQUIRED_SWEEP_HOST_CAPABILITIES_V2
from aeos_kernel.product_policy_v5 import REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
from aeos_kernel.product_policy_v6 import REQUIRED_WLG_HOST_CAPABILITIES_V6
from aeos_kernel.product_policy_v9 import (
    load_canonical_manifest_v9,
    purpose_principal_classes_v9,
    section_authority_classes_v9,
    section_paths_v9,
)
from aeos_kernel.product_policy_v10 import (
    READER_CAPABILITIES_V10,
    SCHEMA_VERSION_V10,
    canonical_manifest_bytes_v10,
    load_canonical_manifest_v10,
    normalize_manifest_payload_v10,
    policy_leaf_paths_v10,
    purpose_principal_classes_v10,
    section_authority_classes_v10,
    section_paths_v10,
)

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")
HOST_CAPABILITIES = (
    REQUIRED_SWEEP_HOST_CAPABILITIES_V2
    | REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
    | REQUIRED_WLG_HOST_CAPABILITIES_V6
)
SLO_KEYS = ("rpo_minutes", "rto_minutes", "audit_retention_days", "delivery_receipt_sla_minutes")
READER_GRANT = {
    "purpose": "operational_objectives",
    "principal_id": "fictional:operational_objectives",
    "principal_class": "operational_objectives_reader",
}


def candidate(profile: str = "base") -> dict[str, Any]:
    return dict(json.loads(SCHEMAS.joinpath(f"canonical_manifest_v10_{profile}.json").read_text()))


def schema() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(SCHEMAS.joinpath("product_manifest_v10.schema.json").read_text())
    )


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_v10_exact_packaged_bytes_and_security_projection(profile: str) -> None:
    payload = candidate(profile)
    policy = load_canonical_manifest_v10(payload)
    vector = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v10_{profile}.vectors.json").read_text()
    )
    assert policy.canonical_bytes == SCHEMAS.joinpath(vector["canonical_bytes"]).read_bytes()
    assert canonical_manifest_bytes_v10(payload) == policy.canonical_bytes
    assert policy.manifest_digest == vector["manifest_sha256"]
    assert policy.grant_set_digest == vector["grant_set_sha256"]
    assert load_canonical_manifest_v10(policy.canonical_bytes) == policy
    assert normalize_manifest_payload_v10(payload) == json.loads(policy.canonical_bytes)
    assert set(policy.payload["security"]["slo_targets"]) == set(SLO_KEYS)
    assert "audit_retention_days" not in policy.payload["security"]
    security = policy.product_security("example")
    assert (
        security.audit_retention_days == payload["security"]["slo_targets"]["audit_retention_days"]
    )
    assert security.key_rotation_days == payload["security"]["key_rotation_days"]
    assert security.manifest_digest == policy.manifest_digest
    assert security.selected_hosts is not None
    assert security.selected_hosts[0].host == payload["security"]["selected_hosts"][0]["host"]
    assert policy.section("product_security") == {
        "security": json.loads(policy.canonical_bytes)["security"]
    }
    assert policy.reader_compatible(available_capabilities=HOST_CAPABILITIES)
    assert not policy.reader_compatible("9.0.0", available_capabilities=HOST_CAPABILITIES)
    with pytest.raises(TypeError, match="immutable"):
        policy.payload["security"]["slo_targets"]["rpo_minutes"] = 99
    assert payload == candidate(profile)
    schema().validate(payload)


@pytest.mark.parametrize("key", ["rpo_minutes", "rto_minutes"])
@pytest.mark.parametrize("value", [0, 1, 10**30])
def test_recovery_targets_allow_nonnegative_integers(key: str, value: int) -> None:
    payload = candidate()
    payload["security"]["slo_targets"][key] = value
    policy = load_canonical_manifest_v10(payload)
    assert policy.payload["security"]["slo_targets"][key] == value
    assert load_canonical_manifest_v10(policy.canonical_bytes) == policy
    schema().validate(payload)


@pytest.mark.parametrize("value", [1, 90])
def test_retention_positive_integer_boundary(value: int) -> None:
    payload = candidate()
    payload["security"]["slo_targets"]["audit_retention_days"] = value
    policy = load_canonical_manifest_v10(payload)
    assert policy.product_security("example").audit_retention_days == value
    schema().validate(payload)


@pytest.mark.parametrize("value", [0.125, 1, 1.0, 2.5])
def test_delivery_accepts_finite_positive_number_in_mapping_and_bytes(value: int | float) -> None:
    payload = candidate()
    payload["security"]["slo_targets"]["delivery_receipt_sla_minutes"] = value
    policy = load_canonical_manifest_v10(payload)
    assert policy.payload["security"]["slo_targets"]["delivery_receipt_sla_minutes"] == value
    assert load_canonical_manifest_v10(json.dumps(payload).encode()) == policy
    assert load_canonical_manifest_v10(policy.canonical_bytes) == policy
    schema().validate(payload)


def delivery_source(token: str) -> bytes:
    raw = SCHEMAS.joinpath("canonical_manifest_v10_base.canonical").read_bytes()
    key = b'"delivery_receipt_sla_minutes":1'
    assert raw.count(key) == 1
    return raw.replace(key, b'"delivery_receipt_sla_minutes":' + token.encode("ascii"))


@pytest.mark.parametrize("source_form", ["bytes", "mapping"])
@pytest.mark.parametrize(
    "token",
    [
        "1",
        "1.0",
        "0.1",
        "0.125",
        "1.0000000000000001",
        "9007199254740993.0",
        "1e-400",
        "1e400",
        str(10**400),
    ],
)
def test_delivery_preserves_exact_numeric_value_and_payload_roundtrip(
    token: str, source_form: str
) -> None:
    """O01-R1: no rounding, overflow or underflow through a binary float."""
    expected = Decimal(token)
    payload = candidate()
    payload["security"]["slo_targets"]["delivery_receipt_sla_minutes"] = expected
    policy = load_canonical_manifest_v10(
        delivery_source(token) if source_form == "bytes" else payload
    )
    assert policy.payload["security"]["slo_targets"]["delivery_receipt_sla_minutes"] == expected
    decoded = json.loads(policy.canonical_bytes, parse_float=Decimal)
    assert decoded["security"]["slo_targets"]["delivery_receipt_sla_minutes"] == expected
    assert load_canonical_manifest_v10(policy.canonical_bytes) == policy
    assert load_canonical_manifest_v10(policy.payload) == policy
    assert canonical_manifest_bytes_v10(policy.payload) == policy.canonical_bytes
    assert normalize_manifest_payload_v10(policy.payload) == decoded
    assert (
        policy.section("product_security")["security"]["slo_targets"]
        == decoded["security"]["slo_targets"]
    )
    assert payload["security"]["slo_targets"]["delivery_receipt_sla_minutes"] == expected


@pytest.mark.parametrize(
    "tokens",
    [
        ("1", "1.0", "1e0", "10e-1"),
        ("9007199254740993", "9007199254740993.0", "90071992547409930e-1"),
        ("1e400", str(10**400), "10e399"),
        ("1e-400", "10e-401", "0." + "0" * 399 + "1"),
    ],
)
def test_equivalent_delivery_number_spellings_share_canonical_identity(
    tokens: tuple[str, ...],
) -> None:
    policies = [load_canonical_manifest_v10(delivery_source(token)) for token in tokens]
    assert len({policy.canonical_bytes for policy in policies}) == 1
    assert len({policy.manifest_digest for policy in policies}) == 1


def test_distinct_delivery_values_keep_distinct_digests_independent_of_decimal_context() -> None:
    tokens = ("1", "1.0000000000000001", "9007199254740993.0", "1e-400", "2e-400", "1e400")
    policies = [load_canonical_manifest_v10(delivery_source(token)) for token in tokens]
    assert len({policy.canonical_bytes for policy in policies}) == len(tokens)
    assert len({policy.manifest_digest for policy in policies}) == len(tokens)
    assert len({policy.grant_set_digest for policy in policies}) == 1
    with localcontext() as context:
        context.prec = 2
        assert [load_canonical_manifest_v10(delivery_source(token)) for token in tokens] == policies


@pytest.mark.parametrize("value", [0.1, 0.125, 1.0, 10**400])
def test_mapping_numbers_agree_with_their_json_spelling(value: int | float) -> None:
    payload = candidate()
    payload["security"]["slo_targets"]["delivery_receipt_sla_minutes"] = value
    policy = load_canonical_manifest_v10(payload)
    assert policy == load_canonical_manifest_v10(json.dumps(payload).encode())
    assert policy.payload["security"]["slo_targets"]["delivery_receipt_sla_minutes"] == Decimal(
        str(value)
    )


@pytest.mark.parametrize("token", ["NaN", "sNaN", "Infinity", "-Infinity", "0", "-1"])
def test_exact_decimal_mapping_values_still_require_positive_finite_numbers(token: str) -> None:
    payload = candidate()
    payload["security"]["slo_targets"]["delivery_receipt_sla_minutes"] = Decimal(token)
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v10(payload)
    assert caught.value.reason_code == "manifest_schema_invalid"
    assert caught.value.path == "manifest.security.slo_targets.delivery_receipt_sla_minutes"


@pytest.mark.parametrize("key", SLO_KEYS)
@pytest.mark.parametrize("value", [True, False, None, "1", "1 minute", {}, []])
def test_every_target_refuses_non_numeric_values(key: str, value: Any) -> None:
    payload = candidate()
    payload["security"]["slo_targets"][key] = value
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v10(payload)
    assert caught.value.reason_code == "manifest_schema_invalid"
    assert caught.value.path == f"manifest.security.slo_targets.{key}"
    with pytest.raises(ValidationError):
        schema().validate(payload)


@pytest.mark.parametrize("key", SLO_KEYS)
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), -float("inf")])
def test_every_target_refuses_negative_or_nonfinite_numbers(key: str, value: int | float) -> None:
    payload = candidate()
    payload["security"]["slo_targets"][key] = value
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v10(payload)
    assert caught.value.path == f"manifest.security.slo_targets.{key}"


@pytest.mark.parametrize("key", SLO_KEYS[:3])
@pytest.mark.parametrize("value", [0.5, 1.0])
def test_integer_fields_refuse_fractional_and_integral_float_tokens(key: str, value: float) -> None:
    # JSON Schema's mathematical integer type accepts 1.0; the parser enforces the token rule.
    payload = candidate()
    payload["security"]["slo_targets"][key] = value
    with pytest.raises(ContractError, match="must be a JSON integer"):
        load_canonical_manifest_v10(payload)
    with pytest.raises(ContractError, match="must be a JSON integer"):
        load_canonical_manifest_v10(json.dumps(payload).encode())


@pytest.mark.parametrize("key", ["audit_retention_days", "delivery_receipt_sla_minutes"])
def test_positive_targets_refuse_zero(key: str) -> None:
    payload = candidate()
    payload["security"]["slo_targets"][key] = 0
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v10(payload)
    assert caught.value.path == f"manifest.security.slo_targets.{key}"
    with pytest.raises(ValidationError):
        schema().validate(payload)


@pytest.mark.parametrize("key", SLO_KEYS)
def test_each_target_is_required_and_wrong_unit_names_refuse(key: str) -> None:
    payload = candidate()
    targets = payload["security"]["slo_targets"]
    value = targets.pop(key)
    with pytest.raises(ManifestContractError, match="is required") as caught:
        load_canonical_manifest_v10(payload)
    assert caught.value.path == f"manifest.security.slo_targets.{key}"
    targets[f"{key}_seconds"] = value
    with pytest.raises(ManifestContractError, match="is not a field of this schema") as caught:
        load_canonical_manifest_v10(payload)
    assert caught.value.path == f"manifest.security.slo_targets.{key}_seconds"
    with pytest.raises(ValidationError):
        schema().validate(payload)


@pytest.mark.parametrize("value", [None, {}, [], "minutes", {"extra": 1}])
def test_slo_block_is_required_and_closed(value: Any) -> None:
    payload = candidate()
    payload["security"]["slo_targets"] = value
    with pytest.raises(ContractError):
        load_canonical_manifest_v10(payload)
    with pytest.raises(ValidationError):
        schema().validate(payload)


def test_extra_target_and_both_retention_locations_refuse() -> None:
    payload = candidate()
    payload["security"]["slo_targets"]["rpo_seconds"] = 1
    with pytest.raises(ContractError, match="is not a field of this schema"):
        load_canonical_manifest_v10(payload)
    del payload["security"]["slo_targets"]["rpo_seconds"]
    payload["security"]["audit_retention_days"] = 90
    with pytest.raises(ContractError, match="belongs only in slo_targets"):
        load_canonical_manifest_v10(payload)
    with pytest.raises(ValidationError):
        schema().validate(payload)
    del payload["security"]["slo_targets"]
    with pytest.raises(ContractError, match="belongs only in slo_targets"):
        load_canonical_manifest_v10(payload)


def test_v10_decoder_retains_strict_json_and_inherited_integer_rules() -> None:
    raw = SCHEMAS.joinpath("canonical_manifest_v10_base.canonical").read_bytes()
    for source, message in [
        (b'{"schema_version":"x","schema_version":"y"}', "appears twice"),
        (b"\xff", "not UTF-8"),
        (b"\xef\xbb\xbf" + raw, "byte-order mark"),
        (b"[]", "must be a JSON object"),
        (b"{", "not valid JSON"),
        (
            raw.replace(b'"delivery_receipt_sla_minutes":1', b'"delivery_receipt_sla_minutes":NaN'),
            "not JSON",
        ),
    ]:
        with pytest.raises(ContractError, match=message):
            load_canonical_manifest_v10(source)
    payload = candidate()
    payload["security"]["key_rotation_days"] = 1.0
    with pytest.raises(ContractError, match="must be a JSON integer"):
        load_canonical_manifest_v10(json.dumps(payload).encode())


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_v10_maps_preserve_inherited_sections_and_own_all_targets(profile: str) -> None:
    assert section_paths_v10(profile) == section_paths_v9(profile)
    assert section_authority_classes_v10(profile) == section_authority_classes_v9(profile)
    paths = section_paths_v10(profile)
    assert section_authority_classes_v10(profile)["product_security"] == "security_role"
    for key in SLO_KEYS:
        leaf = f"security.slo_targets.{key}"
        assert [
            section
            for section, roots in paths.items()
            if any(leaf == root or leaf.startswith(root + ".") for root in roots)
        ] == ["product_security"]
    assert set(policy_leaf_paths_v10(candidate(profile))) == {
        path for roots in paths.values() for path in roots if path != "commercial.paid_pilot_policy"
    }
    assert purpose_principal_classes_v10(profile) == {
        **purpose_principal_classes_v9(profile),
        "operational_objectives": "operational_objectives_reader",
    }
    assert (
        required_authority_class(
            "record_manifest_decision", "product_security", schema_version=SCHEMA_VERSION_V10
        )
        == "security_role"
    )


def test_operational_reader_requires_exact_grant_and_cannot_approve_security() -> None:
    payload = candidate()
    payload["service_principal_grants"] = [READER_GRANT.copy()]
    policy = load_canonical_manifest_v10(payload)
    assert policy.grants_principal(**READER_GRANT)
    assert not policy.grants_principal(**{**READER_GRANT, "principal_id": "another-reader"})
    assert not policy.grants_principal(**{**READER_GRANT, "purpose": "paid_effect"})
    payload["service_principal_grants"] = []
    assert not load_canonical_manifest_v10(payload).grants_principal(**READER_GRANT)
    payload["service_principal_grants"] = [{**READER_GRANT, "principal_class": "security_role"}]
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v10(payload)
    assert caught.value.reason_code == "manifest_grant_mismatch"
    with pytest.raises(ContractError, match="one policy section"):
        command_section(
            "record_manifest_decision", "operational_objectives", schema_version=SCHEMA_VERSION_V10
        )
    args = {
        "subject_id": policy.product_instance_id,
        "command": "record_manifest_decision",
        "section": "product_security",
        "principal_id": READER_GRANT["principal_id"],
    }
    record = AuthorityRecord(
        authority_id="fictional-read-only",
        vertical_id="example",
        tenant_id="example",
        layer="law_or_policy",
        status="confirmed_authority",
        selector=ScopeSelector("exact_attributes", args),
        value={
            "authority_class": "operational_objectives_reader",
            "decision_ref": "example://read",
        },
    )
    result = authorize_policy_command(
        [record],
        vertical_id="example",
        tenant_id="example",
        **args,
        at=datetime(2026, 10, 16, tzinfo=UTC),
        schema_version=SCHEMA_VERSION_V10,
    )
    assert result.status is PolicyAuthorityStatus.CLASS_MISMATCH


@pytest.mark.parametrize("capability", sorted(READER_CAPABILITIES_V10))
def test_v10_requires_its_own_capabilities(capability: str) -> None:
    payload = candidate()
    payload["compatibility"]["required_capabilities"].remove(capability)
    with pytest.raises(ContractError, match="every v10 capability"):
        load_canonical_manifest_v10(payload)


@pytest.mark.parametrize("key", ["product_id", "phase_revision_id", "manifest_version"])
def test_v10_keeps_stored_identity_checks(key: str) -> None:
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v10(candidate(), **{key: "different"})
    assert caught.value.reason_code == "manifest_identity_mismatch"


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_v9_refuses_v10_and_preserves_original_digest(profile: str) -> None:
    raw = SCHEMAS.joinpath(f"canonical_manifest_v9_{profile}.canonical").read_bytes()
    prior = load_canonical_manifest_v9(raw)
    expected = {
        "base": "be4c8976e63a76ff2d92e07c8fbc36155ad8f0a881bf5d75fc2f5d12e047d1a6",
        "correction_sweep": "cbf45fa8e1c25de98473ae377f349fb259f84f35c17c2b024551ffd7b61fe26e",
    }
    assert prior.manifest_digest == expected[profile]
    assert prior.canonical_bytes == raw
    with pytest.raises(ContractError, match="not a v9 schema"):
        load_canonical_manifest_v9(candidate(profile))
    with pytest.raises(ContractError, match="not a v10 schema"):
        load_canonical_manifest_v10(raw)


def test_target_change_changes_only_policy_digest_and_preserves_input() -> None:
    payload = candidate()
    before = load_canonical_manifest_v10(payload)
    payload["security"]["slo_targets"]["rpo_minutes"] += 1
    after = load_canonical_manifest_v10(payload)
    assert before.manifest_digest != after.manifest_digest
    assert before.grant_set_digest == after.grant_set_digest
    assert isinstance(before.payload["security"]["slo_targets"], Mapping)
