"""Focused refusal controls for the integrated business control plane.

These cases exercise the edges that a happy-path readiness run cannot reach: malformed
records, missing scope and a dependency whose rail is unavailable.  They keep the control
plane fail-closed while raising the branch floor with small, direct fixtures.
"""

from __future__ import annotations

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.modules import Module, ModuleRegistry, MoveFamily, PriorityClass, load_modules
from aeos_kernel.moves import MoveRequest, RequestedBy
from aeos_kernel.pipeline import (
    BindingStatus,
    CoverageSnapshot,
    GateManifestEntry,
    GateStatus,
    MirroredTask,
    PipelineGateDecision,
    PipelineGateKind,
    PipelineOutcome,
    PredicateKind,
    ProductGateManifest,
    ProductHealth,
    Readiness,
    RegistryRef,
    ReleaseReadiness,
    TaskBatch,
    ValidationSnapshot,
    WLGProjectBinding,
)
from aeos_kernel.registry import ReleaseState
from aeos_kernel.release_conditions import BlockingCondition
from aeos_kernel.scheduling import (
    AdmissionRefusal,
    Channel,
    ChannelKind,
    ChannelState,
    ProductFault,
    SweepPlan,
    ValidationScope,
    admit_move,
)
from tests.factories_control_plane import NOW, TODAY, manifest


def _family(
    *, module_key: str = "edge", move_type: str = "edge_move", rail: str = "edge.rail"
) -> MoveFamily:
    return MoveFamily(
        move_type=move_type,
        module_key=module_key,
        priority_class=PriorityClass.NORMAL,
        owner_role="fictional.owner",
        approval_policy="fictional.owner_attested",
        evidence_kinds=("record",),
        rails=(rail,),
    )


def _module(
    key: str = "edge",
    *,
    dependencies: tuple[str, ...] = (),
    credentials: tuple[str, ...] = (),
    family: MoveFamily | None = None,
) -> Module:
    return Module(
        key=key,
        version="1.0.0",
        rule_profile_ref=f"fictional.{key}@1",
        move_families=(family or _family(module_key=key, move_type=f"{key}_move"),),
        module_dependencies=dependencies,
        required_credential_scopes=credentials,
    )


def _registry_ref(project_id: str = "project") -> RegistryRef:
    return RegistryRef(
        project_id=project_id,
        registry_locator="fictional://registry",
        registry_sha256="a" * 64,
        row_count=1,
        captured_at=NOW,
        snapshot_ref="snapshot",
    )


def _binding(
    *, project_id: str = "project", status: BindingStatus = BindingStatus.ACTIVE
) -> WLGProjectBinding:
    ref = _registry_ref(project_id)
    return WLGProjectBinding(
        binding_id="binding",
        product_slug="fictional-app",
        project_id=project_id,
        requirements_ref=ref,
        shape_ref=ref,
        bound_at=NOW,
        bound_by="fictional.owner",
        status=status,
    )


def _coverage(**overrides: object) -> CoverageSnapshot:
    values: dict[str, object] = {
        "snapshot_id": "coverage",
        "binding_id": "binding",
        "product_slug": "fictional-app",
        "snapshot_ref": "snapshot",
        "captured_at": NOW,
        "total_requirements": 1,
        "covered_requirements": 1,
        "uncovered_requirement_ids": (),
    }
    values.update(overrides)
    return CoverageSnapshot(**values)  # type: ignore[arg-type]


def _validation(**overrides: object) -> ValidationSnapshot:
    values: dict[str, object] = {
        "snapshot_id": "validation",
        "binding_id": "binding",
        "product_slug": "fictional-app",
        "snapshot_ref": "snapshot",
        "captured_at": NOW,
        "error_gap_count": 0,
        "warning_gap_count": 0,
        "prior_warning_gap_count": 0,
        "gate_status": {"fictional_gate": True},
    }
    values.update(overrides)
    return ValidationSnapshot(**values)  # type: ignore[arg-type]


