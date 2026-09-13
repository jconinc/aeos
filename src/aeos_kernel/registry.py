"""Product registry: families, instances, profiles, manifests and shared assets.

One managed product is a `ProductInstance` bound to a `ProductFamily`. The universal core
carries only what is true of every product; everything family-specific lives in a typed
family profile selected by that family. A new product supplies its family profile and its
manifest; it never requires a product condition inside the core.

The manifest is the only place product-specific policy enters the control plane. Rails and
gates read it. Nothing here hard-codes one product's shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import (
    immutable_json_object,
    required,
    thaw_json,
    utc,
)
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapRow, GapSeverity


class ProductFamilyKey(StrEnum):
    """The closed family set. Adding one is a versioned amendment, never an ad-hoc string."""

    SRG_DESK = "srg_desk"
    CONSUMER_APP = "consumer_app"
    DATA_PRODUCT = "data_product"
    API_PRODUCT = "api_product"
    INTERNAL_TOOL = "internal_tool"
    MARKETPLACE = "marketplace"


class LifecycleStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class ReleaseState(StrEnum):
    """Build and release state. Distinct from lifecycle: `launched` is never a lifecycle."""

    ONBOARDING = "onboarding"
    BUILDING = "building"
    RELEASE_CANDIDATE = "release_candidate"
    LAUNCHED = "launched"


class LiabilityClass(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class BusinessModelType(StrEnum):
    FREE = "free"
    SUBSCRIPTION = "subscription"
    USAGE = "usage"
    DATASET = "dataset"
    LICENSING = "licensing"


class RevenueRecognition(StrEnum):
    NONE = "none"
    ON_SALE = "on_sale"
    OVER_TERM = "over_term"
    ON_USAGE = "on_usage"


class FcraPosture(StrEnum):
    OUTSIDE_FCRA = "outside_fcra"
    ACCEPTS_CRA = "accepts_cra"


class ProfileFieldType(StrEnum):
    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    DATE = "date"
    ENUM = "enum"
    STRING_ARRAY = "string_array"


_TYPE_CHECKS: dict[ProfileFieldType, Any] = {
    ProfileFieldType.STRING: lambda value: isinstance(value, str) and bool(value.strip()),
    ProfileFieldType.BOOLEAN: lambda value: isinstance(value, bool),
    ProfileFieldType.INTEGER: lambda value: isinstance(value, int) and not isinstance(value, bool),
    ProfileFieldType.NUMBER: lambda value: isinstance(value, int | float)
    and not isinstance(value, bool),
    ProfileFieldType.DATE: lambda value: isinstance(value, str) and _is_iso_date(value),
    ProfileFieldType.ENUM: lambda value: isinstance(value, str) and bool(value.strip()),
    ProfileFieldType.STRING_ARRAY: lambda value: isinstance(value, list)
    and all(isinstance(item, str) and item.strip() for item in value),
}


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class ProfileFieldSpec:
    """One field a family requires of its profile."""

    name: str
    field_type: ProfileFieldType
    required_at_creation: bool = True
    allowed_values: tuple[str, ...] = ()
    default: Any = None

    def __post_init__(self) -> None:
        required(self.name, "profile field name")
        if not isinstance(self.field_type, ProfileFieldType):
            raise ContractError("profile field type is not recognized")
        if len(set(self.allowed_values)) != len(self.allowed_values):
            raise ContractError("profile field allowed values must be unique")
        if self.field_type is ProfileFieldType.ENUM and not self.allowed_values:
            raise ContractError(f"enum profile field {self.name!r} must declare allowed values")
        if self.allowed_values and self.field_type not in {
            ProfileFieldType.ENUM,
            ProfileFieldType.STRING,
            ProfileFieldType.STRING_ARRAY,
        }:
            raise ContractError(f"profile field {self.name!r} cannot constrain values by type")

    def violation(self, value: Any) -> str:
        """Return an operator-readable reason this value is not acceptable, or ``""``."""

        if not _TYPE_CHECKS[self.field_type](value):
            return f"{self.name} must be {self.field_type.value}"
        if self.allowed_values:
            offered = value if isinstance(value, list) else [value]
            unknown = [item for item in offered if item not in self.allowed_values]
            if unknown:
                permitted = ", ".join(sorted(self.allowed_values))
                return f"{self.name} value {unknown[0]!r} is not one of: {permitted}"
        return ""


@dataclass(frozen=True, slots=True)
class ProductFamily:
    """The cargo selector: what this kind of product must declare about itself."""

    key: ProductFamilyKey
    version: str
    profile_kind: str
    required_profile_fields: tuple[ProfileFieldSpec, ...]
    default_business_model: BusinessModelType
    release_coverage_thresholds: dict[str, Any] = field(default_factory=dict)
    person_subject_possible: bool = False
    marketing_launch_eligible_by_default: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.key, ProductFamilyKey):
            raise ContractError("product family key is not recognized")
        required(self.version, "family version")
        required(self.profile_kind, "profile_kind")
        if not isinstance(self.default_business_model, BusinessModelType):
            raise ContractError("family default business model is not recognized")
        names = [spec.name for spec in self.required_profile_fields]
        if len(set(names)) != len(names):
            raise ContractError("family profile fields must be uniquely named")
        object.__setattr__(
            self,
            "release_coverage_thresholds",
            immutable_json_object(self.release_coverage_thresholds, "release_coverage_thresholds"),
        )

    def field_spec(self, name: str) -> ProfileFieldSpec | None:
        return next((spec for spec in self.required_profile_fields if spec.name == name), None)


@dataclass(frozen=True, slots=True)
class FamilyProfile:
    """The typed side-record holding one family's fields for one product."""

    profile_kind: str
    product_slug: str
    fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required(self.profile_kind, "profile_kind")
        required(self.product_slug, "product_slug")
        object.__setattr__(self, "fields", immutable_json_object(self.fields, "profile fields"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_kind": self.profile_kind,
            "product_slug": self.product_slug,
            "fields": thaw_json(self.fields),
        }


@dataclass(frozen=True, slots=True)
class BusinessModel:
    model_type: BusinessModelType
    billing_required: bool
    revenue_recognition: RevenueRecognition
    pricing_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.model_type, BusinessModelType):
            raise ContractError("business model type is not recognized")
        if not isinstance(self.revenue_recognition, RevenueRecognition):
            raise ContractError("revenue recognition is not recognized")
        if self.pricing_ref:
            required(self.pricing_ref, "pricing_ref")

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_type": self.model_type.value,
            "billing_required": self.billing_required,
            "revenue_recognition": self.revenue_recognition.value,
            "pricing_ref": self.pricing_ref,
        }


