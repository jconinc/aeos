"""PB-233 current-key proof comparison for the PB-232 encryption fence.

This module compares a retained proof with independently read current evidence.
It neither reads a vault nor authenticates the evidence reader. The Wema effect
boundary must supply that registered reader, current policy and database time;
a matching result is one prerequisite, never a live or provider-I/O grant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from aeos_kernel._validation import digest, required, utc
from aeos_kernel.errors import ContractError
from aeos_kernel.runtime_policy import EffectiveRuntimePolicy

_SAFE_KEY = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")
_VERSION = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def _positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{name} must be a positive integer")


def _safe_key(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SAFE_KEY.fullmatch(value):
        raise ContractError(f"{name} must be a safe canonical key")


@dataclass(frozen=True, slots=True)
class KeyDomainEvidence:
    """Safe evidence for one fully inventoried encryption domain."""

    domain_id: str
    secret_ref_id: UUID
    secret_version: int
    purpose: str
    state: str
    provider_version: str
    provider_readback_at: datetime
    rotated_at: datetime
    rotation_deadline: datetime
    expires_at: datetime
    at_rest_covered: bool
    in_transit_covered: bool
    ciphertext_reader_compatible: bool

    def __post_init__(self) -> None:
        _safe_key(self.domain_id, "domain id")
        if not isinstance(self.secret_ref_id, UUID):
            raise ContractError("secret ref id must be a UUID")
        _positive(self.secret_version, "secret version")
        if self.purpose not in {
            "encryption_key",
            "signing_key",
            "channel_credential",
            "webhook_secret",
            "provider_token",
            "egress_cert",
        }:
            raise ContractError("secret purpose is unknown")
        if self.state not in {"active", "rotating", "revoked"}:
            raise ContractError("secret state is unknown")
        if not isinstance(self.provider_version, str) or not _VERSION.fullmatch(
            self.provider_version
        ):
            raise ContractError("provider version must be an opaque safe token")
        for name in ("provider_readback_at", "rotated_at", "rotation_deadline", "expires_at"):
            utc(getattr(self, name), name)
        for name in ("at_rest_covered", "in_transit_covered", "ciphertext_reader_compatible"):
            if not isinstance(getattr(self, name), bool):
                raise ContractError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class CurrentKeyProof:
    """Retained proof bound to exact policy, inventory and key generations."""

    proof_id: UUID
    product_slug: str
    runtime_root: str
    platform_policy_id: UUID
    platform_generation: int
    manifest_digest: str | None
    permission_generation: int
    source_generation: int
    inventory_digest: str
    declaration_digest: str
    domain_census_digest: str
    domain_census_complete: bool
    domains: tuple[KeyDomainEvidence, ...]
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.proof_id, UUID) or not isinstance(self.platform_policy_id, UUID):
            raise ContractError("proof and platform policy ids must be UUIDs")
        required(self.product_slug, "product slug")
        required(self.runtime_root, "runtime root")
        if len(self.product_slug) > 128 or len(self.runtime_root) > 128:
            raise ContractError("proof scope is too long")
        for name in ("platform_generation", "permission_generation", "source_generation"):
            _positive(getattr(self, name), name)
        if self.manifest_digest is not None:
            digest(self.manifest_digest, "manifest digest")
        for name in ("inventory_digest", "declaration_digest", "domain_census_digest"):
            digest(getattr(self, name), name)
        if not isinstance(self.domain_census_complete, bool):
            raise ContractError("domain census completeness must be a boolean")
        if not isinstance(self.domains, tuple) or any(
            not isinstance(domain, KeyDomainEvidence) for domain in self.domains
        ):
            raise ContractError("proof domains must be an immutable tuple")
        if len({domain.domain_id for domain in self.domains}) != len(self.domains):
            raise ContractError("proof domains contain duplicates")
        utc(self.issued_at, "proof issue time")
        utc(self.expires_at, "proof expiry time")
        if self.expires_at <= self.issued_at:
            raise ContractError("proof expiry must follow issue time")


@dataclass(frozen=True, slots=True)
class CurrentKeyState:
    """One independently observed current state from a registered Wema reader."""

    product_slug: str
    runtime_root: str
    source_generation: int
    inventory_digest: str
    declaration_digest: str
    domain_census_digest: str
    domain_census_complete: bool
    required_domain_ids: tuple[str, ...]
    domains: tuple[KeyDomainEvidence, ...]

    def __post_init__(self) -> None:
        required(self.product_slug, "current product slug")
        required(self.runtime_root, "current runtime root")
        _positive(self.source_generation, "current source generation")
        for name in ("inventory_digest", "declaration_digest", "domain_census_digest"):
            digest(getattr(self, name), name)
        if not isinstance(self.domain_census_complete, bool):
            raise ContractError("current domain census completeness must be a boolean")
        if not isinstance(self.required_domain_ids, tuple) or not isinstance(self.domains, tuple):
            raise ContractError("current domains must be immutable tuples")
        if any(not isinstance(domain, KeyDomainEvidence) for domain in self.domains):
            raise ContractError("current domain evidence is invalid")
        if len(set(self.required_domain_ids)) != len(self.required_domain_ids):
            raise ContractError("required domains contain duplicates")
        if len({domain.domain_id for domain in self.domains}) != len(self.domains):
            raise ContractError("current domains contain duplicates")
        for domain_id in self.required_domain_ids:
            _safe_key(domain_id, "required domain id")


class KeyEvidenceReader(Protocol):
    """Wema supplies the registered, authenticated current-state adapter."""

    def read_current(self, *, product_slug: str, runtime_root: str) -> CurrentKeyState | None: ...


def verify_current_key_proof(
    *,
    proof: CurrentKeyProof | None,
    policy: EffectiveRuntimePolicy | None,
    reader: KeyEvidenceReader,
    product_slug: str,
    runtime_root: str,
    db_now: datetime,
) -> UUID:
    """Return a matching proof id, or refuse before any dependent effect.

    The caller must authenticate ``reader`` and recheck the same policy/key/source
    generations at its final effect or connect fence. This comparison alone does
    not publish policy, prove a real vault operation or authorize network I/O.
    """
    utc(db_now, "database time")
    if proof is None or policy is None:
        raise ContractError("current key proof or policy is unavailable")
    current = reader.read_current(product_slug=product_slug, runtime_root=runtime_root)
    if current is None:
        raise ContractError("current key evidence is unavailable")
    if (
        proof.product_slug != product_slug
        or current.product_slug != product_slug
        or proof.runtime_root != runtime_root
        or current.runtime_root != runtime_root
        or proof.platform_policy_id != policy.platform_policy_id
        or proof.platform_generation != policy.platform_generation
        or proof.manifest_digest != policy.manifest_digest
        or proof.permission_generation != policy.permission_generation
        or proof.source_generation != current.source_generation
        or proof.inventory_digest != current.inventory_digest
        or proof.declaration_digest != current.declaration_digest
        or proof.domain_census_digest != current.domain_census_digest
    ):
        raise ContractError("current key proof has a stale policy or source binding")
    if not proof.issued_at <= db_now < proof.expires_at:
        raise ContractError("current key proof is outside its valid time")
    if not proof.domain_census_complete or not current.domain_census_complete:
        raise ContractError("encryption domain census is incomplete")
    required_ids = set(current.required_domain_ids)
    proved = {domain.domain_id: domain for domain in proof.domains}
    observed = {domain.domain_id: domain for domain in current.domains}
    if not required_ids or set(proved) != required_ids or set(observed) != required_ids:
        raise ContractError("encryption domain coverage is incomplete")
    for domain_id in required_ids:
        stated = proved[domain_id]
        actual = observed[domain_id]
        if (
            stated.secret_ref_id != actual.secret_ref_id
            or stated.secret_version != actual.secret_version
            or stated.provider_version != actual.provider_version
            or stated.purpose != "encryption_key"
            or actual.purpose != "encryption_key"
            or stated.state != "active"
            or actual.state != "active"
            or actual.provider_readback_at < proof.issued_at
            or actual.provider_readback_at > db_now
            or stated.provider_readback_at > proof.issued_at
            or stated.rotated_at != actual.rotated_at
            or stated.rotation_deadline != actual.rotation_deadline
            or stated.expires_at != actual.expires_at
            or stated.rotation_deadline <= db_now
            or stated.expires_at <= db_now
            or stated.rotated_at > db_now
            or db_now - stated.rotated_at >= timedelta(days=policy.key_rotation_days)
            or stated.at_rest_covered != actual.at_rest_covered
            or stated.in_transit_covered != actual.in_transit_covered
            or stated.ciphertext_reader_compatible != actual.ciphertext_reader_compatible
            or not stated.ciphertext_reader_compatible
            or (policy.at_rest_required and not stated.at_rest_covered)
            or (policy.in_transit_required and not stated.in_transit_covered)
        ):
            raise ContractError("current encryption key or coverage is unavailable")
    return proof.proof_id
