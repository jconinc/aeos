"""Focused PB-195 v2 correction-sweep contract controls."""

from __future__ import annotations

import copy
import hashlib
import json
from importlib import resources
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel.errors import ContractError
from aeos_kernel.product_policy import (
    POLICY_SECTIONS,
    SECTION_AUTHORITY_CLASSES,
    SECTION_PATHS,
    ManifestContractError,
    decode_strict_json,
    load_canonical_manifest,
)
from aeos_kernel.product_policy_v2 import (
    POLICY_SECTIONS_V2,
    PURPOSE_PRINCIPAL_CLASSES_V2,
    READER_CAPABILITIES_V2,
    REQUIRED_SWEEP_HOST_CAPABILITIES_V2,
    SECTION_AUTHORITY_CLASSES_V2,
    SECTION_PATHS_V2,
    SWEEP_CAPABILITY,
    SWEEP_PRINCIPAL_CLASS,
    SWEEP_PURPOSE,
    SWEEP_SCOPE,
    canonical_manifest_bytes_v2,
    load_canonical_manifest_v2,
    policy_leaf_paths_v2,
    service_principal_grant_set_digest_v2,
)

_SCHEMAS = resources.files("aeos_kernel.schemas").joinpath("product_policy")

# PB-195 v2 C14 literal interchange vector, prepared from the approved amendment's closed
# field table.  Its input is intentionally already canonical: a future AEOS or host reader must
# reproduce these exact bytes and fixed SHA-256 values without consulting this test's builder.
V2_VECTOR_CANONICAL = (
    b'{"approval_policy_ref":"example://approval/policy-1","authority":{"answer_engines":[{"id'
    b'":"engine_a"},{"id":"engine_b"}],"citation_rate_floor":"0.25","earned_citations_floor":3'
    b',"measurement_window_days":28,"owned_audience":{"double_opt_in":true,"lawful_basis_polic'
    b'y":"example://policy/lawful-basis","suppression_list_ref":"example://suppression/list-1"'
    b'},"paid_fence":{"allow_brand_terms":true,"allow_category_terms":true,"allow_third_party_'
    b'operator_terms":false,"brand_term_register_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    b'aaaaaaaaaaaaaaaaaaaaaaaaaaaa","brand_term_register_ref":"example://terms/brand","brand_t'
    b'erm_register_version":"brand-1","category_term_register_digest":"bbbbbbbbbbbbbbbbbbbbbbb'
    b'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","category_term_register_ref":"example://terms'
    b'/category","category_term_register_version":"category-1","operator_term_register_digest"'
    b':"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","operator_term_regis'
    b'ter_ref":"example://terms/operator","operator_term_register_version":"operator-1"},"prob'
    b'e_budget":{"permitted_model_refs":["example-model-a","example-model-b"],"probes_per_engi'
    b'ne_per_query_class_per_window":4},"source_diversity_min":2,"target_query_classes":[{"id"'
    b':"how_to_plan","question":"How do I plan care for a parent?"},{"id":"what_to_bring","que'
    b'stion":"What should I bring to an appointment?"}],"wedge":true},"budget_caps":{"model_ca'
    b'lls":{"amount":"12.5","currency":"USD","unit":"usd","window":"month"},"probes":{"amount"'
    b':"40","unit":"probe","window":"week"}},"commercial":{"deliverability":{"bounce_rate_stop'
    b'":"0.05","complaint_rate_stop":"0.001","minimum_sent":200,"window_days":7},"quote":{"sec'
    b'ond_signature_above_minor":"250000"},"renewal_attention":{"review_lead_days":30},"unit_e'
    b'conomics":{"contribution_margin_floor_minor":"-500","contribution_window_days":90}},"com'
    b'patibility":{"max_reader":"2.9.0","min_reader":"2.0.0","required_capabilities":["aeos.pr'
    b'oduct-manifest.v2","canonical_manifest_bytes_v2","correction_sweep_queue_admission_v2","'
    b'correction_sweep_source_binding_v2","correction_sweep_worker_revalidation_v2","effective'
    b'_interval_v2","purpose_principal_class_matrix_v2","service_principal_grant_set_digest_v2'
    b'","support_manifest_scope_proposal_v2"]},"content_policy":{"review_age_days":180},"corre'
    b'ction_policy":{"acknowledge_within_days":2,"an_overdue_correction_stops_publication":tru'
    b'e,"clock":"business_days","resolve_within_days":10},"correction_sweep":{"access_policy_r'
    b'ef":"example://access/sweep-7","calendar":{"artifact_id":"business-calendar","digest":"f'
    b'fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff","dst_fold_rule":"earlie'
    b'r","dst_gap_rule":"next_valid","holidays":["2026-11-26","2026-12-25"],"iana_time_zone":"'
    b'America/New_York","version":"2026.10","working_days":["friday","monday","thursday","tues'
    b'day","wednesday"]},"correction_owner_policy_revision":"example://correction-owner/revisi'
    b'on-7","effective_interval":{"decision_ref":"example://decision/source-sweep-interval","e'
    b'nds_before":null,"starts_at":"2026-10-01T00:00:00Z"},"fact_authority_rule":"example://so'
    b'urce-policy/fact-authority-7","incident_policy_ref":"example://incident/sweep-7","legal_'
    b'hold_policy_ref":"example://legal-hold/sweep-7","lookback_algorithm_version":"calendar-m'
    b'onths-v1","lookback_months":12,"policy_id":"source-sweep-policy","privacy_policy_refs":['
    b'"example://privacy/sweep-7"],"retention_policy_ref":"example://retention/sweep-7","sourc'
    b'e_policy_revisions":["example://source-policy/revision-7"],"version":"7"},"credential_sc'
    b'opes":{"example_mail":["draft","send"],"support:correction_sweep":["run_correction_sweep'
    b'"]},"effective_interval":{"decision_ref":"example://decision/interval-1","ends_before":n'
    b'ull,"starts_at":"2026-10-01T00:00:00Z"},"family_overrides":{},"fcra_posture":"outside_fc'
    b'ra","gating":{"graduation_count":25,"judgment_confidence_gate":"0.8","park_ttl_hours":72'
    b',"seed_approval_count":3,"stale_claim_days":30},"liability_class":"B","manifest_version"'
    b':"example-2026.09.27","modules_enabled":["care","practice"],"portfolio_phase_revision_id'
    b'":"0190f2a4-1b2c-7d3e-8f40-000000000001","product_instance_id":"0190f2a4-1b2c-7d3e-8f40-'
    b'5a6b7c8d9e0f","release_policy":{"coverage_thresholds":{"min_overall":"1.0"}},"schema_ver'
    b'sion":"aeos.product-manifest.v2","service_principal_grants":[{"principal_class":"correct'
    b'ion_sweep_service","principal_id":"sweep-service-fixture","purpose":"correction_sweep"},'
    b'{"principal_class":"marketing_effects_worker","principal_id":"example-worker-1","purpose'
    b'":"paid_effect"},{"principal_class":"product_policy_read_client","principal_id":"example'
    b'-reader-1","purpose":"readback"}],"source_bindings":{"correction_sweep":{"digest":"eeeee'
    b'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","version":"source-policy-7"'
    b'},"mailbox_registry":{"digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddd'
    b'dddddddd","version":"example-registry-1"}},"task_generation_policy":{"max_open":5},"tone'
    b'_profile":{"allowed_claim_templates":["example://claims/template-b","example://claims/te'
    b'mplate-a"],"forbidden_phrases":["guaranteed cure","Example Phrase"],"voice":"Plain, warm'
    b', exact \xe2\x80\x94 Example voice."},"wlg_sync_policy":{}}'
)
V2_VECTOR_INPUT = V2_VECTOR_CANONICAL
V2_VECTOR_MANIFEST_SHA256 = "0ab53c67e36cdff10e81fdc4bb056484a44c344d3ecd6131c7338e931d21f6af"
V2_VECTOR_GRANT_SET_SHA256 = "019f588957022357771ce730c5c44e5e754805786f1b98c2bfc7ce06ea319cac"