class OwnerKind(StrEnum):
    FOUNDER = "founder"
    PRODUCT_LEAD = "product_lead"
    COORD_AGENT = "coord_agent"


@dataclass(frozen=True, slots=True)
class ProductOwner:
    """Who is accountable. Reassignment is a new row, never an edit."""

    product_slug: str
    role: str
    owner_kind: OwnerKind
    since: date
    escalation_role: str = ""

    def __post_init__(self) -> None:
        required(self.product_slug, "product_slug")
        required(self.role, "owner role")
        if not isinstance(self.owner_kind, OwnerKind):
            raise ContractError("owner kind is not recognized")
        if not isinstance(self.since, date):
            raise ContractError("owner since must be a date")
        if self.escalation_role:
            required(self.escalation_role, "escalation_role")

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_slug": self.product_slug,
            "role": self.role,
            "owner_kind": self.owner_kind.value,
            "since": self.since.isoformat(),
            "escalation_role": self.escalation_role,
        }


@dataclass(frozen=True, slots=True)
class Gating:
    """The approval and confidence thresholds a product runs under."""

    seed_approval_count: int = 3
    judgment_confidence_gate: float = 0.80
    park_ttl_hours: int = 72
    graduation_count: int = 25
    stale_claim_days: int = 30

    def __post_init__(self) -> None:
        if self.seed_approval_count < 0 or self.graduation_count <= 0:
            raise ContractError("gating counts must be nonnegative with a positive graduation")
        if not 0 < self.judgment_confidence_gate <= 1:
            raise ContractError("judgment confidence gate must fall in (0, 1]")
        if self.park_ttl_hours <= 0 or self.stale_claim_days <= 0:
            raise ContractError("gating windows must be positive")

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed_approval_count": self.seed_approval_count,
            "judgment_confidence_gate": self.judgment_confidence_gate,
            "park_ttl_hours": self.park_ttl_hours,
            "graduation_count": self.graduation_count,
            "stale_claim_days": self.stale_claim_days,
        }


