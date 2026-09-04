from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aeos_kernel import (
    AuthorityLevel,
    AuthorityRecord,
    DecisionStatus,
    ResolvedCandidate,
    ScopeSelector,
    resolve_authority,
    resolve_unique,
    stable_fingerprint,
)

SOURCE_ROOT = Path(
    os.environ.get("AEOS_MULTIAGENT_SOURCE_ROOT", "/home/john/code/MultiAgentCommunication")
)
PINNED_HEAD = "1b71c35c9f1150930618ef56c8bbdf94ff0caf11"
PINNED_FILES = (
    "claude_coord/wlg/decision_engine/contracts.py",
    "claude_coord/wlg/decision_engine/authority.py",
    "claude_coord/wlg/decision_engine/candidate_resolvers.py",
    "claude_coord/wlg/decision_engine/canon_decision.py",
    "claude_coord/wlg/pipeline/decision_planner.py",
    "claude_coord/wlg/fix/repair_mutation_plan.py",
    "claude_coord/tests/test_canon_decision.py",
    "claude_coord/tests/test_canon_decision_pipeline.py",
    "claude_coord/tests/test_intent_authority_lift_canon_decision.py",
)

pytestmark = pytest.mark.compatibility


def require_pinned_source() -> None:
    if not SOURCE_ROOT.is_dir():
        pytest.skip("the MultiAgentCommunication source checkout is unavailable")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=SOURCE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == PINNED_HEAD
    dirty = subprocess.run(
        ["git", "diff", "--quiet", "--", *PINNED_FILES], cwd=SOURCE_ROOT, check=False
    )
    assert dirty.returncode == 0, "pinned decision source files have uncommitted changes"
    source_path = str(SOURCE_ROOT)
    if source_path not in sys.path:
        sys.path.insert(0, source_path)


def test_source_enum_and_fingerprint_values_are_preserved() -> None:
    require_pinned_source()
    from claude_coord.wlg.decision_engine.contracts import (
        AuthorityLevel as SourceAuthorityLevel,
    )
    from claude_coord.wlg.decision_engine.contracts import (
        DecisionStatus as SourceDecisionStatus,
    )
    from claude_coord.wlg.decision_engine.contracts import (
        stable_fingerprint as source_fingerprint,
    )

    assert {item.value for item in AuthorityLevel} == {item.value for item in SourceAuthorityLevel}
    assert {item.value for item in DecisionStatus} == {item.value for item in SourceDecisionStatus}
    fixture = {"project": "any", "nested": [1, {"decision": "bounded"}]}
    assert stable_fingerprint(fixture) == source_fingerprint(fixture)


def test_source_candidate_resolution_known_answers_are_preserved() -> None:
    require_pinned_source()
    from claude_coord.wlg.decision_engine.candidate_resolvers import (
        ResolvedCandidate as SourceCandidate,
    )
    from claude_coord.wlg.decision_engine.candidate_resolvers import (
        resolve_unique as source_resolve,
    )

    fixtures = (
        (("one", "existing_edge", "care"), ("two", "same_domain_structural", "care")),
        (("one", "same_domain_structural", "care"), ("two", "same_domain_structural", "care")),
        (("one", "same_domain_structural", "care"), ("two", "same_domain_structural", "practice")),
        (("screen", "existing_edge", "care"),),
        (("one", "name_similarity", "care"),),
    )
    for fixture in fixtures:
        source = source_resolve(
            SourceCandidate(candidate_id, "Screen", evidence, domain)
            for candidate_id, evidence, domain in fixture
        )
        aeos = resolve_unique(
            ResolvedCandidate(candidate_id, "Screen", evidence, domain)
            for candidate_id, evidence, domain in fixture
        )
        assert aeos.status == source.status
        assert aeos.reason == source.reason
        assert (aeos.candidate.id if aeos.candidate else None) == (
            source.candidate.id if source.candidate else None
        )


