"""zizmor-workflow-source — one workflow file, every finding on it, called out in the margin.

Spec: specs/spec-zizmor-v0.md (req-zizmor-panel-workflow-source).

The finding page shows one finding against its file. This panel is the inverse: the file, with all
of its findings. The whole collected body (github_core's `configuration.raw_yaml`) is set as numbered
source; each finding's span is marked in the tone of its severity, and a call-out sits in the right
margin level with the span's first line — numbered the way a sidenote is, naming the audit and
zizmor's summary, and linking to that finding's page. Findings that start on the same line share one
call-out block; a call-out reserves the rows down to the next one so blocks never overlap, which
means a dense stretch of findings spreads the source a little rather than hiding a note behind
another. That is the trade Tufte makes too: the margin is part of the reading, not decoration.

Three states, never two. The workflow's latest SCANNED_WORKFLOW outcome frames the page:
`evaluated` with findings (annotated), `evaluated` with none ("zizmor read this file and found
nothing"), and not evaluated (`no-yaml`, `parse-failed`: findings UNKNOWN, with the recorded reason —
never an empty file that reads as clean). A body github_core never captured says so as well.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from tap_plugin.github_core.models.github_workflow import GithubWorkflow
from tap_plugin.zizmor.models.finding import ZizmorFinding
from tap_plugin.zizmor.models.run import ZizmorRun
from tap_plugin.zizmor.panels._workflow import (
    line_of,
    severity_rank,
    severity_tone,
    workflow_body_lines,
    workflow_page_url,
)

from tap_grid.models import Edge

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)

DEFAULT_WORKFLOW_VAR = "workflow_id"
EDGE_FLAGS_WORKFLOW = "FLAGS_WORKFLOW__zizmor"
EDGE_SCANNED_WORKFLOW = "SCANNED_WORKFLOW__zizmor"
FINDING_PAGE = "/zizmor/finding?finding_id={finding_id}&workflow_id={workflow_id}"


class ZizmorWorkflowSourcePanelType:
    slug: ClassVar[str] = "zizmor-workflow-source"
    label: ClassVar[str] = "zizmor Workflow Source"
    view: ClassVar[str] = "zizmor/panels/workflow_source.html"
    css: ClassVar[list[str]] = ["zizmor/css/panels.css"]
    js: ClassVar[list[str]] = []
    editor_view: ClassVar[str] = ""
    config_defaults: ClassVar[dict[str, Any]] = {}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        var = (getattr(panel, "config", None) or {}).get("workflow_id_var") or DEFAULT_WORKFLOW_VAR
        requested = (request.GET.get(var) or "").strip() if request else ""
        if not requested:
            return {"state": "no_selection", "requested": "", "workflow": None}
        try:
            workflow_id = int(requested)
        except ValueError:
            # A URL parameter is user input; a mistyped id is a not-found page, not a 500.
            return {"state": "not_found", "requested": requested, "workflow": None}
        workflow = GithubWorkflow.objects.filter(workflow_id=workflow_id).order_by("full_name").first()
        if workflow is None:
            return {"state": "not_found", "requested": requested, "workflow": None}

        findings = cls._findings(workflow)
        scan = cls._scan(workflow)
        lines = workflow_body_lines(workflow)
        annotated = annotate(lines, findings, workflow_id=workflow.workflow_id)
        return {
            "state": "found",
            "requested": requested,
            "workflow": workflow,
            "scan": scan,
            "findings": findings,
            "finding_count": len(findings),
            "loud_count": sum(1 for f in findings if f.severity in ("High", "Medium")),
            "has_body": bool(lines),
            "rows": annotated["rows"],
            "callouts": annotated["callouts"],
            "beyond": annotated["beyond"],
            "workflow_url": workflow_page_url(panel, workflow),
        }

    @staticmethod
    def _findings(workflow: GithubWorkflow) -> list[ZizmorFinding]:
        ids = Edge.objects.filter(to_entity_id=workflow.entity_id, edge_type=EDGE_FLAGS_WORKFLOW).values_list(
            "from_entity_id", flat=True
        )
        rows = list(ZizmorFinding.objects.filter(entity_id__in=list(ids)))
        # By position in the file, loudest first within a line — the order the margin reads in.
        rows.sort(key=lambda f: (line_of((f.location or {}).get("row")), severity_rank(f.severity), f.audit_id))
        return rows

    @staticmethod
    def _scan(workflow: GithubWorkflow) -> dict[str, Any]:
        """The latest run's verdict on this file: evaluated, or the recorded reason it was not.

        `outcome` is None when no run has ever considered this workflow — a fourth state the
        template names separately from "not evaluated".
        """
        edges = list(Edge.objects.filter(to_entity_id=workflow.entity_id, edge_type=EDGE_SCANNED_WORKFLOW))
        if not edges:
            return {"outcome": None, "reason": "", "run": None}
        runs = {r.entity_id: r for r in ZizmorRun.objects.filter(entity_id__in=[e.from_entity_id for e in edges])}
        edges.sort(
            key=lambda e: (
                getattr(runs.get(e.from_entity_id), "started_at", None) is not None,
                getattr(runs.get(e.from_entity_id), "started_at", None) or "",
            ),
        )
        latest = edges[-1]
        props = latest.properties or {}
        return {
            "outcome": props.get("outcome") or "",
            "reason": props.get("reason") or "",
            "run": runs.get(latest.from_entity_id),
        }


def annotate(lines: list[str], findings: list[ZizmorFinding], workflow_id: int | str = "") -> dict[str, Any]:
    """Lay the findings over the lines: marked spans, and one margin call-out per starting line.

    Returns `rows` (one per source line: number, text, tone of the loudest finding covering it, and
    the call-out anchored there if any) and `callouts` (the same blocks in reading order, for the
    fallback list when there is no body to hang them on). Each call-out carries `grid_start` and
    `grid_end`: the margin rows it may occupy — from its line down to the line before the next
    call-out — so two notes never overlap.
    """
    n_lines = len(lines)
    tone_by_line: dict[int, str] = {}
    by_start: dict[int, list[dict[str, Any]]] = {}
    number = 0
    for f in findings:
        loc = f.location or {}
        start = line_of(loc.get("row")) or 1
        end = line_of(loc.get("end_row")) or start
        number += 1
        item = {
            "n": number,
            "finding_id": str(f.entity_id),
            "audit_id": f.audit_id,
            "severity": f.severity,
            "tone": severity_tone(f.severity),
            "summary": f.summary or f.audit_id,
            "job_key": loc.get("job_key") or "",
            "span": f"{start}–{end}" if end != start else str(start),
            "url": FINDING_PAGE.format(finding_id=f.entity_id, workflow_id=workflow_id),
        }
        by_start.setdefault(start, []).append(item)
        for i in range(start, end + 1):
            cur = tone_by_line.get(i)
            if cur is None or severity_rank_of_tone(item["tone"]) < severity_rank_of_tone(cur):
                tone_by_line[i] = item["tone"]

    starts = sorted(by_start)
    callouts: list[dict[str, Any]] = []
    for idx, start in enumerate(starts):
        nxt = starts[idx + 1] if idx + 1 < len(starts) else (n_lines + 1 if n_lines else start + 1)
        items = by_start[start]
        callouts.append(
            {
                "line": start,
                "grid_start": start,
                "grid_end": max(nxt, start + 1),
                "items": items,
                "tone": min((i["tone"] for i in items), key=severity_rank_of_tone),
                "numbers": [i["n"] for i in items],
            }
        )
    callout_at = {c["line"]: c for c in callouts}
    rows = [
        {"n": i, "text": text, "tone": tone_by_line.get(i, ""), "callout": callout_at.get(i)}
        for i, text in enumerate(lines, start=1)
    ]
    # A finding past the end of the collected body: the body and the scan disagree (the file changed
    # between collections). It has no row to hang on, so it is handed back separately and the
    # template lists it under the file — never dropped (req-zizmor-panel-workflow-source-1).
    beyond = [c for c in callouts if n_lines and c["line"] > n_lines]
    if beyond:
        logger.warning(
            "[9c4f] zizmor workflow-source: %s call-out(s) at line %s+ beyond a %s-line body",
            len(beyond),
            beyond[0]["line"],
            n_lines,
        )
    return {"rows": rows, "callouts": callouts, "beyond": beyond}


def severity_rank_of_tone(tone: str) -> int:
    return {"bad": 0, "warn": 1, "muted": 2}.get(tone, 3)