def test_channel_and_product_fault_contracts_refuse_incomplete_scope() -> None:
    with pytest.raises(ContractError):
        Channel("channel", "email_domain", ChannelState.ACTIVE, ("fictional-app",))  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        Channel("channel", ChannelKind.EMAIL_DOMAIN, "active", ("fictional-app",))  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        Channel("channel", ChannelKind.EMAIL_DOMAIN, ChannelState.ACTIVE, ())
    with pytest.raises(ContractError):
        Channel(
            "channel",
            ChannelKind.EMAIL_DOMAIN,
            ChannelState.ACTIVE,
            ("fictional-app", "fictional-app"),
        )
    with pytest.raises(ContractError):
        Channel("channel", ChannelKind.EMAIL_DOMAIN, ChannelState.ACTIVE, ("",))
    with pytest.raises(ContractError):
        Channel(
            "channel",
            ChannelKind.EMAIL_DOMAIN,
            ChannelState.COOLDOWN,
            ("fictional-app",),
            cooldown_until=NOW,
        )
    with pytest.raises(ContractError):
        Channel(
            "channel",
            ChannelKind.EMAIL_DOMAIN,
            ChannelState.COOLDOWN,
            ("fictional-app",),
            cooldown_reason="maintenance",
        )
    with pytest.raises(ContractError):
        ProductFault("fictional-app", "incident", "blocked", NOW, ("x", "x"))


def test_sweep_and_validation_scope_require_named_unique_work() -> None:
    with pytest.raises(ContractError):
        SweepPlan("sweep", (), ("task",), NOW)
    with pytest.raises(ContractError):
        SweepPlan("sweep", ("fictional-app",), (), NOW)
    with pytest.raises(ContractError):
        SweepPlan("sweep", ("fictional-app", "fictional-app"), ("task",), NOW)
    with pytest.raises(ContractError):
        SweepPlan("sweep", ("fictional-app",), ("task", "task"), NOW)
    with pytest.raises(ContractError):
        SweepPlan("sweep", ("",), ("task",), NOW)
    with pytest.raises(ContractError):
        SweepPlan("sweep", ("fictional-app",), ("",), NOW)
    with pytest.raises(ContractError):
        ValidationScope("fictional-app", ())
    with pytest.raises(ContractError):
        ValidationScope("fictional-app", ("subject", "subject"))
    with pytest.raises(ContractError):
        ValidationScope("fictional-app", ("",))


def test_move_family_and_module_registration_refuse_ambiguous_declarations() -> None:
    with pytest.raises(ContractError):
        _family().__class__(
            move_type="move",
            module_key="edge",
            priority_class="normal",  # type: ignore[arg-type]
            owner_role="owner",
            approval_policy="policy",
            evidence_kinds=("record",),
            rails=("rail",),
        )
    with pytest.raises(ContractError):
        _family(rail="")
    with pytest.raises(ContractError):
        MoveFamily(
            move_type="move",
            module_key="edge",
            priority_class=PriorityClass.NORMAL,
            owner_role="owner",
            approval_policy="policy",
            evidence_kinds=("record", "record"),
            rails=("rail",),
        )
    with pytest.raises(ContractError):
        MoveFamily(
            move_type="move",
            module_key="edge",
            priority_class=PriorityClass.NORMAL,
            owner_role="owner",
            approval_policy="policy",
            evidence_kinds=("record",),
            rails=("rail",),
            allowed_actor_roles=("owner", "owner"),
        )
    with pytest.raises(ContractError):
        MoveFamily(
            move_type="move",
            module_key="edge",
            priority_class=PriorityClass.NORMAL,
            owner_role="owner",
            approval_policy="policy",
            evidence_kinds=("record",),
            rails=("rail",),
            never_graduates=True,
        )
    with pytest.raises(ContractError):
        MoveFamily(
            move_type="move",
            module_key="edge",
            priority_class=PriorityClass.NORMAL,
            owner_role="owner",
            approval_policy="policy",
            evidence_kinds=("record",),
            rails=("rail",),
            dual_control=True,
        )
    with pytest.raises(ContractError):
        Module("edge", "1.0.0", "profile", ())
    with pytest.raises(ContractError):
        Module(
            "edge",
            "1.0.0",
            "profile",
            (_family(module_key="other"),),
        )
    with pytest.raises(ContractError):
        Module(
            "edge",
            "1.0.0",
            "profile",
            (_family(module_key="edge"),),
            module_dependencies=("edge",),
        )
    registry = ModuleRegistry((_module("edge"),))
    with pytest.raises(ContractError):
        registry.register(_module("edge"))
    with pytest.raises(ContractError):
        registry.register(
            _module("other", family=_family(module_key="other", move_type="edge_move"))
        )
    assert registry.family("missing") is None


