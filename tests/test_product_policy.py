"""The closed product-policy manifest: schema, canonical bytes, digests and typed view."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from importlib import resources
from typing import Any

import pytest

from aeos_kernel.product_policy import (
    POLICY_SECTIONS,
    PURPOSE_PRINCIPAL_CLASSES,
    READ_ONLY_PURPOSES,
    SECTION_AUTHORITY_CLASSES,
    SECTION_PATHS,
    CanonicalProductManifest,
    ManifestContractError,
    canonical_manifest_bytes_v1,
    decode_strict_json,
    load_canonical_manifest,
    policy_leaf_paths,
    service_principal_grant_set_digest,
)
from aeos_kernel.registry import Gating

VECTORS = resources.files("aeos_kernel.schemas").joinpath("product_policy")


def fixture_bytes(name: str) -> bytes:
    return VECTORS.joinpath(name).read_bytes()


def payload() -> dict[str, Any]:
    return decode_strict_json(fixture_bytes("canonical_manifest_v1.json"))


def refusal(value: Any) -> ManifestContractError:
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest(value)
    return caught.value


def test_product_manifest_schema_and_canonical_vector() -> None:
    vectors = json.loads(fixture_bytes("canonical_manifest_v1.vectors.json"))
    literal = fixture_bytes(vectors["canonical_bytes"])
    manifest = load_canonical_manifest(fixture_bytes(vectors["input"]))

    assert manifest.canonical_bytes == literal
    assert manifest.manifest_digest == vectors["manifest_sha256"]
    assert hashlib.sha256(literal).hexdigest() == vectors["manifest_sha256"]
    assert manifest.grant_set_digest == vectors["grant_set_sha256"]
    assert service_principal_grant_set_digest(payload()) == vectors["grant_set_sha256"]
    # Loading the canonical bytes again is a fixed point.
    assert load_canonical_manifest(literal).canonical_bytes == literal
    assert not literal.endswith(b"\n") and not literal.startswith(b"\xef\xbb\xbf")

    for key, field in (
        ("product_changed", "product_instance_id"),
        ("phase_changed", "portfolio_phase_revision_id"),
    ):
        changed = payload()
        changed[field] = vectors[key][field]
        digest = hashlib.sha256(canonical_manifest_bytes_v1(changed)).hexdigest()
        assert digest == vectors[key]["manifest_sha256"]
        assert digest != vectors["manifest_sha256"]
    assert (
        vectors["product_changed"]["manifest_sha256"] != vectors["phase_changed"]["manifest_sha256"]
    )


def test_canonicalization_normalizes_only_what_the_schema_names() -> None:
    manifest = load_canonical_manifest(payload())
    body = manifest.payload
    assert body["product_instance_id"] == "0190f2a4-1b2c-7d3e-8f40-5a6b7c8d9e0f"
    assert body["authority"]["citation_rate_floor"] == "0.25"
    assert body["budget_caps"]["model_calls"]["amount"] == "12.5"
    assert body["commercial"]["unit_economics"]["contribution_margin_floor_minor"] == "-500"
    assert body["commercial"]["quote"]["second_signature_above_minor"] == "250000"
    assert body["commercial"]["deliverability"]["complaint_rate_stop"] == "0.001"
    assert body["authority"]["paid_fence"]["brand_term_register_digest"] == "a" * 64
    assert list(body["modules_enabled"]) == ["care", "practice"]
    assert [row["id"] for row in body["authority"]["answer_engines"]] == ["engine_a", "engine_b"]
    assert len(body["service_principal_grants"]) == 2
    # Ordered lists keep the owner's order; human strings keep their bytes.
    assert [row["id"] for row in body["authority"]["target_query_classes"]] == [
        "how_to_plan",
        "what_to_bring",
    ]
    assert list(body["tone_profile"]["forbidden_phrases"]) == ["guaranteed cure", "Example Phrase"]
    assert body["tone_profile"]["voice"] == "Plain, warm, exact — Example voice."
    assert "—".encode() in manifest.canonical_bytes


def mutate(path: str, value: Any, *, delete: bool = False) -> dict[str, Any]:
    body = payload()
    target = body
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    if delete:
        del target[parts[-1]]
    else:
        target[parts[-1]] = value
    return body


@pytest.mark.parametrize(
    ("change", "reason", "path"),
    [
        (lambda: mutate("surprise", 1), "manifest_schema_invalid", "manifest.surprise"),
        (
            lambda: mutate("authority.paid_fence.extra", True),
            "manifest_schema_invalid",
            "manifest.authority.paid_fence.extra",
        ),
        (
            lambda: mutate("fcra_posture", None, delete=True),
            "manifest_schema_invalid",
            "manifest.fcra_posture",
        ),
        (
            lambda: mutate("authority.citation_rate_floor", 0.25),
            "manifest_schema_invalid",
            "manifest.authority.citation_rate_floor",
        ),
        (
            lambda: mutate("authority.citation_rate_floor", 1),
            "manifest_schema_invalid",
            "manifest.authority.citation_rate_floor",
        ),
        (
            lambda: mutate("authority.citation_rate_floor", "1.5"),
            "manifest_schema_invalid",
            "manifest.authority.citation_rate_floor",
        ),
        (
            lambda: mutate("authority.citation_rate_floor", "1e-1"),
            "manifest_schema_invalid",
            "manifest.authority.citation_rate_floor",
        ),
        (
            lambda: mutate("authority.earned_citations_floor", True),
            "manifest_schema_invalid",
            "manifest.authority.earned_citations_floor",
        ),
        (
            lambda: mutate("authority.measurement_window_days", 0),
            "manifest_schema_invalid",
            "manifest.authority.measurement_window_days",
        ),
        (
            lambda: mutate("modules_enabled", []),
            "manifest_schema_invalid",
            "manifest.modules_enabled",
        ),
        (
            lambda: mutate("correction_policy.clock", "weekdays"),
            "manifest_schema_invalid",
            "manifest.correction_policy.clock",
        ),
        (
            lambda: mutate("release_policy", {"min_overall": 0.9}),
            "manifest_schema_invalid",
            "manifest.release_policy.min_overall",
        ),
        (
            lambda: mutate("gating.judgment_confidence_gate", "0"),
            "manifest_schema_invalid",
            "manifest.gating.judgment_confidence_gate",
        ),
        (
            lambda: mutate("effective_interval.starts_at", "2026-10-01T00:00:00+00:00"),
            "manifest_schema_invalid",
            "manifest.effective_interval.starts_at",
        ),
        (
            lambda: mutate("effective_interval.ends_before", "2026-10-01T00:00:00Z"),
            "manifest_schema_invalid",
            "manifest.effective_interval.ends_before",
        ),
        (
            lambda: mutate("compatibility.max_reader", "0.9.0"),
            "manifest_schema_invalid",
            "manifest.compatibility.max_reader",
        ),
        (
            lambda: mutate("schema_version", "aeos.product-manifest.v2"),
            "manifest_incompatible",
            "manifest.schema_version",
        ),
        (
            lambda: mutate(
                "authority.target_query_classes",
                [{"id": "a", "question": "One?"}, {"id": "a", "question": "Two?"}],
            ),
            "manifest_schema_invalid",
            "manifest.authority.target_query_classes[1]",
        ),
        (
            lambda: mutate(
                "service_principal_grants",
                [
                    {
                        "purpose": "paid_effect",
                        "principal_id": "w",
                        "principal_class": "distribution_worker",
                    }
                ],
            ),
            "manifest_grant_mismatch",
            "manifest.service_principal_grants[0].principal_class",
        ),
        (
            lambda: mutate(
                "service_principal_grants",
                [
                    {
                        "purpose": "everything",
                        "principal_id": "w",
                        "principal_class": "distribution_worker",
                    }
                ],
            ),
            "manifest_grant_mismatch",
            "manifest.service_principal_grants[0].purpose",
        ),
    ],
)
def test_closed_schema_refusals_name_the_path_never_the_value(
    change: Any, reason: str, path: str
) -> None:
    error = refusal(change())
    assert error.reason_code == reason
    assert error.path == path


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b"\xff\xfe{}",
        b"\xef\xbb\xbf{}",
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"[1,2]",
        b'{"a":',
    ],
)
def test_strict_decoding_refuses_what_json_libraries_forgive(raw: bytes) -> None:
    assert refusal(raw).reason_code == "manifest_schema_invalid"


def test_an_unpaired_surrogate_is_refused() -> None:
    body = fixture_bytes("canonical_manifest_v1.json").replace(
        b"Example voice.", b"Example \\ud800 voice."
    )
    error = refusal(body)
    assert error.path == "manifest.tone_profile.voice"


def test_a_revision_row_cannot_store_another_products_payload() -> None:
    raw = fixture_bytes("canonical_manifest_v1.json")
    manifest = load_canonical_manifest(raw)
    accepted = load_canonical_manifest(
        raw,
        product_id=manifest.product_instance_id.upper(),
        phase_revision_id=manifest.portfolio_phase_revision_id,
        manifest_version=manifest.manifest_version,
    )
    assert accepted.manifest_digest == manifest.manifest_digest
    for kwargs in (
        {"product_id": "0190f2a4-1b2c-7d3e-8f40-5a6b7c8d9e10"},
        {"phase_revision_id": "0190f2a4-1b2c-7d3e-8f40-000000000002"},
        {"manifest_version": "another"},
    ):
        with pytest.raises(ManifestContractError) as caught:
            load_canonical_manifest(raw, **kwargs)  # type: ignore[arg-type]
        assert caught.value.reason_code == "manifest_identity_mismatch"


def test_effective_interval_is_start_inclusive_and_end_exclusive() -> None:
    manifest = load_canonical_manifest(
        mutate("effective_interval.ends_before", "2026-11-01T00:00:00Z")
    )
    assert not manifest.effective_at(datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC))
    assert manifest.effective_at(datetime(2026, 10, 1, tzinfo=UTC))
    assert manifest.effective_at(datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC))
    assert not manifest.effective_at(datetime(2026, 11, 1, tzinfo=UTC))
    assert manifest.effective_time_decision_ref == "example://decision/interval-1"
    open_ended = load_canonical_manifest(payload())
    assert open_ended.effective_until is None
    assert open_ended.effective_at(datetime(2099, 1, 1, tzinfo=UTC))


def test_a_grant_is_an_exact_tuple_never_class_membership() -> None:
    manifest = load_canonical_manifest(payload())
    assert manifest.grants_principal(
        purpose="paid_effect",
        principal_id="example-worker-1",
        principal_class="marketing_effects_worker",
    )
    assert not manifest.grants_principal(
        purpose="paid_effect",
        principal_id="example-worker-2",
        principal_class="marketing_effects_worker",
    )
    assert not manifest.grants_principal(
        purpose="outreach_copy_send",
        principal_id="example-worker-1",
        principal_class="marketing_effects_worker",
    )
    changed = payload()
    changed["service_principal_grants"] = changed["service_principal_grants"][:1]
    assert load_canonical_manifest(changed).grant_set_digest != manifest.grant_set_digest


def test_reader_compatibility_is_a_closed_window() -> None:
    manifest = load_canonical_manifest(payload())
    assert manifest.reader_compatible("1.0.0")
    assert manifest.reader_compatible("1.9.0")
    assert not manifest.reader_compatible("2.0.0")
    assert not manifest.reader_compatible("0.9.9")
    unknown = mutate("compatibility.required_capabilities", ["time_travel_v1"])
    assert not load_canonical_manifest(unknown).reader_compatible()


def test_the_purpose_matrix_is_the_closed_nineteen_rows() -> None:
    assert len(PURPOSE_PRINCIPAL_CLASSES) == 19
    assert len(set(PURPOSE_PRINCIPAL_CLASSES.values())) == 19
    assert {
        "authority_measurement",
        "channel_of_record",
        "paid_plan",
        "readback",
    } == READ_ONLY_PURPOSES


def test_every_policy_path_belongs_to_exactly_one_approval_section() -> None:
    covered = [path for paths in SECTION_PATHS.values() for path in paths]
    assert len(covered) == len(set(covered))
    assert set(covered) == set(policy_leaf_paths(load_canonical_manifest(payload()).payload))
    assert set(SECTION_PATHS) == set(SECTION_AUTHORITY_CLASSES) == set(POLICY_SECTIONS)
    assert "whole_manifest" not in POLICY_SECTIONS


def test_a_section_view_returns_only_its_paths() -> None:
    manifest = load_canonical_manifest(payload())
    assert (
        manifest.section("paid_fence")["authority.paid_fence"]["allow_third_party_operator_terms"]
        is False
    )
    assert set(manifest.section("budget")) == {"budget_caps", "authority.probe_budget"}
    with pytest.raises(ValueError):
        manifest.section("whole_manifest")


def test_the_legacy_manifest_adapter_carries_values_without_inventing_any() -> None:
    manifest = load_canonical_manifest(payload())
    legacy = manifest.as_product_manifest("example-product")
    assert legacy.version == "example-2026.09.27"
    assert legacy.gating == Gating(judgment_confidence_gate=0.8)
    assert legacy.release_rule("coverage_thresholds", {}) == {"min_overall": "1.0"}
    assert legacy.budget_caps["probes"] == {"amount": "40", "unit": "probe", "window": "week"}
    assert legacy.modules_enabled == ("care", "practice")


def test_the_canonical_view_is_immutable() -> None:
    manifest = load_canonical_manifest(payload())
    assert isinstance(manifest, CanonicalProductManifest)
    with pytest.raises(TypeError):
        manifest.payload["manifest_version"] = "edited"  # type: ignore[index]
    snapshot = copy.deepcopy(payload())
    load_canonical_manifest(snapshot)
    assert snapshot == payload()
