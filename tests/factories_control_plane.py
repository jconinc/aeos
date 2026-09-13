"""Fictional two-product fixtures for the control-plane contracts.

Two products of different families share one core. Nothing here names a real product,
customer, credential or channel.
"""

from __future__ import annotations

import datetime as dt

from aeos_kernel.modules import Module, MoveFamily, PriorityClass
from aeos_kernel.registry import (
    BusinessModel,
    BusinessModelType,
    FamilyProfile,
    FamilyRegistry,
    FcraPosture,
    Gating,
    LiabilityClass,
    LifecycleStatus,
    ProductFamily,
    ProductFamilyKey,
    ProductInstance,
    ProductManifest,
    ProfileFieldSpec,
    ProfileFieldType,
    ReleaseState,
    RevenueRecognition,
)

NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=dt.UTC)
TODAY = dt.date(2026, 9, 13)

DESK_FAMILY = ProductFamily(
    key=ProductFamilyKey.SRG_DESK,
    version="1.0.0",
    profile_kind="DeskProfile",
    required_profile_fields=(
        ProfileFieldSpec("cluster", ProfileFieldType.STRING),
        ProfileFieldSpec("anchor", ProfileFieldType.BOOLEAN),
        ProfileFieldSpec("mirror", ProfileFieldType.ENUM, allowed_values=("yes", "no")),
        ProfileFieldSpec("verified_on", ProfileFieldType.DATE),
        ProfileFieldSpec("person_subject", ProfileFieldType.BOOLEAN),
        ProfileFieldSpec("liability_class", ProfileFieldType.ENUM, allowed_values=("A", "B", "C")),
    ),
    default_business_model=BusinessModelType.SUBSCRIPTION,
    release_coverage_thresholds={"min_overall": 1.0, "verified_on_decay_days": 180},
    person_subject_possible=True,
)

APP_FAMILY = ProductFamily(
    key=ProductFamilyKey.CONSUMER_APP,
    version="2.1.0",
    profile_kind="AppProfile",
    required_profile_fields=(
        ProfileFieldSpec(
            "consumer_surfaces",
            ProfileFieldType.STRING_ARRAY,
            allowed_values=("watchlist", "alerts", "billing", "account", "search"),
        ),
        ProfileFieldSpec("has_billing", ProfileFieldType.BOOLEAN),
        ProfileFieldSpec(
            "pii_classes",
            ProfileFieldType.STRING_ARRAY,
            allowed_values=("email", "name", "payment", "device_id", "location", "none"),
        ),
        ProfileFieldSpec("age_gated", ProfileFieldType.BOOLEAN, default=False),
    ),
    default_business_model=BusinessModelType.SUBSCRIPTION,
    release_coverage_thresholds={"min_overall": 0.9},
)


def family_registry() -> FamilyRegistry:
    return FamilyRegistry((DESK_FAMILY, APP_FAMILY))


def desk_instance(
    slug: str = "fictional-desk", *, mirror: str = "yes", verified_on: str = "2026-08-01"
) -> ProductInstance:
    return ProductInstance(
        slug=slug,
        family=ProductFamilyKey.SRG_DESK,
        family_version="1.0.0",
        display_name="Fictional Records Desk",
        lifecycle_status=LifecycleStatus.ACTIVE,
        owner_role="fictional.owner",
        business_model=BusinessModel(
            BusinessModelType.SUBSCRIPTION, True, RevenueRecognition.OVER_TERM
        ),
        profile=FamilyProfile(
            "DeskProfile",
            slug,
            {
                "cluster": "fictional-cluster",
                "anchor": True,
                "mirror": mirror,
                "verified_on": verified_on,
                "person_subject": False,
                "liability_class": "A",
            },
        ),
        release_state=ReleaseState.BUILDING,
    )


def app_instance(slug: str = "fictional-app") -> ProductInstance:
    return ProductInstance(
        slug=slug,
        family=ProductFamilyKey.CONSUMER_APP,
        family_version="2.1.0",
        display_name="Fictional Care App",
        lifecycle_status=LifecycleStatus.ACTIVE,
        owner_role="fictional.owner",
        business_model=BusinessModel(BusinessModelType.FREE, False, RevenueRecognition.NONE),
        profile=FamilyProfile(
            "AppProfile",
            slug,
            {
                "consumer_surfaces": ["account", "search"],
                "has_billing": False,
                "pii_classes": ["email"],
                "age_gated": False,
            },
        ),
        release_state=ReleaseState.BUILDING,
    )


def manifest(
    slug: str,
    *,
    modules: tuple[str, ...] = ("pipeline",),
    credential_scopes: dict[str, object] | None = None,
    liability_class: LiabilityClass = LiabilityClass.A,
    release_policy: dict[str, object] | None = None,
    wlg_sync_policy: dict[str, object] | None = None,
) -> ProductManifest:
    return ProductManifest(
        product_slug=slug,
        version="1.0.0",
        modules_enabled=modules,
        tone_profile={"voice": "plain", "forbidden_phrases": []},
        fcra_posture=FcraPosture.OUTSIDE_FCRA,
        credential_scopes=(
            {"fictional-channel": ["post_update"]}
            if credential_scopes is None
            else credential_scopes
        ),
        budget_caps={"llm_cost_usd_day": 3.0},
        gating=Gating(),
        liability_class=liability_class,
        approval_policy_ref="fictional.owner_attested",
        release_policy=release_policy or {"max_open_error_gaps": 0},
        wlg_sync_policy=wlg_sync_policy or {"staleness_threshold_hours": 48},
    )


def pipeline_module() -> Module:
    return Module(
        key="pipeline",
        version="1.0.0",
        rule_profile_ref="fictional.pipeline@1",
        move_families=(
            MoveFamily(
                move_type="capture_coverage",
                module_key="pipeline",
                priority_class=PriorityClass.BACKGROUND,
                owner_role="fictional.owner",
                approval_policy="fictional.owner_attested",
                evidence_kinds=("coverage_snapshot",),
                rails=("pipeline.requires_active_binding",),
            ),
            MoveFamily(
                move_type="launch_product",
                module_key="pipeline",
                priority_class=PriorityClass.PRIORITY,
                owner_role="fictional.owner",
                approval_policy="fictional.owner_attested",
                evidence_kinds=("release_readiness",),
                rails=("pipeline.requires_green_readiness",),
                human_override=True,
                never_graduates=True,
                dual_control=True,
                requires_audit_record=True,
                allowed_actor_roles=("fictional.owner",),
                escalation_role="fictional.escalation",
            ),
        ),
    )


def outreach_module() -> Module:
    return Module(
        key="outreach",
        version="1.0.0",
        rule_profile_ref="fictional.outreach@1",
        move_families=(
            MoveFamily(
                move_type="post_update",
                module_key="outreach",
                priority_class=PriorityClass.NORMAL,
                owner_role="fictional.owner",
                approval_policy="fictional.owner_attested",
                evidence_kinds=("record_row",),
                rails=("outreach.requires_evidence_path",),
                human_override=True,
            ),
        ),
        module_dependencies=("pipeline",),
        required_credential_scopes=("fictional-channel",),
    )


PIPELINE_RAILS = frozenset(
    {
        "pipeline.requires_active_binding",
        "pipeline.requires_green_readiness",
        "outreach.requires_evidence_path",
    }
)
