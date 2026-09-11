"""The finding page — one finding, and everything the grid knows about it.

req-zizmor-page-finding, req-zizmor-panel-finding-detail.

Most of what is asserted here is about **absence**. A finding page is where a reader decides whether
to act, and the difference between "this finding is about the whole workflow" and "we could not work
out which job it is in" changes that decision. Both render as no job. Only one of them is true of
any given finding, and the panel has to say which.

The joins are the other half. A lint result becomes a risk statement when you can see what the job
it sits in is permitted to do — context zizmor cannot have, because it reads one file.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.utils import timezone
from tap_plugin.zizmor.models.finding import ZizmorFinding
from tap_plugin.zizmor.panels.finding_detail import ZizmorFindingDetailPanelType as Panel

from tap_grid.models import Edge, Entity
from tap_grid.services import create_node

EDGE_PRODUCED = "PRODUCED_FINDING__zizmor"
EDGE_FLAGS_WORKFLOW = "FLAGS_WORKFLOW__zizmor"
EDGE_FLAGS_JOB = "FLAGS_JOB__zizmor"
EDGE_FLAGS_ACTION = "FLAGS_ACTION__zizmor"


class _Req:
    def __init__(self, **params: str) -> None:
        self.GET = params


class _P:
    config: dict[str, Any] = {}


def _edge(edge_type: str, src: uuid.UUID, dst: uuid.UUID, props: dict[str, Any] | None = None) -> None:
    Edge.objects.create(
        entity=Entity.objects.create(id=uuid.uuid7(), entity_type="edge", name=edge_type, dimensions={}),
        from_entity_id=src,
        to_entity_id=dst,
        edge_type=edge_type,
        properties=props or {},
    )


def _finding(**overrides: Any) -> ZizmorFinding:
    fields: dict[str, Any] = {
        "audit_id": "template-injection",
        "audit_url": "https://docs.zizmor.sh/audits/#template-injection",
        "severity": "High",
        "confidence": "High",
        "persona": "Regular",
        "scanner_version": "1.30.0",
        "summary": "code injection via template expansion",
        "location": {
            "path": ".github/workflows/ci.yml",
            "route": "jobs/build/steps/2/run",
            "job_key": "build",
            "step_index": 2,
            "row": 6,
            "column": 8,
            "subfeature": "matrix.image",
            "annotation": "may expand into attacker-controllable code",
        },
        "fixes": [],
        "raw": {"ident": "template-injection"},
        "tags": {},
        "observed_at": timezone.now().isoformat(),
        "known_since": timezone.now().isoformat(),
    }
    fields.update(overrides)
    r = create_node("zizmor__finding", fields)
    assert r.success, r.errors
    return ZizmorFinding.objects.get(entity_id=r.entity_id)


def _workflow(path: str = ".github/workflows/ci.yml", workflow_id: int = 42) -> uuid.UUID:
    r = create_node(
        "github_core__github_workflow",
        {
            "name": "ci",
            "full_name": "acme/repo",
            "workflow_id": workflow_id,
            "path": path,
            "state": "active",
            "configuration": {},
        },
    )
    assert r.success, r.errors
    return r.entity_id


def _job(job_key: str = "build", **extra: Any) -> uuid.UUID:
    fields = {"name": job_key, "full_name": "acme/repo", "workflow_id": 42, "job_key": job_key}
    fields.update(extra)
    r = create_node("github_core__workflow_job", fields)
    assert r.success, r.errors
    return r.entity_id


def _ctx(finding: ZizmorFinding) -> dict[str, Any]:
    return Panel.get_view_context(_P(), _Req(finding_id=str(finding.entity_id)))


# ---------------------------------------------------------------------------
# Resolution states.
# ---------------------------------------------------------------------------


def test_an_unknown_id_says_so_rather_than_rendering_an_empty_finding(db: None) -> None:
    ctx = Panel.get_view_context(_P(), _Req(finding_id=str(uuid.uuid7())))

    assert ctx["state"] == "not_found"
    assert ctx["finding"] is None


def test_a_malformed_id_is_handled_like_an_unknown_one(db: None) -> None:
    """A bad id in a URL must not 500 the page."""
    ctx = Panel.get_view_context(_P(), _Req(finding_id="not-a-uuid"))

    assert ctx["state"] == "not_found"


def test_no_id_at_all_invites_a_selection(db: None) -> None:
    ctx = Panel.get_view_context(_P(), _Req())

    assert ctx["state"] == "no_selection"


# ---------------------------------------------------------------------------
# Absence — the assertions this page exists for.
# ---------------------------------------------------------------------------


def test_a_workflow_level_finding_is_distinguishable_from_an_unresolved_job(db: None) -> None:
    """Both render as "no job". Only one means the finding has no job.

    A workflow-level finding legitimately names none; an unresolved one names a job the grid could
    not find. Rendering them the same way would tell a reader the wrong thing about both.
    """
    workflow_level = _finding(location={"path": ".github/workflows/ci.yml", "route": "", "job_key": None})
    unresolved = _finding(
        location={"path": ".github/workflows/ci.yml", "route": "jobs/ghost/steps/0", "job_key": "ghost"},
        tags={"job_unresolved": "no workflow_job for 'ghost' is on the grid for acme/repo"},
    )

    assert _ctx(workflow_level)["job"] is None
    assert _ctx(workflow_level)["job_unresolved"] == ""
    assert _ctx(unresolved)["job"] is None
    assert "ghost" in _ctx(unresolved)["job_unresolved"], "the recorded reason must survive to the page"


def test_a_reusable_workflow_reference_explains_itself(db: None) -> None:
    """It has no action node BY DESIGN. Showing nothing would read as a lookup failure."""
    finding = _finding(tags={"uses_reusable_workflow": "acme/repo/.github/workflows/ci.yml@main"})

    ctx = _ctx(finding)

    assert ctx["action"] is None
    assert ctx["reusable_workflow"] == "acme/repo/.github/workflows/ci.yml@main"


def test_a_finding_no_run_claims_says_so(db: None) -> None:
    """Provenance is not decoration: a finding no run produced is a finding with no source."""
    ctx = _ctx(_finding())

    assert ctx["run"] is None


# ---------------------------------------------------------------------------
# The joins — context zizmor cannot have.
# ---------------------------------------------------------------------------


def test_the_job_join_surfaces_what_that_job_is_permitted_to_do(db: None) -> None:
    """The same audit on a write-permissioned self-hosted job is a different problem."""
    finding = _finding()
    job = _job("build", permissions={"contents": "write"}, runs_on=["self-hosted"], environment="production")
    _edge(EDGE_FLAGS_JOB, finding.entity_id, job)

    ctx = _ctx(finding)

    assert ctx["job"] is not None
    assert ctx["job"].permissions == {"contents": "write"}
    assert ctx["job"].runs_on == ["self-hosted"]
    assert ctx["job"].environment == "production"


def test_the_action_join_keeps_the_pin_the_finding_reported_on(db: None) -> None:
    """The node is keyed with the ref stripped, so the pin has to come off the edge or it is lost."""
    finding = _finding(audit_id="unpinned-uses")
    r = create_node("github_core__github_action", {"name": "checkout", "action_path": "actions/checkout"})
    assert r.success, r.errors
    _edge(EDGE_FLAGS_ACTION, finding.entity_id, r.entity_id, {"uses": "actions/checkout@main"})

    ctx = _ctx(finding)

    assert ctx["action"]["action"].action_path == "actions/checkout"
    assert ctx["action"]["uses"] == "actions/checkout@main", "the ref is the thing to act on"


def test_the_workflow_join_prefers_the_grid_row_over_the_recorded_path(db: None) -> None:
    finding = _finding()
    wf = _workflow()
    _edge(EDGE_FLAGS_WORKFLOW, finding.entity_id, wf)

    ctx = _ctx(finding)

    assert ctx["workflow"] is not None
    assert ctx["workflow"].full_name == "acme/repo"


def test_the_producing_run_is_reachable_from_the_finding(db: None) -> None:
    finding = _finding()
    r = create_node(
        "zizmor__run",
        {
            "scanner_version": "1.30.0",
            "persona": "Auditor",
            "outcome": "ok",
            "audit_set": ["template-injection"],
            "source_collection_job": str(uuid.uuid7()),
            "started_at": timezone.now().isoformat(),
            "finished_at": timezone.now().isoformat(),
            "workflows_evaluated": 1,
        },
    )
    assert r.success, r.errors
    _edge(EDGE_PRODUCED, r.entity_id, finding.entity_id)

    assert _ctx(finding)["run"].scanner_version == "1.30.0"


# ---------------------------------------------------------------------------
# Presentation decisions that carry meaning.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "loud"), [("High", True), ("Medium", True), ("Low", False), ("Informational", False)]
)
def test_only_the_weighty_severities_are_rendered_loudly(db: None, severity: str, loud: bool) -> None:
    """If every finding shouts, none of them does."""
    assert _ctx(_finding(severity=severity))["is_loud"] is loud


def test_the_narrowed_expression_survives_to_the_page(db: None) -> None:
    """`matrix.image` is the finding; the whole run: block it sits in is not."""
    assert _ctx(_finding())["location"]["subfeature"] == "matrix.image"


def test_the_scanners_verbatim_assertion_is_carried_through(db: None) -> None:
    """Everything else on the page is our reading of it; this is what zizmor said."""
    raw = {"ident": "template-injection", "determinations": {"severity": "High"}}

    assert _ctx(_finding(raw=raw))["finding"].raw == raw


def test_section_config_splits_head_from_body(db: None) -> None:
    """req-zizmor-page-finding-3: the same panel type renders its head, its body, or both."""
    from tap_plugin.zizmor.panels.finding_detail import ZizmorFindingDetailPanelType

    class _Req:
        def __init__(self, **params: str) -> None:
            self.GET = params

    class _Panel:
        def __init__(self, **config: str) -> None:
            self.config = config

    fid = _finding().entity_id
    head = ZizmorFindingDetailPanelType.get_view_context(_Panel(section="head"), _Req(finding_id=str(fid)))
    body = ZizmorFindingDetailPanelType.get_view_context(_Panel(section="body"), _Req(finding_id=str(fid)))
    both = ZizmorFindingDetailPanelType.get_view_context(_Panel(), _Req(finding_id=str(fid)))
    assert (head["show_head"], head["show_body"]) == (True, False)
    assert (body["show_head"], body["show_body"]) == (False, True)
    assert (both["show_head"], both["show_body"]) == (True, True)
