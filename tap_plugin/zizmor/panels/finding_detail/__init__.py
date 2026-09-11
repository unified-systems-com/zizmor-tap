"""zizmor-finding-detail — one finding, and everything the grid knows about it.

Spec: specs/spec-zizmor-v0.md (req-zizmor-panel-finding-detail).

A finding on its own is a lint result. What makes it a *risk statement* is the context the grid
already holds and the scanner does not: which job the flagged line runs in, what that job is
permitted to do, what runner it lands on, and whether the action it references is pinned. zizmor
cannot see any of that — it reads one file — so this panel is where the join happens.

Three disciplines shape it.

**Absence is rendered, never blanked.** A finding whose job could not be resolved carries no
`FLAGS_JOB` edge and records why in `tags.job_unresolved`. Showing "Job: —" there would read as
"this finding has no job", which is a different and false claim. Every unresolved endpoint shows the
recorded reason instead.

**First seen and last seen are labelled apart.** `known_since` does not move when a later run
re-observes the same finding, so the gap between it and `observed_at` is how long the defect has
actually been there. Rendering one without the other invites reading a re-observation as a new
problem.

**The scanner's own words are kept verbatim.** `raw` is zizmor's json-v1 assertion exactly as it
was made. Everything else on this page is our interpretation of it, and a reader must be able to
get back to the original.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from tap_plugin.github_core.models.github_action import GithubAction
from tap_plugin.github_core.models.github_workflow import GithubWorkflow
from tap_plugin.github_core.models.workflow_job import WorkflowJob
from tap_plugin.zizmor.models.finding import ZizmorFinding
from tap_plugin.zizmor.models.run import ZizmorRun

from tap_grid.models import Edge

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

DEFAULT_FINDING_VAR = "finding_id"

from tap_plugin.zizmor.panels._workflow import (  # noqa: E402 — derived once for every zizmor panel
    file_page_url,
    line_of,
    workflow_body_lines,
    workflow_page_url,
)

EDGE_PRODUCED_FINDING = "PRODUCED_FINDING__zizmor"
EDGE_FLAGS_WORKFLOW = "FLAGS_WORKFLOW__zizmor"
EDGE_FLAGS_JOB = "FLAGS_JOB__zizmor"
EDGE_FLAGS_ACTION = "FLAGS_ACTION__zizmor"

#: Severities that deserve visual weight. Kept here rather than in the template so the template
#: stays dumb and the decision is reviewable in one place.
LOUD_SEVERITIES = frozenset({"High", "Medium"})


def _where(location: dict[str, Any], job_key: str) -> str:
    """One phrase for where the finding is, instead of three fields that each report an absence.

    A workflow-level finding has no job, an empty `route`, and a span starting at row 1 — the old
    page printed all three as separate rows ("Job: this is not about a job", "Route: (workflow
    level)", "Line: 1:0"), which is three ways of saying the same nothing. Say it once.
    """
    row = line_of(location.get("row"))
    end = line_of(location.get("end_row")) or row
    route = location.get("route") or ""
    if not job_key and not route:
        return f"the whole file, lines {row}\u2013{end}" if row and end and end != row else "the whole file"
    span = f"lines {row}\u2013{end}" if row and end and end != row else (f"line {row}" if row else "")
    # The route (jobs/<job>/steps/2/run) and the step index are the precision that tells two
    # findings on one line apart; they ride the same phrase rather than their own rows.
    step = location.get("step_index")
    precise = " \u00b7 ".join(p for p in (span, route, f"step {step}" if step is not None else "") if p)
    return precise


class ZizmorFindingDetailPanelType:
    slug: ClassVar[str] = "zizmor-finding-detail"
    label: ClassVar[str] = "zizmor Finding"
    view: ClassVar[str] = "zizmor/panels/finding_detail.html"
    css: ClassVar[list[str]] = ["zizmor/css/panels.css"]
    js: ClassVar[list[str]] = []
    editor_view: ClassVar[str] = ""
    config_defaults: ClassVar[dict[str, Any]] = {}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        var = (getattr(panel, "config", None) or {}).get("finding_id_var") or DEFAULT_FINDING_VAR
        requested = (request.GET.get(var) or "").strip() if request else ""

        if not requested:
            return {"finding": None, "state": "no_selection", "requested": ""}
        try:
            finding = ZizmorFinding.objects.filter(entity_id=requested).first()
        except ValueError, TypeError, ValidationError:
            # A malformed id arrives from a URL, so it is user input, not a programming error.
            # Django raises ValidationError (wrapping ValueError) rather than returning empty, and
            # letting it escape would 500 the page on a mistyped link.
            finding = None
        if finding is None:
            # An id that resolves to nothing is said plainly. An empty page here would read like a
            # finding with no content rather than a finding that is not on this grid.
            return {"finding": None, "state": "not_found", "requested": requested}

        location = finding.location or {}
        tags = finding.tags or {}

        return {
            "finding": finding,
            "state": "found",
            "requested": requested,
            "location": location,
            "tags": tags,
            "is_loud": finding.severity in LOUD_SEVERITIES,
            "run": cls._producing_run(finding),
            "workflow": cls._workflow(finding),
            "job": cls._job(finding),
            "action": cls._action(finding),
            # Why an endpoint is missing, when it is. These are the honest-absence records the
            # collector wrote rather than guessing an endpoint.
            "job_unresolved": tags.get("job_unresolved", ""),
            "action_unresolved": tags.get("action_unresolved", ""),
            "reusable_workflow": tags.get("uses_reusable_workflow", ""),
            "ignored_by_config": bool(tags.get("ignored_by_config")),
            "fixes": finding.fixes or [],
            # One phrase rather than three fields that each report the same absence.
            "where": _where(location, location.get("job_key") or ""),
            # What the grid knows that the scanner cannot — see _bearing().
            "bearing": cls._bearing(finding, cls._workflow(finding)),
            "workflow_url": cls._workflow_url(panel, cls._workflow(finding)),
            "source": cls._source(location, cls._workflow(finding)),
            # zizmor's own page for the whole file — every finding on it, annotated — when seeded.
            "file_page_url": file_page_url(cls._workflow(finding)),
        }

    # ------------------------------------------------------------------
    # Joins. Each returns None when the endpoint is genuinely absent; the caller renders the
    # recorded reason rather than a blank.
    # ------------------------------------------------------------------

    @staticmethod
    def _source(location: dict[str, Any], workflow: GithubWorkflow | None) -> dict[str, Any]:
        """The whole workflow file with the flagged span marked, or the excerpt when that is all we have.

        The panel used to render `location.feature` — zizmor's excerpt, which for a workflow-level
        finding is the file and for a step-level one is a handful of lines with no surrounding
        context. github_core already stores the workflow body, so show the document and mark the
        span instead of making the reader imagine what is around it. Three states, not two: a
        workflow with no collected body says so rather than rendering an empty box.
        """
        start = line_of(location.get("row"))
        end = line_of(location.get("end_row")) or start
        body_lines = workflow_body_lines(workflow)
        if body_lines:
            return {
                "lines": [
                    {"n": i, "text": text, "hit": bool(start) and start <= i <= end}
                    for i, text in enumerate(body_lines, start=1)
                ],
                "whole": True,
                "first_hit": start or None,
            }
        excerpt = location.get("feature") or ""
        if not excerpt:
            return {"lines": [], "whole": False, "first_hit": None}
        # The excerpt's own first line IS `row`, so number from there rather than from 1.
        return {
            "lines": [{"n": start + i, "text": t, "hit": True} for i, t in enumerate(excerpt.splitlines())],
            "whole": False,
            "first_hit": start or None,
        }

    @classmethod
    def _workflow_url(cls, panel: Panel, workflow: GithubWorkflow | None) -> str:
        """The instance-declared page for the workflow — see panels/_workflow.py for the rule."""
        return workflow_page_url(panel, workflow)

    @classmethod
    def _bearing(cls, finding: ZizmorFinding, workflow: GithubWorkflow | None) -> dict[str, Any]:
        """What the grid knows that changes how much this finding matters.

        zizmor reads one file and cannot tell a workflow that gates main from a fixture that has
        never run. The grid can. Four things move the decision, and each is stated with its own
        third state rather than collapsed into a reassuring blank:

        * **Exposure** — how the workflow can start. `workflow_dispatch` alone is a different
          risk from `pull_request_target`.
        * **Traffic** — runs IN THE COLLECTED WINDOW. Zero is *not* "never ran"; it is "none in
          what we have", and it is written that way.
        * **Consequence** — the repository's visibility and the criticality its org declares.
        * **Pattern** — the same audit elsewhere. A rule firing across seven files is a default
          someone should change once, not seven bugs.
        """
        from tap_plugin.github_core.models.github_actions_run import GithubActionsRun
        from tap_plugin.github_core.models.github_repository import GithubRepository

        out: dict[str, Any] = {
            "triggers": [],
            "runs": None,
            "visibility": "",
            "criticality": "",
            # None, not 0: without a resolved workflow the file cannot be scoped, and "0 other
            # findings" would read as clean (the same_file/same_audit_files counts are per
            # WORKFLOW ENTITY, via FLAGS_WORKFLOW — `.github/workflows/nightly.yml` names 16
            # different files across this org, and a path-keyed count conflated them).
            "same_file": None,
            "same_audit": 0,
            "same_audit_files": 0,
        }
        siblings = ZizmorFinding.objects.filter(audit_id=finding.audit_id)
        out["same_audit"] = siblings.count()
        out["same_audit_files"] = (
            Edge.objects.filter(from_entity_id__in=siblings.values("entity_id"), edge_type=EDGE_FLAGS_WORKFLOW)
            .values("to_entity_id")
            .distinct()
            .count()
        )

        if workflow is None:
            return out
        this_file = Edge.objects.filter(to_entity_id=workflow.entity_id, edge_type=EDGE_FLAGS_WORKFLOW).values_list(
            "from_entity_id", flat=True
        )
        out["same_file"] = (
            ZizmorFinding.objects.filter(entity_id__in=list(this_file)).exclude(entity_id=finding.entity_id).count()
        )
        cfg = getattr(workflow, "configuration", None) or {}
        out["triggers"] = cfg.get("triggers") or []
        wf_id = getattr(workflow, "workflow_id", None)
        if wf_id:
            out["runs"] = GithubActionsRun.objects.filter(
                full_name=workflow.full_name, configuration__workflow_id=wf_id
            ).count()
        repo = GithubRepository.objects.filter(full_name=workflow.full_name).first()
        if repo is not None:
            out["visibility"] = getattr(repo, "visibility", "") or ""
            out["criticality"] = (getattr(repo, "custom_properties", None) or {}).get("criticality") or ""
        return out

    @staticmethod
    def _producing_run(finding: ZizmorFinding) -> ZizmorRun | None:
        run_ids = Edge.objects.filter(to_entity_id=finding.entity_id, edge_type=EDGE_PRODUCED_FINDING).values_list(
            "from_entity_id", flat=True
        )
        return ZizmorRun.objects.filter(entity_id__in=list(run_ids)).order_by("-started_at").first()

    @staticmethod
    def _workflow(finding: ZizmorFinding) -> GithubWorkflow | None:
        ids = Edge.objects.filter(from_entity_id=finding.entity_id, edge_type=EDGE_FLAGS_WORKFLOW).values_list(
            "to_entity_id", flat=True
        )
        return GithubWorkflow.objects.filter(entity_id__in=list(ids)).first()

    @staticmethod
    def _job(finding: ZizmorFinding) -> WorkflowJob | None:
        """The declared job the flagged line runs in — and, through it, what that job may DO.

        This is the join that turns a lint result into a risk statement: the same audit on a job
        with `contents: write` on a self-hosted runner is a different problem from one on a
        read-only job.
        """
        ids = Edge.objects.filter(from_entity_id=finding.entity_id, edge_type=EDGE_FLAGS_JOB).values_list(
            "to_entity_id", flat=True
        )
        return WorkflowJob.objects.filter(entity_id__in=list(ids)).first()

    @staticmethod
    def _action(finding: ZizmorFinding) -> dict[str, Any] | None:
        """The referenced action plus the exact pin the finding was reporting on.

        The node is keyed with the ref STRIPPED (one `actions/checkout` for the whole grid), so the
        pin lives on the edge. Both are shown: the action to navigate to, the pin to act on.
        """
        edge = Edge.objects.filter(from_entity_id=finding.entity_id, edge_type=EDGE_FLAGS_ACTION).first()
        if edge is None:
            return None
        action = GithubAction.objects.filter(entity_id=edge.to_entity_id).first()
        if action is None:
            return None
        return {"action": action, "uses": (edge.properties or {}).get("uses", "")}
