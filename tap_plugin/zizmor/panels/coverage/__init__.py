"""zizmor-coverage — what the latest run actually read, and what it never did.

Spec: specs/spec-zizmor-v0.md (req-zizmor-panel-coverage).

This panel exists because a findings table cannot tell the truth on its own. A table of findings
renders a workflow nobody scanned exactly like a workflow that came back clean — and on a real
organisation that is not a rare edge case: *observed* 2026-09-10, **40 of 117 workflows carried no
`raw_yaml` at all**, so a third of the estate had never been read by this scanner while the page
would have shown a reassuring list of 155 findings.

The grid already records the distinction on `SCANNED_WORKFLOW__zizmor` — four outcomes, and a
mandatory reason for every one that is not `evaluated`. This reads them back.

It is a custom panel type rather than a standard table instance for one concrete reason: the
standard table renders NODE results, and its spec defers edge-centric result sets to a future
variant, while outcome and reason live on the edge. Filed as tap#418; when that lands, this
collapses into a standard table instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from tap_plugin.github_core.models.github_workflow import GithubWorkflow
from tap_plugin.zizmor.models.run import ZizmorRun

from tap_grid.models import Edge

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

SCANNED_WORKFLOW = "SCANNED_WORKFLOW__zizmor"

#: Rendering order and prose for each outcome. Ordered worst-understood first: `no-yaml` and
#: `parse-failed` are the states whose findings are UNKNOWN, and they are the ones a reader must not
#: mistake for clean.
OUTCOME_META: dict[str, dict[str, str]] = {
    "no-yaml": {
        "label": "No YAML collected",
        "meaning": "Collected, but no workflow body was captured — this scanner has never read these. Their findings are unknown, not zero.",
        "tone": "unknown",
    },
    "parse-failed": {
        "label": "Could not be parsed",
        "meaning": "The scanner read the file and could not understand it. Findings unknown, not zero.",
        "tone": "unknown",
    },
    "skipped": {
        "label": "Refused before scanning",
        "meaning": "The collector declined the row before scanning it — a path that failed sanitizing, or a cap.",
        "tone": "unknown",
    },
    "evaluated": {
        "label": "Scanned",
        "meaning": "The scanner read these and its findings for them are on the grid.",
        "tone": "observed",
    },
}


class ZizmorCoveragePanelType:
    slug: ClassVar[str] = "zizmor-coverage"
    label: ClassVar[str] = "zizmor Coverage"
    view: ClassVar[str] = "zizmor/panels/coverage.html"
    css: ClassVar[list[str]] = ["zizmor/css/panels.css"]
    js: ClassVar[list[str]] = []
    editor_view: ClassVar[str] = ""
    #: How many workflow names to list per non-evaluated outcome before summarising the remainder.
    #: A panel that printed 40 file paths would bury the number that matters.
    config_defaults: ClassVar[dict[str, Any]] = {"max_named": 8}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        run = ZizmorRun.objects.order_by("-started_at").first()
        if run is None:
            return {"run": None, "groups": [], "rows": [], "skipped": [], "total": 0, "unobserved_total": 0}

        max_named = int((panel.config or {}).get("max_named", 8))
        edges = list(Edge.objects.filter(from_entity_id=run.entity_id, edge_type=SCANNED_WORKFLOW))
        by_target = {e.to_entity_id: (e.properties or {}) for e in edges}
        names = dict(GithubWorkflow.objects.filter(entity_id__in=list(by_target)).values_list("entity_id", "full_name"))
        paths = dict(GithubWorkflow.objects.filter(entity_id__in=list(by_target)).values_list("entity_id", "path"))

        buckets: dict[str, list[dict[str, str]]] = {key: [] for key in OUTCOME_META}
        for target, props in by_target.items():
            outcome = str(props.get("outcome") or "")
            buckets.setdefault(outcome, []).append(
                {
                    "workflow": f"{names.get(target, '?')} / {paths.get(target, '?')}",
                    "reason": str(props.get("reason") or ""),
                }
            )

        # One flat row per workflow — the grouped lists could only ever show the first
        # `max_named` of each bucket and then said "and 32 more", which is the shape of a
        # summary pretending to be an inventory. A table shows all of them.
        rows = []
        shared: dict[str, str] = {}
        for key, meta in OUTCOME_META.items():
            bucket = sorted(buckets.get(key, []), key=lambda x: x["workflow"])
            # A reason identical on every row of a bucket is a property of the OUTCOME, not of the
            # workflow. Printed per row it filled the widest column with the same sentence forty
            # times and said nothing; hoisted to the group it is said once and read once.
            distinct = {r["reason"] for r in bucket if r["reason"]}
            if len(distinct) == 1 and len(bucket) > 1:
                shared[key] = distinct.pop()
            for r in bucket:
                reason = "" if key in shared else r["reason"]
                rows.append({**r, "reason": reason, "outcome": key, "label": meta["label"], "tone": meta["tone"]})

        groups = []
        for key, meta in OUTCOME_META.items():
            bucket_rows = sorted(buckets.get(key, []), key=lambda r: r["workflow"])
            if not bucket_rows:
                continue
            groups.append(
                {
                    "outcome": key,
                    "count": len(bucket_rows),
                    "shared_reason": shared.get(key, ""),
                    "named": bucket_rows[:max_named] if key != "evaluated" else [],
                    "remainder": max(0, len(bucket_rows) - max_named) if key != "evaluated" else 0,
                    **meta,
                }
            )

        # The audits that could not run. Moved here from the about panel: an audit that could not
        # run and a workflow that was never read are the same claim — findings unknown, not zero —
        # and they belong in one place. `tags.skipped_audit_reasons` carries the binary's own words;
        # fall back to the bare list when an older run predates the tag.
        reasons: dict[str, str] = (run.tags or {}).get("skipped_audit_reasons") or {}
        skipped = [
            {"audit_id": a, "reason": reasons.get(a, "not available offline")} for a in sorted(run.skipped_audits or [])
        ]

        total = len(by_target)
        unobserved = total - len(buckets.get("evaluated", []))
        return {
            "run": run,
            "groups": groups,
            "rows": rows,
            "skipped": skipped,
            "total": total,
            "unobserved_total": unobserved,
            # The workflows on the grid that this run has no edge to at all. Distinct from every
            # outcome above: not "scanned and X", but never considered by this run.
            "unreached": GithubWorkflow.objects.exclude(entity_id__in=list(by_target)).count(),
        }
