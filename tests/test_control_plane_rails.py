"""Rails: one shape, merged, and read before they are trusted."""

from __future__ import annotations

import datetime as dt

import pytest

from aeos_kernel import (
    ContractError,
    GapRow,
    MoveDecision,
    Rail,
    RailContext,
    RailMode,
    RailRegistry,
    RailResult,
    RailVerdict,
    evaluate_rails,
)

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


def test_the_strongest_verdict_wins_and_a_park_outranks_a_decline() -> None:
    """A person being asked is a stronger outcome than a refusal: the refusal may be wrong."""

    merged = evaluate_rails(
        (
            rail("a.decline", RailVerdict.DECLINE),
            rail("b.park", RailVerdict.PARK),
            rail("c.hold", RailVerdict.HOLD),
        ),
        context(),
    )
    assert merged.decision is MoveDecision.PARKED
    without_park = evaluate_rails(
        (rail("a.decline", RailVerdict.DECLINE), rail("c.hold", RailVerdict.HOLD)), context()
    )
    assert without_park.decision is MoveDecision.DECLINE


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
