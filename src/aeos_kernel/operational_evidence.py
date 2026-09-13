"""Small, host-neutral freshness gate for native operational measurements.

The host supplies observations from its authoritative store. This module does not
collect data, clear an incident, schedule work, or authorize a corrective effect.
Wema's operational_checks producer and operational health readback are its callers.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Literal

Health = Literal["healthy", "breached", "unknown"]


@dataclass(frozen=True, slots=True)
class Measurement:
    scope: str
    source_digest: str
    observed_at: dt.datetime
    value: float | None
    complete: bool


@dataclass(frozen=True, slots=True)
class Assessment:
    state: Health
    reason: str


def assess(
    observation: Measurement | None,
    *,
    scope: str,
    source_digest: str,
    now: dt.datetime,
    max_age: dt.timedelta,
    maximum: float,
) -> Assessment:
    """An unavailable, stale or differently bound measurement never proves health.

    Equality meets the ceiling. The observation must be complete even when its
    value is zero; absence of a measurement and a measured empty queue differ.
    """
    if (
        now.tzinfo is None
        or max_age <= dt.timedelta(0)
        or isinstance(maximum, bool)
        or not math.isfinite(maximum)
        or maximum < 0
        or len(source_digest) != 64
        or any(c not in "0123456789abcdef" for c in source_digest)
        or not scope
    ):
        raise ValueError("invalid operational policy")
    if observation is None:
        return Assessment("unknown", "observation_missing")
    if observation.scope != scope or observation.source_digest != source_digest:
        return Assessment("unknown", "observation_binding_changed")
    if observation.observed_at.tzinfo is None or observation.observed_at > now:
        return Assessment("unknown", "observation_time_invalid")
    if now - observation.observed_at > max_age:
        return Assessment("unknown", "observation_stale")
    if (
        observation.complete is not True
        or observation.value is None
        or isinstance(observation.value, bool)
        or not math.isfinite(observation.value)
        or observation.value < 0
    ):
        return Assessment("unknown", "observation_incomplete")
    if observation.value > maximum:
        return Assessment("breached", "threshold_exceeded")
    return Assessment("healthy", "current_observation")


def overall_health(states: tuple[Health, ...]) -> Health:
    """An empty or incomplete coverage set cannot present a healthy product."""
    if not states or "unknown" in states:
        return "unknown"
    return "breached" if "breached" in states else "healthy"
