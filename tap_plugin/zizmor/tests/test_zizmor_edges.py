"""Behavioural tests for the five edges that put a finding and a run ON the grid.

req-zizmor-finding (FLAGS_WORKFLOW / FLAGS_JOB / FLAGS_ACTION) and req-zizmor-run
(PRODUCED_FINDING / SCANNED_WORKFLOW). Service-layer setup throughout; the ORM is reached
only to read a projection back.

The two edges that carry properties are the two whose bare form would be a lie:
`SCANNED_WORKFLOW` without a reason turns a coverage gap into a clean result, and
`FLAGS_ACTION` without the `uses:` string loses the very pin the finding was reporting on.
Both refusals are asserted here rather than left to the collector's good manners.
"""

from __future__ import annotations

import pytest
from django.utils import timezone
from tap_plugin.zizmor.models import ZizmorFinding, ZizmorRun

from tap_grid.exceptions import EdgePropertyValidationError
from tap_grid.models import Entity
from tap_grid.registry import get_model_class
from tap_grid.services import create_edge, create_node

PRODUCED_FINDING = "PRODUCED_FINDING__zizmor"
SCANNED_WORKFLOW = "SCANNED_WORKFLOW__zizmor"
FLAGS_WORKFLOW = "FLAGS_WORKFLOW__zizmor"
FLAGS_JOB = "FLAGS_JOB__zizmor"
FLAGS_ACTION = "FLAGS_ACTION__zizmor"

EXPECTED_DIMENSIONS = {
    "github.platform": "github.com",
    "github.surface": "actions",
    "github.observation": "declaration",
}


def _create(type_slug: str, payload: dict):
    result = create_node(type_slug, payload)
    assert result.success, f"create_node({type_slug}) failed: {result.errors}"
    entity = Entity.objects.get(pk=result.entity_id)
    return get_model_class(type_slug).objects.get(entity=entity)


def _run() -> ZizmorRun:
    return _create(
        "zizmor__run",
        {
            "scanner_version": "1.30.0",
            "persona": "Auditor",
            "started_at": timezone.now().isoformat(),
        },
    )


def _finding() -> ZizmorFinding:
    return _create(
        "zizmor__finding",
        {
            "audit_id": "unpinned-uses",
            "severity": "Medium",
            "confidence": "High",
            "scanner_version": "1.30.0",
            "location": {"path": ".github/workflows/ci.yml", "route": "jobs/build/steps/0"},
        },
    )


def _workflow():
    return _create(
        "github_core__github_workflow",
        {"full_name": "unified-systems-com/zizmor-tap", "path": ".github/workflows/ci.yml"},
    )


def _job():
    return _create(
        "github_core__workflow_job",
        {"full_name": "unified-systems-com/zizmor-tap", "job_key": "build"},
    )


def _action():
    return _create("github_core__github_action", {"action_path": "actions/checkout"})


@pytest.mark.django_db
class TestPropertyFreeEdges:
    """PRODUCED_FINDING, FLAGS_WORKFLOW and FLAGS_JOB assert a relationship and nothing else."""

    def test_a_run_produced_its_finding(self) -> None:
        edge = create_edge(_run().entity, _finding().entity, PRODUCED_FINDING)
        assert edge.edge_type == PRODUCED_FINDING

    def test_a_finding_flags_its_workflow(self) -> None:
        edge = create_edge(_finding().entity, _workflow().entity, FLAGS_WORKFLOW)
        assert edge.edge_type == FLAGS_WORKFLOW

    def test_a_finding_flags_a_resolved_job(self) -> None:
        edge = create_edge(_finding().entity, _job().entity, FLAGS_JOB)
        assert edge.edge_type == FLAGS_JOB

    def test_default_dimensions_are_applied_when_the_caller_names_none(self) -> None:
        edge = create_edge(_finding().entity, _workflow().entity, FLAGS_WORKFLOW)
        for key, value in EXPECTED_DIMENSIONS.items():
            assert edge.entity.dimensions.get(key) == value