def test_module_loader_drops_a_dependent_when_its_dependency_loses_a_rail() -> None:
    dependency = _module("dependency", family=_family(module_key="dependency", rail="dep.rail"))
    dependent = _module(
        "dependent",
        dependencies=("dependency",),
        family=_family(module_key="dependent", move_type="dependent_move", rail="dependent.rail"),
    )
    loaded = load_modules(
        registry=ModuleRegistry((dependency, dependent)),
        manifest=manifest("fictional-app", modules=("dependency", "dependent")),
        available_rails=frozenset({"dependent.rail"}),
        detected_at=NOW,
    )
    assert loaded.active == ()
    assert set(loaded.refused) == {"dependency", "dependent"}
    assert [gap.gap_type for gap in loaded.gaps] == [
        "move_type_ungated",
        "module_dependency_unsatisfied",
    ]


def test_remaining_module_and_scheduling_edges_are_fail_closed() -> None:
    with pytest.raises(ContractError):
        MoveFamily(
            move_type="move",
            module_key="edge",
            priority_class=PriorityClass.NORMAL,
            owner_role="owner",
            approval_policy="policy",
            evidence_kinds=("record",),
            rails=(),
        )
    loaded = load_modules(
        registry=ModuleRegistry((_module(),)),
        manifest=manifest("fictional-app", modules=()),
        available_rails=frozenset(),
        detected_at=NOW,
    )
    assert loaded.family("missing") is None
    assert not loaded.is_active("edge")
    active = load_modules(
        registry=ModuleRegistry((_module(),)),
        manifest=manifest("fictional-app", modules=("edge",)),
        available_rails=frozenset({"edge.rail"}),
        detected_at=NOW,
    )
    assert active.family("missing") is None
    assert active.family("edge_move") is not None
    request = MoveRequest(
        request_id="request",
        product_slug="fictional-app",
        move_type="edge_move",
        as_of=TODAY,
        priority_class=PriorityClass.NORMAL,
        requested_by=RequestedBy.SCHEDULE,
        requested_at=NOW,
        args={},
    )
    refusal = admit_move(
        request=request,
        family=_family(move_type="edge_move"),
        faults=(),
        channels=(),
        channel_key="missing-channel",
        now=NOW,
    )
    assert isinstance(refusal, AdmissionRefusal)
    assert "not registered" in refusal.reason


def test_pipeline_records_refuse_invalid_identity_counts_and_states() -> None:
    with pytest.raises(ContractError):
        RegistryRef("project", "fictional://registry", "a" * 64, -1, NOW, "snapshot")
    with pytest.raises(ContractError):
        WLGProjectBinding(
            "binding",
            "fictional-app",
            "project",
            _registry_ref("other"),
            _registry_ref("project"),
            NOW,
            "owner",
        )
    with pytest.raises(ContractError):
        WLGProjectBinding(
            "binding",
            "fictional-app",
            "project",
            _registry_ref("project"),
            _registry_ref("other"),
            NOW,
            "owner",
        )
    with pytest.raises(ContractError):
        _coverage(total_requirements=-1)
    with pytest.raises(ContractError):
        _coverage(total_requirements=1, covered_requirements=2)
    with pytest.raises(ContractError):
        _coverage(uncovered_requirement_ids=("REQ-1", "REQ-1"))
    with pytest.raises(ContractError):
        _coverage(orphan_shape_count=-1)
    with pytest.raises(ContractError):
        _validation(error_gap_count=-1)
    with pytest.raises(ContractError):
        _validation(gate_status={})
    with pytest.raises(ContractError):
        _validation(gate_status={"fictional_gate": "yes"})  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        WLGProjectBinding(
            "binding",
            "fictional-app",
            "project",
            _registry_ref("project"),
            _registry_ref("project"),
            NOW,
            "owner",
            status="active",  # type: ignore[arg-type]
        )
    assert (
        _validation(gaps_by_rule={"rule": {"error": 0}, "missing": {}}).failing_rules(
            ("rule", "missing")
        )
        == ()
    )


