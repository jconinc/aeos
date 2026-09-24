"""Rails: one shape, merged, and read before they are trusted."""

from __future__ import annotations

import datetime as dt

import pytest

from aeos_kernel import (
    ContractError,
    GapRow,
    MoveDecision,
    MoveFamily,
    Rail,
    RailContext,
    RailMode,
    RailRegistry,
    RailResult,
    RailVerdict,
    decide_move,
    evaluate_rails,
)
from tests.factories_control_plane import pipeline_module

NOW = dt.datetime(2026, 9, 13, 12, 0, tzinfo=dt.UTC)


def context(move_type: str = "do_thing", **facts: object) -> RailContext:
    return RailContext(
        product_slug="fictional-app", move_type=move_type, detected_at=NOW, facts=facts
    )


def rail(name: str, verdict: RailVerdict, *, mode: RailMode = RailMode.ENFORCING) -> Rail:
    def check(rail_name: str, ctx: RailContext) -> RailResult:
        if verdict in {RailVerdict.PASS, RailVerdict.NOT_APPLICABLE}:
            return RailResult(rail=rail_name, verdict=verdict)
        return RailResult(
            rail=rail_name,
            verdict=verdict,
            reason=f"{rail_name} says no",
            gaps=(ctx.gap("fictional_gap", "subject", f"{rail_name} found something"),),
        )

    return Rail(name=name, move_types=("do_thing",), check=check, mode=mode)


def test_every_rail_answers_in_the_same_shape_so_merging_is_arithmetic() -> None:
    merged = evaluate_rails(
        (rail("a.pass", RailVerdict.PASS), rail("b.hold", RailVerdict.HOLD)), context()
    )
    assert merged.decision is MoveDecision.HOLD
    assert len(merged.results) == 2


def test_a_decline_outranks_a_lexically_first_park_and_a_hold() -> None:
    """PB-99: approval cannot override a refusal; every reason remains available."""

    merged = evaluate_rails(
        (
            rail("a.park", RailVerdict.PARK),
            rail("b.decline", RailVerdict.DECLINE),
            rail("c.hold", RailVerdict.HOLD),
        ),
        context(),
    )
    assert merged.decision is MoveDecision.DECLINE
    assert merged.reasons == ("a.park says no", "b.decline says no", "c.hold says no")


def test_a_park_outranks_a_lexically_first_hold() -> None:
    """PB-99: a hold must not suppress a required approval request."""

    merged = evaluate_rails(
        (rail("a.hold", RailVerdict.HOLD), rail("b.park", RailVerdict.PARK)), context()
    )
    assert merged.decision is MoveDecision.PARKED
    assert tuple(result.verdict for result in merged.results) == (
        RailVerdict.HOLD, RailVerdict.PARK,
    )
    assert merged.reasons == ("a.hold says no", "b.park says no")


def test_an_inapplicable_enforcing_rail_cannot_override_a_decline() -> None:
    """PB-99: a rule for another move cannot turn a refusal into permission."""

    def unexpected_check(_name: str, _context: RailContext) -> RailResult:
        pytest.fail("A rail for another move must not run")

    other = Rail(name="a.other", move_types=("something_else",), check=unexpected_check)
    merged = evaluate_rails((other, rail("b.decline", RailVerdict.DECLINE)), context())
    assert merged.decision is MoveDecision.DECLINE
    assert tuple(result.verdict for result in merged.results) == (
        RailVerdict.NOT_APPLICABLE, RailVerdict.DECLINE,
    )
    assert merged.reasons == ("b.decline says no",)


def test_a_park_without_other_objections_requests_approval() -> None:
    """PB-99: correcting a mixed refusal must preserve an ordinary approval request."""

    merged = evaluate_rails((rail("a.park", RailVerdict.PARK),), context())
    assert merged.decision is MoveDecision.PARKED
    assert merged.reasons == ("a.park says no",)


def test_all_rails_passing_leaves_the_default_decision() -> None:
    merged = evaluate_rails((rail("a.pass", RailVerdict.PASS),), context())
    assert merged.decision is MoveDecision.SHIP
    assert merged.reasons == ()


def test_an_observing_rail_reports_what_it_would_have_done_and_decides_nothing() -> None:
    """Gaps-first: a rail is read for a while before it is allowed to stop anything."""

    merged = evaluate_rails(
        (rail("a.new", RailVerdict.DECLINE, mode=RailMode.OBSERVING),), context()
    )
    assert merged.decision is MoveDecision.SHIP
    assert merged.results == ()
    assert "would have decline" in merged.would_have[0]
    # Its gaps still travel: a gap is a fact about the product, and whether the rule that
    # found it is switched on does not make it less true.
    assert len(merged.gaps) == 1


def test_the_same_rail_enforcing_does_stop_the_move() -> None:
    """Control: the pass above is the mode, not the rail failing to fire."""

    merged = evaluate_rails((rail("a.new", RailVerdict.DECLINE),), context())
    assert merged.decision is MoveDecision.DECLINE


def test_a_rail_that_does_not_answer_for_this_move_says_so_rather_than_passing() -> None:
    other = Rail(
        name="x.other",
        move_types=("something_else",),
        check=lambda name, _ctx: RailResult(rail=name, verdict=RailVerdict.DECLINE, reason="no"),
    )
    merged = evaluate_rails((other,), context())
    assert merged.decision is MoveDecision.SHIP
    assert merged.results[0].verdict is RailVerdict.NOT_APPLICABLE


