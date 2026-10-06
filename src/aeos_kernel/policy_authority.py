"""Who may run a product-policy command: exact grants resolved through ``resolve_authority``.

A policy command is authorized only by a confirmed ``AuthorityRecord`` whose exact-attribute
selector names the subject, the command, the section and the principal. Product ownership,
service execution, class membership, a default and a prior approval all authorize nothing.
An unknown, missing, stale or revoked grant is a typed refusal, never an inferred approval.

This module keeps no grant store. Hosts supply the records they hold; a host that holds none
gets ``policy_authority_missing`` for every command, which is the correct held state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from aeos_kernel.authority import (
    AuthorityRecord,
    AuthorityResolutionStatus,
    AuthorityStatus,
    SelectorType,
    resolve_authority,
    selector_matches,
)
from aeos_kernel.errors import ContractError
from aeos_kernel.product_policy import (
    POLICY_SECTIONS,
    SCHEMA_VERSION,
    SECTION_AUTHORITY_CLASSES,
    SERVICE_GRANT_WITHDRAWAL,
    WHOLE_MANIFEST,
)
from aeos_kernel.product_policy_v2 import (
    POLICY_SECTIONS_V2,
    SCHEMA_VERSION_V2,
    SECTION_AUTHORITY_CLASSES_V2,
)
from aeos_kernel.product_policy_v3 import SCHEMA_VERSION_V3, section_authority_classes_v3
from aeos_kernel.product_policy_v4 import SCHEMA_VERSION_V4, section_authority_classes_v4
from aeos_kernel.product_policy_v5 import SCHEMA_VERSION_V5, section_authority_classes_v5

#: The closed PB-195 command surface.
POLICY_COMMANDS: Final = (
    "propose_phase",
    "record_phase_decision",
    "select_phase",
    "deactivate_phase",
    "retire_phase",
    "propose_manifest",
    "record_manifest_decision",
    "activate_manifest",
    "replace_manifest",
    "revoke_manifest",
    "rollback_manifest",
    "deactivate_manifest",
    "withdraw_latest_service_grant_set",
)
#: The scope label a command other than a section decision or revocation is authorized under.
PHASE_SCOPE: Final = "portfolio_phase"
SELECTION_SCOPE: Final = "manifest_selection"
PROPOSAL_SCOPE: Final = "manifest_proposal"
#: The authority class each command requires outside a section decision, from PB-195 R5's held
#: human decisions: the portfolio owner holds phase and transition authority, the product owner
#: replacement and revocation, the release owner activation generation and rollback candidate,
#: and the security/role authority grant-set revocation (R11). A proposal names no class: it is
#: a candidate that approves nothing, so only its exact grant is required.
COMMAND_AUTHORITY_CLASSES: Final[Mapping[str, str | None]] = MappingProxyType(
    {
        "propose_phase": "portfolio_owner",
        "record_phase_decision": "portfolio_owner",
        "select_phase": "portfolio_owner",
        "deactivate_phase": "portfolio_owner",
        "retire_phase": "portfolio_owner",
        "propose_manifest": None,
        "activate_manifest": "release_owner",
        "replace_manifest": "product_owner",
        "revoke_manifest": "product_owner",
        "rollback_manifest": "release_owner",
        "deactivate_manifest": "release_owner",
        "withdraw_latest_service_grant_set": "security_role",
    }
)
SCOPE_KEYS: Final = frozenset({"subject_id", "command", "section", "principal_id"})


class PolicyAuthorityStatus(StrEnum):
    AUTHORIZED = "authorized"
    MISSING = "policy_authority_missing"
    STALE = "policy_authority_stale"
    REVOKED = "policy_authority_revoked"
    CONFLICT = "policy_authority_conflict"
    CLASS_MISMATCH = "policy_authority_class_mismatch"
    SCOPE_VIOLATION = "policy_authority_scope_violation"


@dataclass(frozen=True, slots=True)
class PolicyAuthorityDecision:
    status: PolicyAuthorityStatus
    authority_class: str | None = None
    authority_id: str | None = None
    decision_ref: str | None = None
    #: For a grant-withdrawing revocation, the separate security/role authorization.
    grant_withdrawal: PolicyAuthorityDecision | None = None

    @property
    def authorized(self) -> bool:
        return self.status is PolicyAuthorityStatus.AUTHORIZED


def command_section(
    command: str, section: str | None, *, schema_version: str = SCHEMA_VERSION
) -> str:
    """The one section label a command is authorized under; callers cannot choose another.

    ``revoke_manifest`` is authorized under ``whole_manifest``. When its scope also withdraws the
    service-principal grants, ``authorize_policy_command`` also requires a second exact grant under
    ``service_grant_withdrawal``; neither authorization stands in for the other.
    """

    if command not in POLICY_COMMANDS:
        raise ContractError(f"unknown policy command {command!r}")
    if schema_version not in {
        SCHEMA_VERSION,
        SCHEMA_VERSION_V2,
        SCHEMA_VERSION_V3,
        SCHEMA_VERSION_V4,
        SCHEMA_VERSION_V5,
    }:
        raise ContractError("unknown product-policy schema version")
    if command == "record_manifest_decision":
        sections = POLICY_SECTIONS_V2 if schema_version == SCHEMA_VERSION_V2 else POLICY_SECTIONS
        if schema_version == SCHEMA_VERSION_V3:
            # The storing host also checks the selected revision's exact profile.
            sections = tuple(section_authority_classes_v3("correction_sweep"))
        if schema_version == SCHEMA_VERSION_V4:
            sections = tuple(section_authority_classes_v4("correction_sweep"))
        if schema_version == SCHEMA_VERSION_V5:
            sections = tuple(section_authority_classes_v5("correction_sweep"))
        if section not in sections:
            raise ContractError("a manifest decision names one policy section")
        return str(section)
    if command == "revoke_manifest" and section == SERVICE_GRANT_WITHDRAWAL:
        return SERVICE_GRANT_WITHDRAWAL
    if section is not None:
        raise ContractError(f"{command} does not take a policy section")
    if command == "revoke_manifest":
        return WHOLE_MANIFEST
    if command == "withdraw_latest_service_grant_set":
        return SERVICE_GRANT_WITHDRAWAL
    if command == "propose_manifest":
        return PROPOSAL_SCOPE
    if command.endswith("_phase"):
        return PHASE_SCOPE
    return SELECTION_SCOPE


def required_authority_class(
    command: str, section_label: str, *, schema_version: str = SCHEMA_VERSION
) -> str | None:
    """The authority class a grant must carry for this command under this label."""

    classes = (
        SECTION_AUTHORITY_CLASSES_V2
        if schema_version == SCHEMA_VERSION_V2
        else SECTION_AUTHORITY_CLASSES
    )
    if schema_version == SCHEMA_VERSION_V3:
        classes = section_authority_classes_v3("correction_sweep")
    if schema_version == SCHEMA_VERSION_V4:
        classes = section_authority_classes_v4("correction_sweep")
    if schema_version == SCHEMA_VERSION_V5:
        classes = section_authority_classes_v5("correction_sweep")
    if schema_version not in {
        SCHEMA_VERSION,
        SCHEMA_VERSION_V2,
        SCHEMA_VERSION_V3,
        SCHEMA_VERSION_V4,
        SCHEMA_VERSION_V5,
    }:
        raise ContractError("unknown product-policy schema version")
    if section_label in classes:
        return classes[section_label]
    if section_label == SERVICE_GRANT_WITHDRAWAL:
        return "security_role"
    return COMMAND_AUTHORITY_CLASSES[command]


def _exact(record: AuthorityRecord) -> bool:
    selector = record.selector
    return (
        selector.selector_type == SelectorType.EXACT_ATTRIBUTES.value
        and set(selector.selector_args) == SCOPE_KEYS
    )


def authorize_policy_command(
    records: Iterable[AuthorityRecord],
    *,
    vertical_id: str,
    tenant_id: str,
    subject_id: str,
    command: str,
    section: str | None,
    principal_id: str,
    at: datetime,
    schema_version: str = SCHEMA_VERSION,
) -> PolicyAuthorityDecision:
    """Resolve one exact grant for one command, or return the typed reason there is none.

    A grant-withdrawing ``revoke_manifest`` (section ``service_grant_withdrawal``) needs the
    ordinary ``whole_manifest`` grant and, separately, the security/role withdrawal grant
    (PB-195 R8-B1). The returned decision is the whole-manifest one, carrying the withdrawal
    decision in ``grant_withdrawal``; the first refusal of either is returned instead.
    """

    label = command_section(command, section, schema_version=schema_version)
    exact = tuple(record for record in records if _exact(record))

    def one(scope_label: str) -> PolicyAuthorityDecision:
        scope = {
            "subject_id": subject_id,
            "command": command,
            "section": scope_label,
            "principal_id": principal_id,
        }
        return _resolve(exact, vertical_id, tenant_id, scope, command, at, schema_version)

    if command == "revoke_manifest" and label == SERVICE_GRANT_WITHDRAWAL:
        whole = one(WHOLE_MANIFEST)
        if not whole.authorized:
            return whole
        withdrawal = one(SERVICE_GRANT_WITHDRAWAL)
        if not withdrawal.authorized:
            return withdrawal
        return replace(whole, grant_withdrawal=withdrawal)
    return one(label)


def _resolve(
    exact: tuple[AuthorityRecord, ...],
    vertical_id: str,
    tenant_id: str,
    scope: dict[str, str],
    command: str,
    at: datetime,
    schema_version: str,
) -> PolicyAuthorityDecision:
    resolution = resolve_authority(
        exact, vertical_id=vertical_id, tenant_id=tenant_id, scope=scope, at=at
    )
    if resolution.status is AuthorityResolutionStatus.SCOPE_VIOLATION:
        return PolicyAuthorityDecision(PolicyAuthorityStatus.SCOPE_VIOLATION)
    if resolution.status is AuthorityResolutionStatus.AUTHORITY_CONFLICT:
        return PolicyAuthorityDecision(PolicyAuthorityStatus.CONFLICT)
    if resolution.status is AuthorityResolutionStatus.AUTHORITY_GAP:
        return PolicyAuthorityDecision(_gap_status(exact, scope))
    record = resolution.selected[0] if len(resolution.selected) == 1 else None
    if record is None:
        return PolicyAuthorityDecision(PolicyAuthorityStatus.MISSING)
    authority_class = record.value.get("authority_class")
    decision_ref = record.value.get("decision_ref")
    if (
        not isinstance(authority_class, str)
        or not isinstance(decision_ref, str)
        or not decision_ref
    ):
        return PolicyAuthorityDecision(PolicyAuthorityStatus.MISSING)
    required_class = required_authority_class(
        command, scope["section"], schema_version=schema_version
    )
    if required_class is not None and authority_class != required_class:
        return PolicyAuthorityDecision(
            PolicyAuthorityStatus.CLASS_MISMATCH, authority_class, record.authority_id
        )
    return PolicyAuthorityDecision(
        PolicyAuthorityStatus.AUTHORIZED, authority_class, record.authority_id, decision_ref
    )


def _gap_status(
    records: tuple[AuthorityRecord, ...], scope: dict[str, str]
) -> PolicyAuthorityStatus:
    matching = [record for record in records if selector_matches(record.selector, scope)]
    withdrawn = {AuthorityStatus.RETIRED.value, AuthorityStatus.REJECTED.value}
    if any(
        record.status in withdrawn
        or record.status == AuthorityStatus.SUPERSEDED.value
        or record.superseded_by
        for record in matching
    ):
        return PolicyAuthorityStatus.REVOKED
    if any(record.status == AuthorityStatus.CONFIRMED_AUTHORITY.value for record in matching):
        return PolicyAuthorityStatus.STALE
    return PolicyAuthorityStatus.MISSING


__all__ = [
    "COMMAND_AUTHORITY_CLASSES",
    "PHASE_SCOPE",
    "POLICY_COMMANDS",
    "PROPOSAL_SCOPE",
    "SCOPE_KEYS",
    "SELECTION_SCOPE",
    "PolicyAuthorityDecision",
    "PolicyAuthorityStatus",
    "authorize_policy_command",
    "command_section",
    "required_authority_class",
]