@dataclass(frozen=True, slots=True)
class ProductManifest:
    """The only place product-specific policy enters the control plane."""

    product_slug: str
    version: str
    modules_enabled: tuple[str, ...]
    tone_profile: dict[str, Any]
    fcra_posture: FcraPosture
    credential_scopes: dict[str, Any]
    budget_caps: dict[str, Any]
    gating: Gating
    liability_class: LiabilityClass
    approval_policy_ref: str
    release_policy: dict[str, Any] = field(default_factory=dict)
    wlg_sync_policy: dict[str, Any] = field(default_factory=dict)
    task_generation_policy: dict[str, Any] = field(default_factory=dict)
    family_overrides: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required(self.product_slug, "product_slug")
        required(self.version, "manifest version")
        required(self.approval_policy_ref, "approval_policy_ref")
        if not isinstance(self.fcra_posture, FcraPosture):
            raise ContractError("fcra_posture is not recognized")
        if not isinstance(self.liability_class, LiabilityClass):
            raise ContractError("liability_class is not recognized")
        if not isinstance(self.gating, Gating):
            raise ContractError("manifest gating must be a Gating contract")
        if len(set(self.modules_enabled)) != len(self.modules_enabled):
            raise ContractError("modules_enabled must be unique")
        for key in self.modules_enabled:
            required(key, "enabled module key")
        for name in (
            "tone_profile",
            "credential_scopes",
            "budget_caps",
            "release_policy",
            "wlg_sync_policy",
            "task_generation_policy",
            "family_overrides",
        ):
            object.__setattr__(
                self, name, immutable_json_object(getattr(self, name), f"manifest {name}")
            )

    def permits(self, *, channel: str, move_type: str) -> bool:
        """Credential scopes decide which move types a channel may carry."""

        permitted = self.credential_scopes.get(channel)
        return isinstance(permitted, list) and move_type in permitted

    def budget_cap(self, name: str) -> float | None:
        value = self.budget_caps.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    def release_rule(self, name: str, fallback: Any) -> Any:
        return self.release_policy.get(name, fallback)

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_slug": self.product_slug,
            "version": self.version,
            "modules_enabled": list(self.modules_enabled),
            "tone_profile": thaw_json(self.tone_profile),
            "fcra_posture": self.fcra_posture.value,
            "credential_scopes": thaw_json(self.credential_scopes),
            "budget_caps": thaw_json(self.budget_caps),
            "gating": self.gating.as_dict(),
            "liability_class": self.liability_class.value,
            "approval_policy_ref": self.approval_policy_ref,
            "release_policy": thaw_json(self.release_policy),
            "wlg_sync_policy": thaw_json(self.wlg_sync_policy),
            "task_generation_policy": thaw_json(self.task_generation_policy),
            "family_overrides": thaw_json(self.family_overrides),
        }

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class ProductInstance:
    """One managed product. Universal fields only; the rest lives in its family profile."""

    slug: str
    family: ProductFamilyKey
    family_version: str
    display_name: str
    lifecycle_status: LifecycleStatus
    owner_role: str
    business_model: BusinessModel
    profile: FamilyProfile
    release_state: ReleaseState | None = None
    wlg_binding_id: str = ""
    launched_at: datetime | None = None
    retired_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("slug", "family_version", "display_name", "owner_role"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.family, ProductFamilyKey):
            raise ContractError("product family is not recognized")
        if not isinstance(self.lifecycle_status, LifecycleStatus):
            raise ContractError("lifecycle status is not recognized")
        if self.release_state is not None and not isinstance(self.release_state, ReleaseState):
            raise ContractError("release state is not recognized")
        if self.profile.product_slug != self.slug:
            raise ContractError("family profile belongs to a different product")
        for name in ("launched_at", "retired_at"):
            value = getattr(self, name)
            if value is not None:
                utc(value, name)
        if self.wlg_binding_id:
            required(self.wlg_binding_id, "wlg_binding_id")

    def profile_value(self, name: str, family: ProductFamily | None = None) -> Any:
        """Read a family field, falling back to the family's declared default.

        A rail that needs a field one family does not have reads it through here and takes
        the family default instead of assuming every product is a verdict desk.
        """

        if name in self.profile.fields:
            return self.profile.fields[name]
        spec = family.field_spec(name) if family is not None else None
        return spec.default if spec is not None else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "family": self.family.value,
            "family_version": self.family_version,
            "display_name": self.display_name,
            "lifecycle_status": self.lifecycle_status.value,
            "release_state": self.release_state.value if self.release_state else None,
            "owner_role": self.owner_role,
            "business_model": self.business_model.as_dict(),
            "profile": self.profile.as_dict(),
            "wlg_binding_id": self.wlg_binding_id,
            "launched_at": self.launched_at.isoformat() if self.launched_at else None,
            "retired_at": self.retired_at.isoformat() if self.retired_at else None,
        }


