"""Modules: the registered capability a product may switch on, and what it needs first.

Enabling a module on a product activates that module's move families and rails for that
product alone. A module whose dependencies, credentials or rails are unsatisfied does not
quietly half-load: it refuses, and says which obligation is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from aeos_kernel._validation import immutable_json_object, required, thaw_json
from aeos_kernel.errors import ContractError
from aeos_kernel.gaps import GapRow, GapSeverity
from aeos_kernel.registry import ProductManifest


class PriorityClass(StrEnum):
    """Scheduling class of a move family."""

    PRIORITY = "priority"
    NORMAL = "normal"
    BACKGROUND = "background"


@dataclass(frozen=True, slots=True)
class MoveFamily:
    """One registered kind of decision, with what backs it and who may approve it."""

    move_type: str
    module_key: str
    priority_class: PriorityClass
    owner_role: str
    approval_policy: str
    evidence_kinds: tuple[str, ...]
    rails: tuple[str, ...]
    human_override: bool = False
    never_graduates: bool = False
    long_running: bool = False
    dual_control: bool = False
    requires_audit_record: bool = False
    allowed_actor_roles: tuple[str, ...] = ()
    escalation_role: str = ""
    allowed_tools: tuple[str, ...] = ()
    args_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("move_type", "module_key", "owner_role", "approval_policy"):
            required(str(getattr(self, name)), name)
        if not isinstance(self.priority_class, PriorityClass):
            raise ContractError("move family priority class is not recognized")
        if not self.rails:
            raise ContractError(f"move family {self.move_type!r} must declare at least one rail")
        for group, label in ((self.evidence_kinds, "evidence kind"), (self.rails, "rail")):
            if len(set(group)) != len(group):
                raise ContractError(f"move family {label}s must be unique")
            for item in group:
                required(item, f"move family {label}")
        if self.never_graduates and not self.human_override:
            raise ContractError("only a parking family can be marked as never graduating")
        if self.dual_control and not (self.human_override and self.never_graduates):
            raise ContractError(
                "a dual-control family always parks and never graduates to unattended execution"
            )
        for group, label in (
            (self.allowed_actor_roles, "allowed actor role"),
            (self.allowed_tools, "allowed tool"),
        ):
            if len(set(group)) != len(group):
                raise ContractError(f"move family {label}s must be unique")
            for item in group:
                required(item, f"move family {label}")
        if self.escalation_role:
            required(self.escalation_role, "escalation_role")
        object.__setattr__(
            self, "args_schema", immutable_json_object(self.args_schema, "args_schema")
        )

    def permits_actor(self, role: str) -> bool:
        """An empty allow-list means the family is not actor-restricted."""

        return not self.allowed_actor_roles or role in self.allowed_actor_roles

    def permits_tool(self, tool: str) -> bool:
        return not self.allowed_tools or tool in self.allowed_tools

    def as_dict(self) -> dict[str, Any]:
        return {
            "move_type": self.move_type,
            "module_key": self.module_key,
            "priority_class": self.priority_class.value,
            "owner_role": self.owner_role,
            "approval_policy": self.approval_policy,
            "evidence_kinds": list(self.evidence_kinds),
            "rails": list(self.rails),
            "human_override": self.human_override,
            "never_graduates": self.never_graduates,
            "long_running": self.long_running,
            "dual_control": self.dual_control,
            "requires_audit_record": self.requires_audit_record,
            "allowed_actor_roles": list(self.allowed_actor_roles),
            "escalation_role": self.escalation_role,
            "allowed_tools": list(self.allowed_tools),
            "args_schema": thaw_json(self.args_schema),
        }


@dataclass(frozen=True, slots=True)
class Module:
    """A registered rule profile, shape extension and move-family set."""

    key: str
    version: str
    rule_profile_ref: str
    move_families: tuple[MoveFamily, ...]
    shape_extensions: tuple[str, ...] = ()
    module_dependencies: tuple[str, ...] = ()
    required_credential_scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("key", "version", "rule_profile_ref"):
            required(str(getattr(self, name)), name)
        if not self.move_families:
            raise ContractError(f"module {self.key!r} registers no move family")
        types = [family.move_type for family in self.move_families]
        if len(set(types)) != len(types):
            raise ContractError(f"module {self.key!r} registers a move type twice")
        for family in self.move_families:
            if family.module_key != self.key:
                raise ContractError(
                    f"move family {family.move_type!r} names module {family.module_key!r}"
                )
        for group, label in (
            (self.shape_extensions, "shape extension"),
            (self.module_dependencies, "module dependency"),
            (self.required_credential_scopes, "credential scope"),
        ):
            if len(set(group)) != len(group):
                raise ContractError(f"module {label}s must be unique")
            for item in group:
                required(item, f"module {label}")
        if self.key in self.module_dependencies:
            raise ContractError(f"module {self.key!r} cannot depend on itself")

    @property
    def move_types(self) -> tuple[str, ...]:
        return tuple(family.move_type for family in self.move_families)

    def family(self, move_type: str) -> MoveFamily | None:
        return next(
            (item for item in self.move_families if item.move_type == move_type),
            None,
        )


@dataclass(frozen=True, slots=True)
class LoadedModules:
    """What a product may actually do right now, and what stopped the rest."""

    product_slug: str
    active: tuple[Module, ...]
    refused: tuple[str, ...]
    gaps: tuple[GapRow, ...]

    @property
    def move_types(self) -> tuple[str, ...]:
        return tuple(sorted({move for module in self.active for move in module.move_types}))

    def family(self, move_type: str) -> MoveFamily | None:
        for module in self.active:
            found = module.family(move_type)
            if found is not None:
                return found
        return None

    def is_active(self, module_key: str) -> bool:
        return any(module.key == module_key for module in self.active)


class ModuleRegistry:
    """Every module key the control plane knows. The loader, not a list, admits them."""

    def __init__(self, modules: tuple[Module, ...] = ()) -> None:
        self._modules: dict[str, Module] = {}
        for module in modules:
            self.register(module)

    def register(self, module: Module) -> None:
        if module.key in self._modules:
            raise ContractError(f"module {module.key!r} is already registered")
        claimed = {
            move_type: existing.key
            for existing in self._modules.values()
            for move_type in existing.move_types
        }
        for move_type in module.move_types:
            if move_type in claimed:
                raise ContractError(
                    f"move type {move_type!r} is already registered by module "
                    f"{claimed[move_type]!r}; a move belongs to exactly one family"
                )
        self._modules[module.key] = module

    def get(self, key: str) -> Module | None:
        return self._modules.get(key)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._modules))

    def family(self, move_type: str) -> MoveFamily | None:
        for module in self._modules.values():
            found = module.family(move_type)
            if found is not None:
                return found
        return None


def load_modules(
    *,
    registry: ModuleRegistry,
    manifest: ProductManifest,
    available_rails: frozenset[str],
    detected_at: datetime,
) -> LoadedModules:
    """Activate the manifest's modules for one product, refusing the unsatisfiable ones.

    Refusal is per module: a product whose ``alerts`` module lacks a credential still runs
    its other modules. The unmet obligation becomes a gap, not a silent absence.
    """

    requested = tuple(manifest.modules_enabled)
    unknown = [key for key in requested if registry.get(key) is None]
    known = [key for key in requested if registry.get(key) is not None]
    gaps: list[GapRow] = [
        GapRow(
            gap_type="module_not_registered",
            severity=GapSeverity.ERROR,
            product_slug=manifest.product_slug,
            subject_ref=key,
            reason=f"manifest enables module {key!r}, which is not registered",
            detected_at=detected_at,
        )
        for key in unknown
    ]
    refused: list[str] = list(unknown)
    accepted: dict[str, Module] = {}
    pending: list[Module] = [module for key in known if (module := registry.get(key)) is not None]
    # Dependencies chain, so keep admitting until a whole pass admits nothing new.
    while True:
        admissible = [
            module
            for module in pending
            if all(key in accepted for key in module.module_dependencies)
        ]
        if not admissible:
            break
        for module in admissible:
            accepted[module.key] = module
            pending.remove(module)
    for module in pending:
        unmet = sorted(key for key in module.module_dependencies if key not in accepted)
        refused.append(module.key)
        gaps.append(
            GapRow(
                gap_type="module_dependency_unsatisfied",
                severity=GapSeverity.ERROR,
                product_slug=manifest.product_slug,
                subject_ref=module.key,
                reason=(
                    f"module {module.key!r} needs {', '.join(unmet)}, which "
                    f"{manifest.product_slug} does not have active"
                ),
                detected_at=detected_at,
            )
        )
    active: list[Module] = []
    for module in sorted(accepted.values(), key=lambda item: item.key):
        missing_scopes = sorted(
            scope for scope in module.required_credential_scopes
            if scope not in manifest.credential_scopes
        )
        missing_rails = sorted(
            {rail for family in module.move_families for rail in family.rails} - available_rails
        )
        if missing_scopes:
            refused.append(module.key)
            gaps.append(
                GapRow(
                    gap_type="module_credential_unsatisfied",
                    severity=GapSeverity.ERROR,
                    product_slug=manifest.product_slug,
                    subject_ref=module.key,
                    reason=(
                        f"module {module.key!r} requires credential scope(s) "
                        f"{', '.join(missing_scopes)}, which the manifest does not grant"
                    ),
                    detected_at=detected_at,
                )
            )
            continue
        if missing_rails:
            refused.append(module.key)
            gaps.append(
                GapRow(
                    gap_type="move_type_ungated",
                    severity=GapSeverity.ERROR,
                    product_slug=manifest.product_slug,
                    subject_ref=module.key,
                    reason=(
                        f"module {module.key!r} declares rail(s) {', '.join(missing_rails)} "
                        "that no enabled rule profile provides; no family executes ungated"
                    ),
                    detected_at=detected_at,
                )
            )
            continue
        active.append(module)
    # A module admitted before a dependency was refused must not stay active.
    while True:
        active_keys = {module.key for module in active}
        dropped = [
            module
            for module in active
            if any(key not in active_keys for key in module.module_dependencies)
        ]
        if not dropped:
            break
        for module in dropped:
            active.remove(module)
            refused.append(module.key)
            unmet = sorted(key for key in module.module_dependencies if key not in active_keys)
            gaps.append(
                GapRow(
                    gap_type="module_dependency_unsatisfied",
                    severity=GapSeverity.ERROR,
                    product_slug=manifest.product_slug,
                    subject_ref=module.key,
                    reason=(
                        f"module {module.key!r} was dropped because its dependency "
                        f"{', '.join(unmet)} could not be activated"
                    ),
                    detected_at=detected_at,
                )
            )
    return LoadedModules(
        product_slug=manifest.product_slug,
        active=tuple(active),
        refused=tuple(sorted(set(refused))),
        gaps=tuple(gaps),
    )


__all__ = [
    "LoadedModules",
    "Module",
    "ModuleRegistry",
    "MoveFamily",
    "PriorityClass",
    "load_modules",
]