def test_source_wlg_authority_selector_known_answer_is_preserved() -> None:
    require_pinned_source()
    from claude_coord.wlg.decision_engine.authority import (
        ScopeSelector as SourceScopeSelector,
    )
    from claude_coord.wlg.decision_engine.authority import selector_matches as source_matches

    fixtures = (
        (
            "path_pattern_method",
            {"domain": "care", "method": "GET", "path_glob": "/articles/*"},
            {"domain": "care", "method": "GET", "path": "/articles/one"},
        ),
        (
            "field_name_canonical",
            {"domain": "care", "kind": "Article", "field_name": "slug"},
            {"domain": "care", "kind": "Article", "field_name": "slug"},
        ),
        (
            "lifecycle_namespace",
            {"domain": "care", "state_machine_body": "draft -> approved"},
            {"domain": "care", "state_machine_body": "draft -> approved"},
        ),
        ("rule_scope", {"rule_id": "*", "domain": "care"}, {"rule_id": "one", "domain": "care"}),
    )
    for selector_type, selector_args, scope in fixtures:
        assert ScopeSelector(selector_type, selector_args).selector_type == selector_type
        assert source_matches(SourceScopeSelector(selector_type, selector_args), scope)
        from aeos_kernel import selector_matches

        assert selector_matches(ScopeSelector(selector_type, selector_args), scope)


def test_source_wlg_authority_precedence_and_conflict_known_answers_are_preserved() -> None:
    require_pinned_source()
    from claude_coord.wlg.decision_engine.authority import (
        AuthorityRecord as SourceAuthorityRecord,
    )
    from claude_coord.wlg.decision_engine.authority import ScopeSelector as SourceScopeSelector
    from claude_coord.wlg.decision_engine.authority import resolve_authority as source_resolve

    source_records = (
        SourceAuthorityRecord(
            "requirement",
            "P1",
            "WLGRequirement",
            "confirmed_authority",
            SourceScopeSelector("shape_id", {"shape_id": "u1"}),
            {"owner": "requirement"},
            "spec:req",
        ),
        SourceAuthorityRecord(
            "decision",
            "P1",
            "DesignDecision",
            "confirmed_authority",
            SourceScopeSelector("shape_id", {"shape_id": "u1"}),
            {"owner": "decision"},
            "decision:1",
        ),
    )
    aeos_records = tuple(
        AuthorityRecord(
            authority_id=item.authority_id,
            vertical_id="multiagent",
            tenant_id=item.project_id,
            layer=item.layer,
            status=item.status,
            selector=ScopeSelector(item.selector.selector_type, item.selector.selector_args),
            value=item.value,
            source_anchor=item.source_anchor,
            version=item.version,
            priority=item.priority,
        )
        for item in source_records
    )
    scope = {"shape_id": "u1"}
    source = source_resolve(source_records, scope=scope)
    aeos = resolve_authority(
        aeos_records,
        vertical_id="multiagent",
        tenant_id="P1",
        scope=scope,
        at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert source.status == aeos.status.value == "authorized"
    assert (
        [item.authority_id for item in source.selected]
        == [item.authority_id for item in aeos.selected]
        == ["decision"]
    )

    source_conflict = (
        *source_records,
        SourceAuthorityRecord(
            "decision-conflict",
            "P1",
            "DesignDecision",
            "confirmed_authority",
            SourceScopeSelector("shape_id", {"shape_id": "u1"}),
            {"owner": "someone-else"},
            "decision:2",
        ),
    )
    aeos_conflict = (
        *aeos_records,
        AuthorityRecord(
            authority_id="decision-conflict",
            vertical_id="multiagent",
            tenant_id="P1",
            layer="DesignDecision",
            status="confirmed_authority",
            selector=ScopeSelector("shape_id", {"shape_id": "u1"}),
            value={"owner": "someone-else"},
            source_anchor="decision:2",
        ),
    )
    assert source_resolve(source_conflict, scope=scope).status == "decision_conflict"
    assert (
        resolve_authority(
            aeos_conflict,
            vertical_id="multiagent",
            tenant_id="P1",
            scope=scope,
            at=datetime(2026, 9, 2, tzinfo=UTC),
        ).status.value
        == "authority_conflict"
    )


def test_source_pin_is_a_current_commit_not_a_date_label() -> None:
    require_pinned_source()
    result = subprocess.run(
        ["git", "show", "-s", "--format=%cI", PINNED_HEAD],
        cwd=SOURCE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert datetime.fromisoformat(result.stdout.strip()).astimezone(UTC).tzinfo is not None