class SharedAssetKind(StrEnum):
    ENTITY_GRAPH = "entity_graph"
    REGIME_REGISTRY = "regime_registry"
    SOURCE_REGISTRY = "source_registry"
    TAXONOMY = "taxonomy"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class SharedAssetBinding:
    """A physical asset several products share, with exactly one owner."""

    asset_id: str
    asset_kind: SharedAssetKind
    owner_product: str
    consumer_products: tuple[str, ...]
    change_policy: str
    created_at: datetime
    status: str = "active"

    def __post_init__(self) -> None:
        required(self.asset_id, "asset_id")
        required(self.owner_product, "owner_product")
        required(self.change_policy, "change_policy")
        if not isinstance(self.asset_kind, SharedAssetKind):
            raise ContractError("shared asset kind is not recognized")
        if self.status not in {"active", "superseded"}:
            raise ContractError("shared asset status must be active or superseded")
        if len(set(self.consumer_products)) != len(self.consumer_products):
            raise ContractError("shared asset consumers must be unique")
        for slug in self.consumer_products:
            required(slug, "shared asset consumer")
        if self.owner_product in self.consumer_products:
            raise ContractError("a shared asset owner cannot also be listed as its consumer")
        utc(self.created_at, "created_at")

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_kind": self.asset_kind.value,
            "owner_product": self.owner_product,
            "consumer_products": list(self.consumer_products),
            "change_policy": self.change_policy,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ProfileValidation:
    """Why a product's profile was accepted or refused, field by field."""

    accepted: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.accepted and self.reasons:
            raise ContractError("an accepted profile validation carries no refusal reasons")
        if not self.accepted and not self.reasons:
            raise ContractError("a refused profile validation must say why")


def validate_family_profile(family: ProductFamily, profile: FamilyProfile) -> ProfileValidation:
    """Enforce the family's typed-creation contract against one profile."""

    if profile.profile_kind != family.profile_kind:
        return ProfileValidation(
            False,
            (
                f"profile kind {profile.profile_kind!r} does not match family "
                f"{family.key.value} which requires {family.profile_kind!r}",
            ),
        )
    reasons: list[str] = []
    declared = {spec.name for spec in family.required_profile_fields}
    for spec in family.required_profile_fields:
        if spec.name not in profile.fields:
            if spec.required_at_creation:
                reasons.append(f"{spec.name} is required by family {family.key.value}")
            continue
        violation = spec.violation(profile.fields[spec.name])
        if violation:
            reasons.append(violation)
    undeclared = sorted(set(profile.fields) - declared)
    reasons.extend(f"{name} is not declared by family {family.key.value}" for name in undeclared)
    return ProfileValidation(not reasons, tuple(reasons))


class FamilyRegistry:
    """The registered families. A product whose family is unregistered never runs."""

    def __init__(self, families: tuple[ProductFamily, ...] = ()) -> None:
        self._families: dict[ProductFamilyKey, ProductFamily] = {}
        for family in families:
            self.register(family)

    def register(self, family: ProductFamily) -> None:
        if family.key in self._families:
            raise ContractError(f"family {family.key.value} is already registered")
        self._families[family.key] = family

    def get(self, key: ProductFamilyKey) -> ProductFamily | None:
        return self._families.get(key)

    def require(self, key: ProductFamilyKey) -> ProductFamily:
        family = self._families.get(key)
        if family is None:
            raise ContractError(f"family {key.value} is not registered")
        return family

    @property
    def keys(self) -> tuple[ProductFamilyKey, ...]:
        return tuple(sorted(self._families, key=lambda item: item.value))