def test_v2_literal_interchange_vector_has_fixed_bytes_and_digests() -> None:
    """PB-195 C14 vector from John's approved v2 closed field table; values stay literal."""

    manifest = load_canonical_manifest_v2(V2_VECTOR_INPUT)

    assert manifest.canonical_bytes == V2_VECTOR_CANONICAL
    assert manifest.manifest_digest == V2_VECTOR_MANIFEST_SHA256
    assert manifest.grant_set_digest == V2_VECTOR_GRANT_SET_SHA256
    assert hashlib.sha256(V2_VECTOR_CANONICAL).hexdigest() == V2_VECTOR_MANIFEST_SHA256
    vector_payload = decode_strict_json(V2_VECTOR_INPUT)
    assert canonical_manifest_bytes_v2(vector_payload) == V2_VECTOR_CANONICAL
    assert service_principal_grant_set_digest_v2(vector_payload) == V2_VECTOR_GRANT_SET_SHA256


def test_v2_packaged_vector_and_schema_freeze_the_c14_interchange_contract() -> None:
    """PB-195 C14 publishes the Wema consumer's fixed v2 interchange resource set."""

    vectors = json.loads(_SCHEMAS.joinpath("canonical_manifest_v2.vectors.json").read_text())
    literal = _SCHEMAS.joinpath(vectors["canonical_bytes"]).read_bytes()
    input_bytes = _SCHEMAS.joinpath(vectors["input"]).read_bytes()
    schema = json.loads(_SCHEMAS.joinpath(vectors["schema"]).read_text())
    validator = Draft202012Validator(schema)

    Draft202012Validator.check_schema(schema)
    validator.validate(decode_strict_json(input_bytes))
    manifest = load_canonical_manifest_v2(input_bytes)
    assert vectors["schema_version"] == "aeos.product-manifest.v2"
    assert vectors["provenance"] == (
        "John-approved PB-195 v2 C14 correction-sweep amendment; Wema correction-sweep consumer."
    )
    assert input_bytes == literal == V2_VECTOR_CANONICAL
    assert manifest.canonical_bytes == literal
    assert manifest.manifest_digest == vectors["manifest_sha256"]
    assert manifest.grant_set_digest == vectors["grant_set_sha256"]
    invalid = decode_strict_json(input_bytes)
    invalid["unexpected"] = True
    with pytest.raises(ValidationError, match="Additional properties"):
        validator.validate(invalid)


