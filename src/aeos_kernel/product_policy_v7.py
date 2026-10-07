"""PB-187's exact Authority formula in the immutable v6 manifest composition.

Values remain proposals until the host adopts the exact required owner mapping,
complete authority_targets section and manifest. Parsing never supplies that
mapping, adopts policy or grants a service purpose.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Final, cast
from uuid import UUID

from aeos_kernel._validation import freeze_json
from aeos_kernel.errors import ContractError
from aeos_kernel.product_policy import (
    READER_CAPABILITIES,
    ManifestReason,
    _at,
    _fail,
    _object,
    _reference,
    _serialize,
    _version_key,
    canonical_decimal,
    decode_strict_json,
    manifest_digest,
)
from aeos_kernel.product_policy_v2 import READER_CAPABILITIES_V2
from aeos_kernel.product_policy_v3 import READER_CAPABILITIES_V3
from aeos_kernel.product_policy_v4 import READER_CAPABILITIES_V4
from aeos_kernel.product_policy_v5 import READER_CAPABILITIES_V5
from aeos_kernel.product_policy_v6 import (
    READER_CAPABILITIES_V6,
    SCHEMA_VERSION_V6,
    CanonicalProductManifestV6,
    normalize_manifest_payload_v6,
    policy_leaf_paths_v6,
    purpose_principal_classes_v6,
    section_authority_classes_v6,
    section_paths_v6,
)

SCHEMA_VERSION_V7: Final = "aeos.product-manifest.v7"
READER_VERSION_V7: Final = "7.0.0"
READER_CAPABILITIES_V7: Final = frozenset(
    {SCHEMA_VERSION_V7, "canonical_manifest_bytes_v7", "authority_score_formula_v1"}
)
AUTHORITY_SCORE_INPUTS: Final = (
    "earned_citation_count", "source_diversity_count", "answer_engine_citation_rate",
    "owned_audience_size", "brand_search_index", "platform_presence_count",
)
AUTHORITY_CITATION_TYPES: Final = (
    "journalist", "answer_engine", "directory", "backlink", "trade_press",
)


def section_authority_classes_v7(profile: str) -> Mapping[str, str]:
    return section_authority_classes_v6(profile)


def section_paths_v7(profile: str) -> Mapping[str, tuple[str, ...]]:
    prior = section_paths_v6(profile)
    return MappingProxyType({
        **prior,
        "authority_targets": (*prior["authority_targets"], "authority.score_formula"),
    })


def purpose_principal_classes_v7(profile: str) -> Mapping[str, str]:
    return purpose_principal_classes_v6(profile)


def _signed_decimal(value: Any, path: str) -> str:
    negative = isinstance(value, str) and value.startswith("-")
    if negative and value[1:].startswith(("+", "-")):
        _fail(path, "must contain at most one sign")
    normalized = canonical_decimal(value[1:] if negative else value, path)
    return f"-{normalized}" if negative and normalized != "0" else normalized


def _component(value: Any, path: str) -> dict[str, str]:
    row = _object({
        "lower_anchor": _signed_decimal,
        "target": _signed_decimal,
        "weight": canonical_decimal,
    })(value, path)
    if Decimal(row["target"]) <= Decimal(row["lower_anchor"]) or Decimal(row["weight"]) <= 0:
        _fail(path, "requires target greater than lower_anchor and positive weight")
    return dict(row)


def _precision(value: Any, path: str) -> int:
    if type(value) is not int or value != 4:
        _fail(path, "must be the integer 4")
    return 4


def _rounding(value: Any, path: str) -> str:
    if value != "half_even":
        _fail(path, "must be half_even")
    return "half_even"


def normalize_authority_formula_v1(value: Any, path: str = "manifest.authority.score_formula"
                                  ) -> dict[str, Any]:
    """Canonical closed values; exact sums are independent of Decimal context."""
    row = _object({
        "version": _reference,
        "components": _object({name: _component for name in AUTHORITY_SCORE_INPUTS}),
        "precision": _precision,
        "rounding": _rounding,
        "citation_authority_weights": _object({
            name: canonical_decimal for name in AUTHORITY_CITATION_TYPES
        }),
    })(value, path)
    if sum((Fraction(term["weight"]) for term in row["components"].values()), Fraction(0)) != 1:
        _fail(f"{path}.components", "weights must sum exactly to 1")
    return dict(row)


def normalize_manifest_payload_v7(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION_V7:
        _fail("manifest.schema_version", "is not a v7 schema", ManifestReason.INCOMPATIBLE)
    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        _fail("manifest.authority", "must be an object")
    authority = cast(Mapping[str, Any], authority)
    formula = normalize_authority_formula_v1(authority.get("score_formula"))
    prior = dict(payload)
    prior["schema_version"] = SCHEMA_VERSION_V6
    prior["authority"] = {key: value for key, value in authority.items() if key != "score_formula"}
    normalized = normalize_manifest_payload_v6(prior)
    if not set(normalized["compatibility"]["required_capabilities"]) >= READER_CAPABILITIES_V7:
        _fail(
            "manifest.compatibility.required_capabilities",
            "must name every v7 capability",
            ManifestReason.INCOMPATIBLE,
        )
    normalized["schema_version"] = SCHEMA_VERSION_V7
    normalized["authority"]["score_formula"] = formula
    return normalized


class CanonicalProductManifestV7(CanonicalProductManifestV6):
    """V7 binds the formula into the existing Authority-target approval section."""

    @property
    def authority_score_formula(self) -> dict[str, Any]:
        # Return a normalized independent object, never a mutable alias of policy.
        return normalize_authority_formula_v1(self.payload["authority"]["score_formula"])

    def reader_compatible(
        self,
        reader_version: str = READER_VERSION_V7,
        *,
        available_capabilities: Collection[str] = (),
    ) -> bool:
        compatibility = self.payload["compatibility"]
        version = _version_key(reader_version)
        prior = (READER_CAPABILITIES_V2 if self.manifest_profile == "correction_sweep"
                 else READER_CAPABILITIES)
        return _version_key(compatibility["min_reader"]) <= version <= _version_key(
            compatibility["max_reader"]
        ) and set(compatibility["required_capabilities"]) <= (
            prior | READER_CAPABILITIES_V3 | READER_CAPABILITIES_V4 | READER_CAPABILITIES_V5
            | READER_CAPABILITIES_V6 | READER_CAPABILITIES_V7 | set(available_capabilities)
        )

    def section(self, name: str) -> dict[str, Any]:
        paths = section_paths_v7(self.manifest_profile)
        if name not in paths:
            raise ContractError(f"unknown policy section {name!r}")
        return {path: _at(self.payload, path) for path in paths[name]}


def canonical_manifest_bytes_v7(
    payload: Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> bytes:
    normalized = normalize_manifest_payload_v7(payload)
    for key, expected in {
        "product_instance_id": product_id,
        "portfolio_phase_revision_id": phase_revision_id,
    }.items():
        if expected is not None and normalized[key] != str(expected).lower():
            _fail(f"manifest.{key}", "differs from the revision row",
                  ManifestReason.IDENTITY_MISMATCH)
    if manifest_version is not None and normalized["manifest_version"] != manifest_version:
        _fail("manifest.manifest_version", "differs from the revision row",
              ManifestReason.IDENTITY_MISMATCH)
    return _serialize(normalized)


def load_canonical_manifest_v7(
    source: bytes | Mapping[str, Any],
    *,
    product_id: str | UUID | None = None,
    phase_revision_id: str | UUID | None = None,
    manifest_version: str | None = None,
) -> CanonicalProductManifestV7:
    payload = decode_strict_json(source) if isinstance(source, bytes) else source
    canonical = canonical_manifest_bytes_v7(
        payload, product_id=product_id, phase_revision_id=phase_revision_id,
        manifest_version=manifest_version,
    )
    normalized = json.loads(canonical)
    return CanonicalProductManifestV7(
        payload=freeze_json(normalized), canonical_bytes=canonical,
        manifest_digest=manifest_digest(canonical),
        grant_set_digest=hashlib.sha256(_serialize(normalized["service_principal_grants"])).hexdigest(),
    )


def policy_leaf_paths_v7(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return policy_leaf_paths_v6(payload)