def test_pipeline_gate_batch_health_and_readiness_edges_remain_explicit() -> None:
    with pytest.raises(ContractError):
        GateManifestEntry("gate", "description", "custom", GateStatus.OPEN, True)  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        GateManifestEntry("gate", "description", PredicateKind.CUSTOM, "open", True)  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        GateManifestEntry("gate", "description", PredicateKind.CUSTOM, GateStatus.GREEN, True)
    with pytest.raises(ContractError):
        GateManifestEntry(
            "gate", "description", PredicateKind.CUSTOM, GateStatus.OPEN, True, "stale-evidence"
        )
    with pytest.raises(ContractError):
        ProductGateManifest("manifest", "fictional-app", (), "source", NOW, "snapshot", version=0)
    gate = GateManifestEntry(
        "gate", "description", PredicateKind.CUSTOM, GateStatus.GREEN, True, "evidence"
    )
    with pytest.raises(ContractError):
        ProductGateManifest("manifest", "fictional-app", (gate, gate), "source", NOW, "snapshot")
    with pytest.raises(ContractError):
        ReleaseReadiness(
            "fictional-app", Readiness.GREEN, ("blocked",), NOW, "", "", "",
            (BlockingCondition("coverage_below_minimum", (), "blocked"),),
        )
    with pytest.raises(ContractError):
        ReleaseReadiness("fictional-app", Readiness.BLOCKED, (), NOW, "", "", "", ())
    with pytest.raises(ContractError):
        PipelineGateDecision(
            "decision",
            "fictional-app",
            "run",
            "release_readiness",  # type: ignore[arg-type]
            ReleaseState.BUILDING,
            ReleaseState.BUILDING,
            PipelineOutcome.BLOCK,
            "reason",
            NOW,
        )
    with pytest.raises(ContractError):
        PipelineGateDecision(
            "decision",
            "fictional-app",
            "run",
            PipelineGateKind.RELEASE_READINESS,
            ReleaseState.BUILDING,
            ReleaseState.BUILDING,
            "block",  # type: ignore[arg-type]
            "reason",
            NOW,
        )
    with pytest.raises(ContractError):
        TaskBatch("batch", "binding", "fictional-app", "move", "bad", False, 0, 0, "c", "v", NOW)
    with pytest.raises(ContractError):
        TaskBatch("batch", "binding", "fictional-app", "move", "rule", False, -1, 0, "c", "v", NOW)
    with pytest.raises(ContractError):
        MirroredTask("task", "batch", "external", "rule", "claimed", False)  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        ProductHealth("fictional-app", NOW, -0.1, 0, 0, 0, None, None, 0)
    with pytest.raises(ContractError):
        ProductHealth("fictional-app", NOW, 0.5, 0, 0, 0, None, -1, 0)
    with pytest.raises(ContractError):
        ProductHealth("fictional-app", NOW, 1.1, 0, 0, 0, None, None, 0)
    with pytest.raises(ContractError):
        ProductHealth("fictional-app", NOW, 0.5, -1, 0, 0, None, None, 0)


def test_pipeline_health_keeps_unmeasured_queue_distinct_from_empty() -> None:
    health = ProductHealth("fictional-app", NOW, 0.2, 0, 0, 0, None, None, 0)
    assert health.as_dict()["open_tasks"] == "unmeasured"
    assert "open_build_tasks" not in {key for key in health.as_dict() if key == "open_build_tasks"}
    assert health.health_score == "stalled"
