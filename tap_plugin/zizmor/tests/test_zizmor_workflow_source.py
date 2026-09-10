"""The annotated workflow source (req-zizmor-panel-workflow-source): every finding marked and called
out, notes that never overlap, and a scan that could not read the file rendered as unknown — never as
clean. Seeds go through the service layer inside the test transaction; function-scoped on purpose
(tap/pytest_harness binds the caller context per test)."""

from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone
from tap_plugin.zizmor.models.run import ZizmorRun
from tap_plugin.zizmor.panels.workflow_source import ZizmorWorkflowSourcePanelType, annotate

from tap_grid.models import Edge, Entity
from tap_grid.services import create_node

FLAGS = "FLAGS_WORKFLOW__zizmor"
SCANNED = "SCANNED_WORKFLOW__zizmor"
BODY = "\n".join(f"line {i}: on: [push]" if i == 1 else f"line {i}" for i in range(1, 21))


class _Req:
    def __init__(self, **params: str) -> None:
        self.GET = params


class _Panel:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}


def _workflow(workflow_id: int, body: str | None = BODY) -> uuid.UUID:
    result = create_node(
        "github_core__github_workflow",
        {
            "name": "ci",
            "full_name": "acme/repo",
            "workflow_id": workflow_id,
            "path": ".github/workflows/ci.yml",
            "state": "active",
            "configuration": {"raw_yaml": body} if body else {},
        },
    )
    assert result.success, result.errors
    return result.entity_id


def _run() -> ZizmorRun:
    result = create_node(
        "zizmor__run",
        {
            "scanner_version": "1.30.0",
            "persona": "Auditor",
            "audit_set": ["template-injection"],
            "skipped_audits": [],
            "outcome": "ok",
            "source_collection_job": str(uuid.uuid7()),
            "started_at": timezone.now().isoformat(),
            "finished_at": timezone.now().isoformat(),
            "workflows_evaluated": 1,
            "tags": {},
        },
    )
    assert result.success, result.errors
    return ZizmorRun.objects.get(entity_id=result.entity_id)


def _edge(edge_type: str, src: uuid.UUID, dst: uuid.UUID, props: dict[str, Any] | None = None) -> None:
    Edge.objects.create(
        entity=Entity.objects.create(id=uuid.uuid7(), entity_type="edge", name=edge_type, dimensions={}),
        from_entity_id=src,
        to_entity_id=dst,
        edge_type=edge_type,
        properties=props or {},
    )


def _finding(
    workflow: uuid.UUID, run: ZizmorRun, audit: str, severity: str, row: int, end: int | None = None
) -> uuid.UUID:
    result = create_node(
        "zizmor__finding",
        {
            "audit_id": audit,
            "audit_url": f"https://docs.zizmor.sh/audits/#{audit}",
            "severity": severity,
            "confidence": "High",
            "persona": "Regular",
            "scanner_version": "1.30.0",
            "summary": f"{audit} summary",
            "location": {
                "path": ".github/workflows/ci.yml",
                "row": row,
                "end_row": end or row,
                "route": "jobs/x",
                "job_key": "x",
            },
            "fixes": [],
            "raw": {},
            "tags": {},
        },
    )
    assert result.success, result.errors
    _edge(FLAGS, result.entity_id, workflow)
    _edge("PRODUCED_FINDING__zizmor", run.entity_id, result.entity_id)
    return result.entity_id