def payload_v2() -> dict[str, Any]:
    payload = decode_strict_json(_SCHEMAS.joinpath("canonical_manifest_v1.json").read_bytes())
    payload["schema_version"] = "aeos.product-manifest.v2"
    payload["compatibility"] = {
        "min_reader": "2.0.0",
        "max_reader": "2.9.0",
        "required_capabilities": sorted(
            READER_CAPABILITIES_V2 | REQUIRED_SWEEP_HOST_CAPABILITIES_V2
        ),
    }
    payload["credential_scopes"][SWEEP_SCOPE] = [SWEEP_CAPABILITY]
    payload["service_principal_grants"].append(
        {
            "purpose": SWEEP_PURPOSE,
            "principal_id": "sweep-service-fixture",
            "principal_class": SWEEP_PRINCIPAL_CLASS,
        }
    )
    payload["source_bindings"]["correction_sweep"] = {
        "version": "source-policy-7",
        "digest": "e" * 64,
    }
    payload["correction_sweep"] = {
        "policy_id": "source-sweep-policy",
        "version": "7",
        "effective_interval": {
            "starts_at": "2026-10-01T00:00:00Z",
            "ends_before": None,
            "decision_ref": "example://decision/source-sweep-interval",
        },
        "source_policy_revisions": ["example://source-policy/revision-7"],
        "fact_authority_rule": "example://source-policy/fact-authority-7",
        "privacy_policy_refs": ["example://privacy/sweep-7"],
        "retention_policy_ref": "example://retention/sweep-7",
        "access_policy_ref": "example://access/sweep-7",
        "legal_hold_policy_ref": "example://legal-hold/sweep-7",
        "incident_policy_ref": "example://incident/sweep-7",
        "correction_owner_policy_revision": "example://correction-owner/revision-7",
        "calendar": {
            "artifact_id": "business-calendar",
            "version": "2026.10",
            "digest": "f" * 64,
            "iana_time_zone": "America/New_York",
            "working_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "holidays": ["2026-11-26", "2026-12-25"],
            "dst_fold_rule": "earlier",
            "dst_gap_rule": "next_valid",
        },
        "lookback_months": 12,
        "lookback_algorithm_version": "calendar-months-v1",
    }
    return payload