@pytest.mark.django_db
class TestScannedWorkflowOutcome:
    """Coverage is the property that stops silence from rendering as safety."""

    def test_an_evaluated_workflow_needs_no_reason(self) -> None:
        edge = create_edge(_run().entity, _workflow().entity, SCANNED_WORKFLOW, {"outcome": "evaluated"})
        assert edge.properties["outcome"] == "evaluated"

    def test_an_outcome_is_required(self) -> None:
        with pytest.raises(EdgePropertyValidationError):
            create_edge(_run().entity, _workflow().entity, SCANNED_WORKFLOW, {})

    def test_an_outcome_outside_the_enum_is_refused(self) -> None:
        with pytest.raises(EdgePropertyValidationError):
            create_edge(_run().entity, _workflow().entity, SCANNED_WORKFLOW, {"outcome": "clean"})

    @pytest.mark.parametrize("outcome", ["parse-failed", "skipped", "no-yaml"])
    def test_a_non_evaluated_outcome_must_say_why(self, outcome: str) -> None:
        """An unexplained non-result is the shape that lets a coverage gap read as clean."""
        with pytest.raises(EdgePropertyValidationError):
            create_edge(_run().entity, _workflow().entity, SCANNED_WORKFLOW, {"outcome": outcome})

    @pytest.mark.parametrize(
        ("outcome", "reason"),
        [
            ("parse-failed", "while parsing a block mapping, did not find expected key at line 12"),
            ("skipped", "workflow path escapes its repository scratch directory"),
            ("no-yaml", "github_core collected this workflow but captured no raw_yaml for it"),
        ],
    )
    def test_a_non_evaluated_outcome_with_a_reason_is_accepted(self, outcome: str, reason: str) -> None:
        edge = create_edge(_run().entity, _workflow().entity, SCANNED_WORKFLOW, {"outcome": outcome, "reason": reason})
        assert edge.properties["reason"] == reason

    def test_no_yaml_is_a_first_class_outcome(self) -> None:
        """40 of 117 workflows on a real org collection had no raw_yaml (observed 2026-09-10).
        That is not `skipped` and it is emphatically not clean, so it is its own value."""
        edge = create_edge(
            _run().entity,
            _workflow().entity,
            SCANNED_WORKFLOW,
            {"outcome": "no-yaml", "reason": "no raw_yaml captured"},
        )
        assert edge.properties["outcome"] == "no-yaml"

    def test_an_unknown_property_is_refused(self) -> None:
        with pytest.raises(EdgePropertyValidationError):
            create_edge(
                _run().entity,
                _workflow().entity,
                SCANNED_WORKFLOW,
                {"outcome": "evaluated", "finding_count": 3},
            )


@pytest.mark.django_db
class TestFlagsAction:
    """The action node is keyed with the ref STRIPPED, so the pin has to live on the edge."""

    def test_the_uses_string_rides_the_edge(self) -> None:
        edge = create_edge(_finding().entity, _action().entity, FLAGS_ACTION, {"uses": "actions/checkout@v4"})
        assert edge.properties["uses"] == "actions/checkout@v4"

    def test_a_bare_edge_is_refused(self) -> None:
        """Without the reference, a finding about an unpinned `uses:` cannot say which one."""
        with pytest.raises(EdgePropertyValidationError):
            create_edge(_finding().entity, _action().entity, FLAGS_ACTION, {})

    def test_the_pin_vocabulary_is_not_duplicated_here(self) -> None:
        """`pin_kind` / `is_pinned` / `resolved_sha` are github_core's USES_ACTION facts. Writing
        them here would be the same fact derived twice, so the schema refuses them."""
        with pytest.raises(EdgePropertyValidationError):
            create_edge(
                _finding().entity,
                _action().entity,
                FLAGS_ACTION,
                {"uses": "actions/checkout@v4", "pin_kind": "unresolved"},
            )
