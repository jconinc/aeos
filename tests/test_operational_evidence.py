"""REQ-RT-012 / SEC-055: authored for the joined run; no clock sleeps or services."""

import datetime as dt
from dataclasses import replace

import pytest

from aeos_kernel.operational_evidence import Measurement, assess, overall_health

NOW = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
SOURCE = "a" * 64
GOOD = Measurement("wema:worker", SOURCE, NOW, 0, True)


@pytest.mark.parametrize(
    "observation,reason",
    [
        (None, "observation_missing"),
        (replace(GOOD, scope="another:worker"), "observation_binding_changed"),
        (replace(GOOD, source_digest="b" * 64), "observation_binding_changed"),
        (replace(GOOD, observed_at=NOW + dt.timedelta(seconds=1)), "observation_time_invalid"),
        (replace(GOOD, observed_at=NOW.replace(tzinfo=None)), "observation_time_invalid"),
        (replace(GOOD, observed_at=NOW - dt.timedelta(seconds=301)), "observation_stale"),
        (replace(GOOD, complete=False), "observation_incomplete"),
        (replace(GOOD, complete=1), "observation_incomplete"),
        (replace(GOOD, value=None), "observation_incomplete"),
        (replace(GOOD, value=float("nan")), "observation_incomplete"),
        (replace(GOOD, value=-1), "observation_incomplete"),
        (replace(GOOD, value=True), "observation_incomplete"),
    ],
)
def test_missing_or_untrustworthy_measurement_cannot_clear(observation, reason):
    result = assess(
        observation,
        scope=GOOD.scope,
        source_digest=SOURCE,
        now=NOW,
        max_age=dt.timedelta(minutes=5),
        maximum=0,
    )
    assert (result.state, result.reason) == ("unknown", reason)


@pytest.mark.parametrize("value,state", [(0, "healthy"), (5, "healthy"), (6, "breached")])
def test_threshold_uses_actual_window(value, state):
    result = assess(
        replace(GOOD, value=value, observed_at=NOW - dt.timedelta(minutes=5)),
        scope=GOOD.scope,
        source_digest=SOURCE,
        now=NOW,
        max_age=dt.timedelta(minutes=5),
        maximum=5,
    )
    assert result.state == state


def test_missing_coverage_does_not_become_a_healthy_report():
    assert overall_health(()) == "unknown"
    assert overall_health(("healthy", "unknown")) == "unknown"
    assert overall_health(("healthy", "breached")) == "breached"
    assert overall_health(("healthy",)) == "healthy"


def test_invalid_policy_is_refused():
    with pytest.raises(ValueError):
        assess(
            GOOD,
            scope=GOOD.scope,
            source_digest=SOURCE,
            now=NOW,
            max_age=dt.timedelta(0),
            maximum=0,
        )