def refusal(payload: dict[str, Any]) -> ManifestContractError:
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest_v2(payload)
    return caught.value


def test_v2_canonical_bytes_and_reader_identity_are_separate_from_v1() -> None:
    payload = payload_v2()
    manifest = load_canonical_manifest_v2(payload)

    assert manifest.canonical_bytes == canonical_manifest_bytes_v2(payload)
    assert manifest.manifest_digest == hashlib.sha256(manifest.canonical_bytes).hexdigest()
    assert manifest.grant_set_digest == service_principal_grant_set_digest_v2(payload)
    parsed = load_canonical_manifest_v2(manifest.canonical_bytes)
    assert parsed.canonical_bytes == manifest.canonical_bytes
    incompatible = copy.deepcopy(payload) | {"schema_version": "aeos.product-manifest.v1"}
    assert refusal(incompatible).reason_code == "manifest_incompatible"
    with pytest.raises(ManifestContractError) as caught:
        load_canonical_manifest(manifest.canonical_bytes)
    assert caught.value.reason_code in {"manifest_incompatible", "manifest_schema_invalid"}


def test_v2_effectful_reader_needs_explicit_host_installation() -> None:
    manifest = load_canonical_manifest_v2(payload_v2())

    assert not manifest.reader_compatible()
    assert manifest.reader_compatible(available_capabilities=REQUIRED_SWEEP_HOST_CAPABILITIES_V2)
    assert not manifest.reader_compatible(
        available_capabilities=REQUIRED_SWEEP_HOST_CAPABILITIES_V2
        - {"correction_sweep_queue_admission_v2"}
    )
    missing = payload_v2()
    missing["compatibility"]["required_capabilities"].remove(
        "correction_sweep_worker_revalidation_v2"
    )
    assert refusal(missing).path == "manifest.compatibility.required_capabilities"


def test_v2_sweep_scope_and_principal_are_exact_and_not_mailbox_derived() -> None:
    manifest = load_canonical_manifest_v2(payload_v2())
    assert manifest.grants_principal(
        purpose=SWEEP_PURPOSE,
        principal_id="sweep-service-fixture",
        principal_class=SWEEP_PRINCIPAL_CLASS,
    )
    assert PURPOSE_PRINCIPAL_CLASSES_V2[SWEEP_PURPOSE] == SWEEP_PRINCIPAL_CLASS
    assert PURPOSE_PRINCIPAL_CLASSES_V2["support_move_admission"] == "support_move_service"
    assert not manifest.grants_principal(
        purpose=SWEEP_PURPOSE,
        principal_id="example-worker-1",
        principal_class=SWEEP_PRINCIPAL_CLASS,
    )
    wrong_scope = payload_v2()
    wrong_scope["credential_scopes"][SWEEP_SCOPE] = ["draft"]
    assert refusal(wrong_scope).reason_code == "manifest_grant_mismatch"
    aggregate_mailboxes = payload_v2()
    aggregate_mailboxes["credential_scopes"]["support:registered_mailboxes"] = [SWEEP_CAPABILITY]
    aggregate_error = refusal(aggregate_mailboxes)
    assert aggregate_error.reason_code == "manifest_grant_mismatch"
    assert aggregate_error.path == "manifest.credential_scopes.support:registered_mailboxes"
    mailbox_scope = payload_v2()
    mailbox_scope["credential_scopes"]["support:mailbox:fixture"] = [SWEEP_CAPABILITY]
    mailbox_error = refusal(mailbox_scope)
    assert mailbox_error.reason_code == "manifest_grant_mismatch"
    assert mailbox_error.path == "manifest.credential_scopes.support:mailbox:fixture"
    duplicate_sweep = payload_v2()
    duplicate_sweep["service_principal_grants"].append(
        {
            "purpose": SWEEP_PURPOSE,
            "principal_id": "another-sweep-service",
            "principal_class": SWEEP_PRINCIPAL_CLASS,
        }
    )
    assert refusal(duplicate_sweep).reason_code == "manifest_grant_mismatch"
    wrong_class = payload_v2()
    wrong_class["service_principal_grants"][-1]["principal_class"] = "support_move_service"
    assert refusal(wrong_class).reason_code == "manifest_grant_mismatch"


