"""Scheduling: what may run now, for which product, without waiting on the others.

Two cadences. A move decides against its own product's state and never waits for portfolio
arithmetic. A sweep does the cross-product work on its own clock.

One product's fault stops that product. The single exception is a sending domain several
products share: its cooldown stops outbound on that channel everywhere, because the fault
unit for deliverability really is the domain — and nothing else on those products stops.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, TypeVar

from aeos_kernel._validation import immutable_json_object, required, thaw_json, utc
from aeos_kernel.errors import ContractError
from aeos_kernel.modules import MoveFamily, PriorityClass
from aeos_kernel.moves import MoveRequest

_Result = TypeVar("_Result")

_PRIORITY_ORDER: dict[PriorityClass, int] = {
    PriorityClass.PRIORITY: 0,
    PriorityClass.NORMAL: 1,
    PriorityClass.BACKGROUND: 2,
}


class ChannelKind(StrEnum):
    EMAIL_DOMAIN = "email_domain"
    SOCIAL_ACCOUNT = "social_account"
    DIRECTORY = "directory"
    WEB_SURFACE = "web_surface"


class ChannelState(StrEnum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class Channel:
    """A sending domain or posting surface, and every product that shares it."""

    key: str
    kind: ChannelKind
    state: ChannelState
    product_slugs: tuple[str, ...]
    cooldown_until: datetime | None = None
    cooldown_reason: str = ""
    health: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required(self.key, "channel key")
        if not isinstance(self.kind, ChannelKind):
            raise ContractError("channel kind is not recognized")
        if not isinstance(self.state, ChannelState):
            raise ContractError("channel state is not recognized")
        if not self.product_slugs:
            raise ContractError("a channel must name the products that share it")
        if len(set(self.product_slugs)) != len(self.product_slugs):
            raise ContractError("channel products must be unique")
        for slug in self.product_slugs:
            required(slug, "channel product")
        if self.state is ChannelState.COOLDOWN:
            required(self.cooldown_reason, "cooldown_reason")
            if self.cooldown_until is None:
                raise ContractError("a channel in cooldown must say when it is reconsidered")
            utc(self.cooldown_until, "cooldown_until")
        object.__setattr__(self, "health", immutable_json_object(self.health, "channel health"))

    def blocks_outbound(self, *, now: datetime) -> bool:
        if self.state is ChannelState.REVOKED:
            return True
        if self.state is not ChannelState.COOLDOWN:
            return False
        return self.cooldown_until is None or now < self.cooldown_until

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind.value,
            "state": self.state.value,
            "product_slugs": list(self.product_slugs),
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "cooldown_reason": self.cooldown_reason,
            "health": thaw_json(self.health),
        }


@dataclass(frozen=True, slots=True)
class ProductFault:
    """A product-scoped fault. It never leaves the product it belongs to."""

    product_slug: str
    fault_type: str
    reason: str
    detected_at: datetime
    halts_module_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("product_slug", "fault_type", "reason"):
            required(str(getattr(self, name)), name)
        utc(self.detected_at, "detected_at")
        if len(set(self.halts_module_keys)) != len(self.halts_module_keys):
            raise ContractError("halted module keys must be unique")


@dataclass(frozen=True, slots=True)
class AdmissionRefusal:
    """Why one move may not run now, with the scope the refusal belongs to."""

    reason: str
    scope: str
    retry_after: datetime | None = None

    def __post_init__(self) -> None:
        required(self.reason, "refusal reason")
        required(self.scope, "refusal scope")


def admit_move(
    *,
    request: MoveRequest,
    family: MoveFamily,
    faults: tuple[ProductFault, ...],
    channels: tuple[Channel, ...],
    channel_key: str = "",
    now: datetime,
) -> AdmissionRefusal | None:
    """Decide whether one move may run, reading only what that move's own subject needs.

    Returns ``None`` to admit. Every refusal names its scope so an operator can see whether
    one product stalled or one shared sending domain did.
    """

    utc(now, "now")
    for fault in faults:
        if fault.product_slug != request.product_slug:
            # Another product's fault is not this product's business.
            continue
        if not fault.halts_module_keys or family.module_key in fault.halts_module_keys:
            return AdmissionRefusal(
                reason=f"{request.product_slug} is halted: {fault.reason}",
                scope=f"product:{request.product_slug}",
            )
    if channel_key:
        channel = next((item for item in channels if item.key == channel_key), None)
        if channel is None:
            return AdmissionRefusal(
                reason=f"channel {channel_key!r} is not registered",
                scope=f"channel:{channel_key}",
            )
        if request.product_slug not in channel.product_slugs:
            return AdmissionRefusal(
                reason=f"{request.product_slug} does not send on channel {channel_key!r}",
                scope=f"channel:{channel_key}",
            )
        if channel.blocks_outbound(now=now):
            return AdmissionRefusal(
                reason=(
                    f"channel {channel_key!r} is in {channel.state.value}: "
                    f"{channel.cooldown_reason or 'revoked'}. Outbound stops for every product "
                    "on this sending domain; their other work continues."
                ),
                scope=f"channel:{channel_key}",
                retry_after=channel.cooldown_until,
            )
    return None


def drain_order(
    requests: tuple[MoveRequest, ...],
    *,
    now: datetime,
) -> tuple[MoveRequest, ...]:
    """Order the queue: urgent first, then oldest first inside a class."""

    utc(now, "now")
    return tuple(
        sorted(
            requests,
            key=lambda item: (
                _PRIORITY_ORDER[item.priority_class],
                item.requested_at,
                item.request_id,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class Preemption:
    """A background item set aside so an urgent one on the same product can run."""

    preempted_request_id: str
    by_request_id: str
    product_slug: str
    reason: str


def preemptions(
    requests: tuple[MoveRequest, ...], *, in_flight: tuple[MoveRequest, ...]
) -> tuple[Preemption, ...]:
    """Urgent work displaces background work on the same product, and only there."""

    urgent = [item for item in requests if item.priority_class is PriorityClass.PRIORITY]
    results: list[Preemption] = []
    for pending in urgent:
        for running in in_flight:
            if running.product_slug != pending.product_slug:
                continue
            if running.priority_class is not PriorityClass.BACKGROUND:
                continue
            results.append(
                Preemption(
                    preempted_request_id=running.request_id,
                    by_request_id=pending.request_id,
                    product_slug=pending.product_slug,
                    reason=(
                        f"{pending.move_type} is urgent for {pending.product_slug}; "
                        f"background {running.move_type} yields until it finishes"
                    ),
                )
            )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class ValidationScope:
    """What a per-move validation is allowed to read.

    Subject ids are required. A validator with no scope would rescan the whole archive, and
    the cost of that grows with the ledger until it breaks the operator's response time.
    """

    product_slug: str
    subject_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        required(self.product_slug, "product_slug")
        if not self.subject_ids:
            raise ContractError(
                "a per-move validation must name its subjects; an unscoped rescan is refused"
            )
        if len(set(self.subject_ids)) != len(self.subject_ids):
            raise ContractError("validation subject ids must be unique")
        for subject_id in self.subject_ids:
            required(subject_id, "validation subject id")

    def contains(self, *, product_slug: str, subject_id: str) -> bool:
        return product_slug == self.product_slug and subject_id in self.subject_ids


def run_scoped_validation(
    *,
    scope: ValidationScope,
    validator: Callable[[ValidationScope], tuple[_Result, ...]],
    belongs_to: Callable[[_Result], tuple[str, str]],
) -> tuple[_Result, ...]:
    """Run one validator inside its scope and refuse a result that escaped it.

    The check is not decoration: a validator that quietly widened would pass unnoticed until
    the ledger made it slow, and by then its results would already be trusted.
    """

    produced = validator(scope)
    escaped = [
        item
        for item in produced
        if not scope.contains(
            product_slug=belongs_to(item)[0], subject_id=belongs_to(item)[1]
        )
    ]
    if escaped:
        product_slug, subject_id = belongs_to(escaped[0])
        raise ContractError(
            f"a scoped validation for {scope.product_slug} returned a result about "
            f"{product_slug}/{subject_id}, which is outside its scope"
        )
    return produced


@dataclass(frozen=True, slots=True)
class SweepPlan:
    """The cross-product cadence. Nothing on the per-move path waits for this."""

    sweep_id: str
    product_slugs: tuple[str, ...]
    tasks: tuple[str, ...]
    scheduled_for: datetime

    def __post_init__(self) -> None:
        required(self.sweep_id, "sweep_id")
        if not self.product_slugs:
            raise ContractError("a sweep must name the products it covers")
        if not self.tasks:
            raise ContractError("a sweep must name the work it performs")
        for group, label in ((self.product_slugs, "product"), (self.tasks, "task")):
            if len(set(group)) != len(group):
                raise ContractError(f"sweep {label}s must be unique")
            for item in group:
                required(item, f"sweep {label}")
        utc(self.scheduled_for, "scheduled_for")

    def excludes(self, product_slug: str) -> bool:
        return product_slug not in self.product_slugs


def resolve_adapter(
    *, credential_scopes: dict[str, Any], move_type: str, channel_key: str
) -> str | None:
    """Resolve a product's channel adapter at move time from its own manifest.

    Late binding is the point: a product brings its own delivery surface, and the control
    plane learns about it when the move runs rather than at build time.
    """

    permitted = credential_scopes.get(channel_key)
    if not isinstance(permitted, list) or move_type not in permitted:
        return None
    return channel_key


__all__ = [
    "AdmissionRefusal",
    "Channel",
    "ChannelKind",
    "ChannelState",
    "Preemption",
    "ProductFault",
    "SweepPlan",
    "ValidationScope",
    "admit_move",
    "drain_order",
    "preemptions",
    "resolve_adapter",
    "run_scoped_validation",
]