def _ctx(workflow_id: int | str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    return ZizmorWorkflowSourcePanelType.get_view_context(_Panel(config), _Req(workflow_id=str(workflow_id)))


def test_every_finding_is_marked_and_called_out_with_a_link_to_itself(db: None) -> None:
    wf, run = _workflow(101), _run()
    _edge(SCANNED, run.entity_id, wf, {"outcome": "evaluated"})
    a = _finding(wf, run, "template-injection", "High", 3, 5)
    b = _finding(wf, run, "excessive-permissions", "Medium", 3)
    c = _finding(wf, run, "unpinned-uses", "Low", 12)
    ctx = _ctx(101)
    assert ctx["state"] == "found" and ctx["scan"]["outcome"] == "evaluated"
    assert ctx["finding_count"] == 3 and ctx["loud_count"] == 2
    rows = ctx["rows"]
    assert len(rows) == 20
    assert [r["tone"] for r in rows[2:5]] == ["bad", "bad", "bad"]  # the High span wins lines 3-5
    assert rows[11]["tone"] == "muted" and rows[0]["tone"] == ""
    links = {it["url"] for c_ in ctx["callouts"] for it in c_["items"]}
    assert links == {f"/zizmor/finding?finding_id={x}" for x in (a, b, c)}
    # findings starting on one line share one block; numbering is continuous across blocks
    assert [c_["line"] for c_ in ctx["callouts"]] == [3, 12]
    assert [it["n"] for c_ in ctx["callouts"] for it in c_["items"]] == [1, 2, 3]
    assert rows[2]["callout"] is ctx["callouts"][0] and rows[2]["callout"]["numbers"] == [1, 2]


def test_callout_blocks_reserve_disjoint_margin_rows() -> None:
    class F:
        def __init__(self, row: int, end: int, sev: str, audit: str) -> None:
            self.entity_id, self.audit_id, self.severity, self.summary = uuid.uuid7(), audit, sev, ""
            self.location = {"row": row, "end_row": end}

    out = annotate(
        [f"l{i}" for i in range(1, 31)], [F(2, 2, "High", "a"), F(3, 3, "Low", "b"), F(20, 25, "Medium", "c")]
    )
    spans = [(c["grid_start"], c["grid_end"]) for c in out["callouts"]]
    assert spans == [(2, 3), (3, 20), (20, 31)]
    for (_s1, e1), (s2, _e2) in zip(spans, spans[1:], strict=False):
        assert e1 <= s2, "margin blocks overlap"


def test_not_read_renders_unknown_with_the_reason_never_clean(db: None) -> None:
    wf, run = _workflow(202, body=None), _run()
    _edge(SCANNED, run.entity_id, wf, {"outcome": "no-yaml", "reason": "github_core captured no raw_yaml"})
    ctx = _ctx(202)
    assert ctx["state"] == "found"
    assert ctx["scan"] == {"outcome": "no-yaml", "reason": "github_core captured no raw_yaml", "run": run}
    assert ctx["has_body"] is False and ctx["finding_count"] == 0


def test_never_scanned_is_its_own_state(db: None) -> None:
    _workflow(303)
    ctx = _ctx(303)
    assert ctx["scan"]["outcome"] is None and ctx["has_body"] is True and ctx["finding_count"] == 0


def test_findings_with_no_body_are_listed_not_hung_on_a_missing_file(db: None) -> None:
    wf, run = _workflow(404, body=None), _run()
    _edge(SCANNED, run.entity_id, wf, {"outcome": "evaluated"})
    _finding(wf, run, "dangerous-triggers", "High", 7)
    ctx = _ctx(404)
    assert ctx["has_body"] is False and ctx["rows"] == []
    assert [it["audit_id"] for c_ in ctx["callouts"] for it in c_["items"]] == ["dangerous-triggers"]


def test_bad_or_missing_id_is_a_state_not_a_500(db: None) -> None:
    assert _ctx("not-a-number")["state"] == "not_found"
    assert _ctx(999999)["state"] == "not_found"
    ctx = ZizmorWorkflowSourcePanelType.get_view_context(_Panel(), _Req())
    assert ctx["state"] == "no_selection"


def test_workflow_page_link_only_when_that_page_exists(db: None) -> None:
    wf = _workflow(505)
    _run()
    cfg = {"workflow_page_template": "/github_core/workflow?workflow_id={workflow_id}"}
    assert _ctx(505, cfg)["workflow_url"] == ""  # no such Page seeded in this transaction
    # Below the service layer on purpose: a Page's service create demands its USES_PANEL edges
    # (hotlink exact), and the rule under test is only "does a Page with this slug exist".
    from tap_web.models import Page

    Page.objects.bulk_create(  # bulk_create skips save() and therefore the hotlink check
        [
            Page(
                entity=Entity.objects.create(id=uuid.uuid7(), entity_type="page", name="wf", dimensions={}),
                slug="/github_core/workflow",
                name="wf",
                layout={"columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "x"}}}}},
            )
        ]
    )
    assert _ctx(505, cfg)["workflow_url"] == "/github_core/workflow?workflow_id=505"
    assert wf is not None