def test_v2_closed_calendar_and_sweep_policy_refuse_incomplete_or_unknown_leaves() -> None:
    invalid_zone = payload_v2()
    invalid_zone["correction_sweep"]["calendar"]["iana_time_zone"] = "Mars/Olympus"
    assert refusal(invalid_zone).path == "manifest.correction_sweep.calendar.iana_time_zone"
    invalid_fold = payload_v2()
    invalid_fold["correction_sweep"]["calendar"]["dst_fold_rule"] = "guess"
    assert refusal(invalid_fold).path == "manifest.correction_sweep.calendar.dst_fold_rule"
    extra = payload_v2()
    extra["correction_sweep"]["approved"] = True
    assert refusal(extra).path == "manifest.correction_sweep.approved"


def test_v2_section_ownership_covers_each_leaf_once() -> None:
    assert dict(SECTION_AUTHORITY_CLASSES_V2) == {
        **SECTION_AUTHORITY_CLASSES,
        "source_sweep_source": "source_policy_owner",
        "source_sweep_privacy": "privacy_legal_owner",
        "source_sweep_calendar": "calendar_policy_owner",
        "source_sweep_correction_owner": "correction_policy_owner",
    }
    assert tuple(POLICY_SECTIONS_V2[: len(POLICY_SECTIONS)]) == POLICY_SECTIONS
    assert SECTION_PATHS_V2["source_sweep_source"] == (
        "correction_sweep.policy_id",
        "correction_sweep.version",
        "correction_sweep.effective_interval",
        "correction_sweep.source_policy_revisions",
        "correction_sweep.fact_authority_rule",
    )
    assert SECTION_PATHS_V2["source_sweep_privacy"] == (
        "correction_sweep.privacy_policy_refs",
        "correction_sweep.retention_policy_ref",
        "correction_sweep.access_policy_ref",
        "correction_sweep.legal_hold_policy_ref",
        "correction_sweep.incident_policy_ref",
    )
    assert SECTION_PATHS_V2["source_sweep_calendar"] == (
        "correction_sweep.calendar",
        "correction_sweep.lookback_months",
        "correction_sweep.lookback_algorithm_version",
    )
    assert SECTION_PATHS_V2["source_sweep_correction_owner"] == (
        "correction_sweep.correction_owner_policy_revision",
    )
    covered = [path for paths in SECTION_PATHS_V2.values() for path in paths]
    assert len(covered) == len(set(covered))
    manifest = load_canonical_manifest_v2(payload_v2())
    assert set(covered) == set(policy_leaf_paths_v2(manifest.payload))
    assert set(POLICY_SECTIONS_V2) == set(SECTION_AUTHORITY_CLASSES_V2) == set(SECTION_PATHS_V2)
    assert SECTION_PATHS_V2["source_bindings"] == SECTION_PATHS["source_bindings"]


def test_v2_reader_keeps_v1_host_facing_accessors_without_policy_defaults() -> None:
    manifest = load_canonical_manifest_v2(payload_v2())

    assert manifest.correction_sweep["lookback_months"] == 12
    assert manifest.correction_sweep_source_binding == {
        "version": "source-policy-7",
        "digest": "e" * 64,
    }
    calendar = manifest.section("source_sweep_calendar")["correction_sweep.calendar"]
    assert calendar["iana_time_zone"] == "America/New_York"
    assert manifest.as_product_manifest("example-product").version == "example-2026.09.27"
    with pytest.raises(ContractError):
        manifest.section("whole_manifest")