@dataclass(frozen=True, slots=True)
class RegistrationRefusal:
    """A product that cannot be admitted, with the gaps that say why."""

    reason: str
    gaps: tuple[GapRow, ...] = ()

    def __post_init__(self) -> None:
        required(self.reason, "registration refusal reason")
        if not isinstance(self.gaps, tuple):
            raise ContractError("registration refusal gaps must be a tuple, not a lazy sequence")


def register_product(
    *,
    registry: FamilyRegistry,
    instance: ProductInstance,
    manifest: ProductManifest,
    shared_assets_consumed: tuple[str, ...] = (),
    shared_asset_bindings: tuple[SharedAssetBinding, ...] = (),
    detected_at: datetime,
) -> RegistrationRefusal | None:
    """Admit one product, or refuse with operator-readable gaps.

    Returns ``None`` when the product is admissible. Registration never mutates: the host
    records the instance only after this returns clean.
    """

    family = registry.get(instance.family)
    if family is None:
        return RegistrationRefusal(
            f"family {instance.family.value} is not registered; no product runs family-less"
        )
    if family.version != instance.family_version:
        return RegistrationRefusal(
            f"product declares family version {instance.family_version} but the registered "
            f"{family.key.value} family is version {family.version}"
        )
    if manifest.product_slug != instance.slug:
        return RegistrationRefusal("manifest belongs to a different product")
    validation = validate_family_profile(family, instance.profile)
    if not validation.accepted:
        return RegistrationRefusal(
            "incomplete_family_profile: " + "; ".join(validation.reasons),
            tuple(
                GapRow(
                    gap_type="incomplete_family_profile",
                    severity=GapSeverity.ERROR,
                    product_slug=instance.slug,
                    subject_ref=instance.profile.profile_kind,
                    reason=reason,
                    detected_at=detected_at,
                )
                for reason in validation.reasons
            ),
        )
    profile_class = instance.profile.fields.get("liability_class")
    if profile_class is not None and profile_class != manifest.liability_class.value:
        return RegistrationRefusal(
            f"liability class disagrees: profile {profile_class!r} against manifest "
            f"{manifest.liability_class.value!r}"
        )
    gaps: list[GapRow] = []
    declared = set(shared_assets_consumed)
    active = {
        binding.asset_id: binding
        for binding in shared_asset_bindings
        if binding.is_active and instance.slug in binding.consumer_products
    }
    for asset_id in sorted(declared - set(active)):
        gaps.append(
            GapRow(
                gap_type="shared_asset_unbound",
                severity=GapSeverity.ERROR,
                product_slug=instance.slug,
                subject_ref=asset_id,
                reason=(
                    f"{instance.slug} declares shared asset {asset_id!r}, which has no active "
                    "binding naming it as a consumer"
                ),
                detected_at=detected_at,
            )
        )
    for asset_id in sorted(set(active) - declared):
        gaps.append(
            GapRow(
                gap_type="shared_asset_undeclared",
                severity=GapSeverity.ERROR,
                product_slug=instance.slug,
                subject_ref=asset_id,
                reason=(
                    f"{instance.slug} consumes shared asset {asset_id!r} without declaring it "
                    "at onboarding"
                ),
                detected_at=detected_at,
            )
        )
    if gaps:
        return RegistrationRefusal("shared_asset_declaration_mismatch", tuple(gaps))
    if instance.business_model.billing_required and "commercial" not in manifest.modules_enabled:
        gaps.append(
            GapRow(
                gap_type="commercial_module_not_enabled",
                severity=GapSeverity.ERROR,
                product_slug=instance.slug,
                subject_ref="commercial",
                reason=(
                    f"{instance.slug} takes payment but its manifest does not enable the "
                    "commercial module"
                ),
                detected_at=detected_at,
            )
        )
        return RegistrationRefusal("commercial_dependency_unsatisfied", tuple(gaps))
    return None


