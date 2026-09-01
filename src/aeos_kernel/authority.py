"""Project-neutral authority records and deterministic resolution.

The precedence and fail-closed conflict behavior are extracted from
MultiAgentCommunication ``decision_engine/authority.py`` at the pinned source commit.
Persistence is deliberately absent; repositories belong behind ports or adapters.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from fnmatch import fnmatch
from typing import Any

from aeos_kernel.canonical import stable_fingerprint


class AuthorityStatus(StrEnum):
    EXTRACTED_TENTATIVE = "extracted_tentative"
    CONSISTENT_CANDIDATE = "consistent_candidate"
    CONFIRMED_AUTHORITY = "confirmed_authority"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    REJECTED = "rejected"


class AuthorityLayer(StrEnum):
    DESIGN_PRINCIPLE = "design_principle"
    REQUIREMENT = "requirement"
    CONVENTION = "convention"
    TEMPLATE = "template"
    DESIGN_DECISION = "design_decision"
    LAW_OR_POLICY = "law_or_policy"


class SelectorType(StrEnum):
    EXACT_ATTRIBUTES = "exact_attributes"
    PATH_PATTERN_METHOD = "path_pattern_method"
    SUBJECT_ID = "subject_id"
    SUBJECT_KIND = "subject_kind"
    RULE_SCOPE = "rule_scope"
    WLG_SHAPE_ID = "shape_id"
    WLG_KIND_IN_DOMAIN = "kind_in_domain"
    WLG_FIELD_NAME_CANONICAL = "field_name_canonical"
    WLG_LIFECYCLE_NAMESPACE = "lifecycle_namespace"


LAYER_RANK: dict[str, int] = {
    AuthorityLayer.DESIGN_PRINCIPLE.value: 10,
    AuthorityLayer.REQUIREMENT.value: 20,
    AuthorityLayer.CONVENTION.value: 30,
    AuthorityLayer.TEMPLATE.value: 30,
    AuthorityLayer.DESIGN_DECISION.value: 40,
    AuthorityLayer.LAW_OR_POLICY.value: 50,
    # WLG compatibility aliases.
    "DesignPrinciple": 10,
    "WLGRequirement": 20,
    "Convention": 30,
    "Template": 30,
    "NamingConvention": 30,
    "LifecycleTemplate": 30,
    "RouteConvention": 30,
    "FieldSemantic": 30,
    "PolicyTemplate": 30,
    "DesignDecision": 40,
}


@dataclass(frozen=True, slots=True)
class ScopeSelector:
    selector_type: str
    selector_args: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"selector_type": self.selector_type, "selector_args": dict(self.selector_args)}


@dataclass(frozen=True, slots=True)
class AuthorityRecord:
    authority_id: str
    vertical_id: str
    tenant_id: str
    layer: str
    status: str
    selector: ScopeSelector
    value: Mapping[str, Any] = field(default_factory=dict)
    source_anchor: str = ""
    version: str = "1"
    priority: int = 0
    superseded_by: str = ""
    active_from: datetime | None = None
    active_until: datetime | None = None

    def active_at(self, instant: datetime) -> bool:
        if self.status != AuthorityStatus.CONFIRMED_AUTHORITY.value or self.superseded_by:
            return False
        if self.active_from is not None and instant < self.active_from:
            return False
        return self.active_until is None or instant < self.active_until

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["selector"] = self.selector.as_dict()
        value["value"] = dict(self.value)
        value["active_from"] = self.active_from.isoformat() if self.active_from else None
        value["active_until"] = self.active_until.isoformat() if self.active_until else None
        return value


@dataclass(frozen=True, slots=True)
class AuthorityResolution:
    status: str
    selected: tuple[AuthorityRecord, ...] = ()
    conflicts: tuple[AuthorityRecord, ...] = ()
    reason: str = ""


def selector_specificity(selector: ScopeSelector) -> tuple[int, ...]:
    args = dict(selector.selector_args)
    selector_type = selector.selector_type
    if selector_type in {SelectorType.SUBJECT_ID.value, "shape_id"}:
        return (100, 1 if (args.get("subject_id") or args.get("shape_id")) else 0)
    if selector_type == SelectorType.PATH_PATTERN_METHOD.value:
        return (
            70,
            1 if args.get("domain") else 0,
            1 if args.get("method") else 0,
            2 if args.get("path") else (1 if args.get("path_glob") else 0),
            1 if args.get("locale") else 0,
        )
    if selector_type == SelectorType.EXACT_ATTRIBUTES.value:
        return (60, len(args))
    if selector_type == SelectorType.WLG_FIELD_NAME_CANONICAL.value:
        return (
            60,
            1 if args.get("domain") else 0,
            1 if args.get("kind") else 0,
            1 if args.get("field_name") else 0,
        )
    if selector_type == SelectorType.WLG_LIFECYCLE_NAMESPACE.value:
        return (
            55,
            1 if args.get("domain") else 0,
            1 if args.get("state_machine_body") else 0,
        )
    if selector_type == SelectorType.RULE_SCOPE.value:
        return (
            50,
            1 if args.get("rule_id") else 0,
            1 if args.get("domain") else 0,
            1 if args.get("kind") else 0,
        )
    if selector_type in {SelectorType.SUBJECT_KIND.value, "kind_in_domain"}:
        return (40, 1 if args.get("domain") else 0, 1 if args.get("kind") else 0)
    return (0,)


def selector_matches(selector: ScopeSelector, scope: Mapping[str, Any]) -> bool:
    args = dict(selector.selector_args)
    selector_type = selector.selector_type
    if selector_type == SelectorType.EXACT_ATTRIBUTES.value:
        return all(str(scope.get(key, "")) == str(value) for key, value in args.items())
    if selector_type in {SelectorType.SUBJECT_ID.value, "shape_id"}:
        expected = args.get("subject_id", args.get("shape_id", ""))
        actual = scope.get("subject_id", scope.get("shape_id", ""))
        return str(actual) == str(expected)
    if selector_type in {SelectorType.SUBJECT_KIND.value, "kind_in_domain"}:
        return _eq_if_present(args, scope, "domain") and _eq_if_present(args, scope, "kind")
    if selector_type == SelectorType.WLG_FIELD_NAME_CANONICAL.value:
        return (
            _eq_if_present(args, scope, "domain")
            and _eq_if_present(args, scope, "kind")
            and str(scope.get("field_name", "")) == str(args.get("field_name", ""))
        )
    if selector_type == SelectorType.WLG_LIFECYCLE_NAMESPACE.value:
        return _eq_if_present(args, scope, "domain") and str(
            scope.get("state_machine_body", "")
        ) == str(args.get("state_machine_body", ""))
    if selector_type == SelectorType.PATH_PATTERN_METHOD.value:
        if not (_eq_if_present(args, scope, "domain") and _eq_if_present(args, scope, "method")):
            return False
        if not _eq_if_present(args, scope, "locale"):
            return False
        if args.get("path"):
            return str(scope.get("path", "")) == str(args["path"])
        return not args.get("path_glob") or fnmatch(
            str(scope.get("path", "")), str(args["path_glob"])
        )
    if selector_type == SelectorType.RULE_SCOPE.value:
        rule_id = str(args.get("rule_id", ""))
        if rule_id not in {"", "*"} and str(scope.get("rule_id", "")) != rule_id:
            return False
        return _eq_if_present(args, scope, "domain") and _eq_if_present(args, scope, "kind")
    return False


def resolve_authority(
    records: Iterable[AuthorityRecord], *, scope: Mapping[str, Any], at: datetime
) -> AuthorityResolution:
    candidates = [
        record
        for record in records
        if record.active_at(at) and selector_matches(record.selector, scope)
    ]
    if not candidates:
        return AuthorityResolution(
            status="authority_gap", reason="no confirmed authority matched scope"
        )

    def key(record: AuthorityRecord) -> tuple[int, tuple[int, ...], int]:
        principle_priority = record.priority if LAYER_RANK.get(record.layer, 0) == 10 else 0
        return (
            LAYER_RANK.get(record.layer, 0),
            selector_specificity(record.selector),
            principle_priority,
        )

    best_key = max(key(record) for record in candidates)
    best = tuple(record for record in candidates if key(record) == best_key)
    if len({stable_fingerprint(dict(record.value)) for record in best}) > 1:
        return AuthorityResolution(
            status="authority_conflict",
            conflicts=best,
            reason="same-layer same-specificity authority values conflict",
        )
    return AuthorityResolution(status="authorized", selected=best)


def _eq_if_present(args: Mapping[str, Any], scope: Mapping[str, Any], key: str) -> bool:
    return not args.get(key) or str(scope.get(key, "")) == str(args[key])