def test_a_rail_returning_another_rail_s_label_is_refused() -> None:
    """A copy-pasted check that kept the original's name would attribute its verdict wrongly."""

    mislabelled = Rail(
        name="a.mine",
        move_types=("do_thing",),
        check=lambda _name, _ctx: RailResult(
            rail="b.somebody_elses", verdict=RailVerdict.DECLINE, reason="no"
        ),
    )
    with pytest.raises(ContractError, match="returned a result labelled"):
        evaluate_rails((mislabelled,), context())


def test_a_rail_that_did_not_pass_must_say_why() -> None:
    with pytest.raises(ContractError, match="must say why"):
        RailResult(rail="a.silent", verdict=RailVerdict.DECLINE)


def test_a_rail_declaring_no_move_type_answers_for_nothing_and_is_refused() -> None:
    with pytest.raises(ContractError, match="must declare the move types"):
        Rail(
            name="a.empty",
            move_types=(),
            check=lambda name, _ctx: RailResult(name, RailVerdict.PASS),
        )


def test_a_move_type_no_rail_covers_is_named_so_it_cannot_run_ungated() -> None:
    registry = RailRegistry((rail("a.pass", RailVerdict.PASS),))
    assert registry.uncovered(("do_thing", "unguarded_thing")) == ("unguarded_thing",)
    assert registry.for_move("do_thing")


def test_a_rail_reads_declared_facts_rather_than_a_product() -> None:
    """A rail that could reach into an instance is one field away from assuming a family."""

    ctx = context(mirror="yes")
    assert ctx.fact("mirror") == "yes"
    # A field this family does not have reads as the default, not as an error and not as
    # another family's value.
    assert ctx.fact("consumer_surfaces", "absent") == "absent"


def test_one_rail_cannot_be_registered_twice() -> None:
    registry = RailRegistry((rail("a.pass", RailVerdict.PASS),))
    with pytest.raises(ContractError, match="already registered"):
        registry.register(rail("a.pass", RailVerdict.PASS))


def test_a_rail_handing_back_a_lazy_gap_sequence_is_refused() -> None:
    """A generator here reads as a tuple until somebody consumes it, and then it is empty.

    The same shape already cost a caller a working refusal once, so the rail result rejects
    it at construction rather than at the second read.
    """

    empty: tuple[GapRow, ...] = ()
    with pytest.raises(ContractError, match="must be a tuple"):
        RailResult(
            rail="a.lazy",
            verdict=RailVerdict.DECLINE,
            reason="no",
            gaps=(gap for gap in empty),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("malformed", "refusal"),
    [
        (
            lambda: RailResult(rail="", verdict=RailVerdict.PASS),
            "rail name",
        ),
        (
            lambda: RailResult(rail="a.odd", verdict="decline"),  # type: ignore[arg-type]
            "verdict is not recognized",
        ),
        (
            lambda: RailContext(
                product_slug="", move_type="do_thing", detected_at=NOW
            ),
            "product_slug",
        ),
        (
            lambda: RailContext(product_slug="fictional-app", move_type="", detected_at=NOW),
            "move_type",
        ),
        (
            lambda: Rail(
                name="",
                move_types=("do_thing",),
                check=lambda name, _ctx: RailResult(name, RailVerdict.PASS),
            ),
            "rail name",
        ),
        (
            lambda: Rail(
                name="a.twice",
                move_types=("do_thing", "do_thing"),
                check=lambda name, _ctx: RailResult(name, RailVerdict.PASS),
            ),
            "lists a move type twice",
        ),
        (
            lambda: Rail(
                name="a.moded",
                move_types=("do_thing",),
                check=lambda name, _ctx: RailResult(name, RailVerdict.PASS),
                mode="observing",  # type: ignore[arg-type]
            ),
            "mode is not recognized",
        ),
    ],
)
def test_a_malformed_rail_is_refused_where_it_is_built(
    malformed: object, refusal: str
) -> None:
    with pytest.raises(ContractError, match=refusal):
        malformed()  # type: ignore[operator]


def family(move_type: str) -> MoveFamily:
    found = next(
        item for item in pipeline_module().move_families if item.move_type == move_type
    )
    return found


def test_a_family_that_always_parks_starts_parked_rather_than_shipping() -> None:
    """The safe outcome must not depend on a rail being present to produce it.

    launch_product declares human_override, so an empty or all-passing rail set still routes
    it to a person. Starting at ship and relying on a rail to park would mean a deleted rail
    silently promotes an owner decision into an unattended one.
    """

    merged = decide_move(
        family=family("launch_product"), rails=(), context=context("launch_product")
    )
    assert merged.decision is MoveDecision.PARKED


def test_a_family_that_does_not_always_park_ships_when_every_rail_passes() -> None:
    passing = Rail(
        name="a.pass",
        move_types=("capture_coverage",),
        check=lambda name, _ctx: RailResult(name, RailVerdict.PASS),
    )
    merged = decide_move(
        family=family("capture_coverage"),
        rails=(passing,),
        context=context("capture_coverage"),
    )
    assert merged.decision is MoveDecision.SHIP


def test_a_rail_can_still_refuse_a_family_that_would_otherwise_park() -> None:
    """Control: the family sets the floor, it does not outrank what a rail found."""

    refusing = Rail(
        name="a.refuse",
        move_types=("launch_product",),
        check=lambda name, _ctx: RailResult(
            name, RailVerdict.DECLINE, reason="readiness is not green"
        ),
    )
    merged = decide_move(
        family=family("launch_product"),
        rails=(refusing,),
        context=context("launch_product"),
    )
    assert merged.decision is MoveDecision.DECLINE


def test_rails_for_one_move_cannot_decide_another_move() -> None:
    with pytest.raises(ContractError, match="cannot decide"):
        decide_move(
            family=family("launch_product"), rails=(), context=context("capture_coverage")
        )