def retire_blocked_by_shared_assets(
    *, product_slug: str, bindings: tuple[SharedAssetBinding, ...]
) -> tuple[SharedAssetBinding, ...]:
    """Active bindings this product owns that still have consumers.

    Retiring a product that owns a live shared asset blocks outright. It does not park:
    a consumer would lose its spine while the approval sat in a queue.
    """

    return tuple(
        binding
        for binding in bindings
        if binding.is_active
        and binding.owner_product == product_slug
        and binding.consumer_products
    )


def launch_blockers(
    *,
    instance: ProductInstance,
    family: ProductFamily,
    release_ready: bool,
    today: date,
) -> tuple[str, ...]:
    """Family-aware launch predicate, stated as the reasons a launch cannot proceed."""

    blockers: list[str] = []
    if not release_ready:
        blockers.append("release readiness is not green")
    if instance.lifecycle_status is LifecycleStatus.RETIRED:
        blockers.append("a retired product cannot launch")
    if instance.family is ProductFamilyKey.SRG_DESK:
        if instance.profile_value("mirror", family) != "yes":
            blockers.append("no raw mirror exists, so no claim can be derived")
        verified_on = instance.profile_value("verified_on", family)
        stale_days = int(family.release_coverage_thresholds.get("verified_on_decay_days", 180))
        if isinstance(verified_on, str) and _is_iso_date(verified_on):
            if (today - date.fromisoformat(verified_on)).days > stale_days:
                blockers.append(
                    f"source verification is older than {stale_days} days ({verified_on})"
                )
        else:
            blockers.append("verified_on is missing, so source freshness is unknown")
    if (
        instance.family is ProductFamilyKey.INTERNAL_TOOL
        and instance.profile_value("public_marketing_allowed", family) is not True
    ):
        blockers.append("internal tools are not marketing-launch-eligible")
    return tuple(blockers)


def manifest_from_mapping(
    product_slug: str, values: Mapping[str, Any], *, version: str
) -> ProductManifest:
    """Build a manifest from a host's own canonical policy mapping.

    The host owns the mapping; this only types it. It never invents a policy the host did
    not state, which is why every required key raises rather than defaulting.
    """

    missing = [
        key
        for key in ("fcra_posture", "liability_class", "approval_policy_ref")
        if key not in values
    ]
    if missing:
        raise ContractError(f"manifest mapping is missing: {', '.join(missing)}")
    gating_values = dict(values.get("gating", {}))
    return ProductManifest(
        product_slug=product_slug,
        version=version,
        modules_enabled=tuple(values.get("modules_enabled", ())),
        tone_profile=dict(values.get("tone_profile", {})),
        fcra_posture=FcraPosture(values["fcra_posture"]),
        credential_scopes=dict(values.get("credential_scopes", {})),
        budget_caps=dict(values.get("budget_caps", {})),
        gating=Gating(**gating_values) if gating_values else Gating(),
        liability_class=LiabilityClass(values["liability_class"]),
        approval_policy_ref=str(values["approval_policy_ref"]),
        release_policy=dict(values.get("release_policy", {})),
        wlg_sync_policy=dict(values.get("wlg_sync_policy", {})),
        task_generation_policy=dict(values.get("task_generation_policy", {})),
        family_overrides=dict(values.get("family_overrides", {})),
    )


__all__ = [
    "BusinessModel",
    "BusinessModelType",
    "FamilyProfile",
    "FamilyRegistry",
    "FcraPosture",
    "Gating",
    "LiabilityClass",
    "LifecycleStatus",
    "OwnerKind",
    "ProductFamily",
    "ProductFamilyKey",
    "ProductInstance",
    "ProductManifest",
    "ProductOwner",
    "ProfileFieldSpec",
    "ProfileFieldType",
    "ProfileValidation",
    "RegistrationRefusal",
    "ReleaseState",
    "RevenueRecognition",
    "SharedAssetBinding",
    "SharedAssetKind",
    "launch_blockers",
    "manifest_from_mapping",
    "register_product",
    "retire_blocked_by_shared_assets",
    "validate_family_profile",
]
