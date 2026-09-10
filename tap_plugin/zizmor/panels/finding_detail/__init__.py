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

import json
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

EDGE_PRODUCED_FINDING = "PRODUCED_FINDING__zizmor"
EDGE_FLAGS_WORKFLOW = "FLAGS_WORKFLOW__zizmor"
EDGE_FLAGS_JOB = "FLAGS_JOB__zizmor"
EDGE_FLAGS_ACTION = "FLAGS_ACTION__zizmor"

#: Severities that deserve visual weight. Kept here rather than in the template so the template
#: stays dumb and the decision is reviewable in one place.
LOUD_SEVERITIES = frozenset({"High", "Medium"})


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

        job = cls._job(finding)
        action = cls._action(finding)
        workflow = cls._workflow(finding)

        # Presence is computed HERE, not asked in the template. A section that renders its heading
        # and its explanation above an empty body is worse than one that is absent: it promises
        # context and delivers a blank, which reads as "no permissions" rather than "not recorded".
        job_facts = (
            [
                (label, cls._humanize(value))
                for label, value in (
                    ("Permissions", job.permissions),
                    ("Runner", job.runs_on),
                    ("Environment", job.environment),
                    ("Condition", job.if_condition),
                )
                if value
            ]
            if job is not None
            else []
        )

        # The same string rendered twice reads as two facts. The narrowed fragment is only worth
        # calling out separately when it is genuinely narrower than the excerpt it sits in.
        feature = (location.get("feature") or "").strip()
        subfeature = (location.get("subfeature") or "").strip()
        fragment_is_distinct = bool(subfeature) and subfeature != feature

        first_seen, last_seen = finding.known_since, finding.observed_at

        return {
            "finding": finding,
            "state": "found",
            "requested": requested,
            "location": location,
            "tags": tags,
            "severity_key": (finding.severity or "unknown").lower(),
            "is_loud": finding.severity in LOUD_SEVERITIES,
            "run": cls._producing_run(finding),
            "workflow": workflow,
            "job": job,
            "job_facts": job_facts,
            "action": action,
            # A job whose key and display name are the same word is one fact, not two.
            "job_label": cls._job_label(job, location),
            "fragment": subfeature if fragment_is_distinct else "",
            "excerpt": feature,
            "first_seen": first_seen,
            "last_seen": last_seen,
            # When a finding has only ever been seen once these are the same instant; showing both
            # invites reading a re-observation into a single sighting.
            "seen_once": bool(first_seen and last_seen and first_seen == last_seen),
            "job_unresolved": tags.get("job_unresolved", ""),
            "action_unresolved": tags.get("action_unresolved", ""),
            "reusable_workflow": tags.get("uses_reusable_workflow", ""),
            "ignored_by_config": bool(tags.get("ignored_by_config")),
            "fixes": finding.fixes or [],
            # JSON, not pprint: pprint emits Python repr, whose quotes HTML-escape into a wall of
            # &#x27; that nobody can read.
            "raw_json": json.dumps(finding.raw or {}, indent=2, sort_keys=True, default=str),
        }

    @staticmethod
    def _humanize(value: Any) -> str:
        """Render a JSONField value as prose, not as Python repr.

        `permissions` and `runs_on` are JSONFields, so a bare `str()` puts `{'issues': 'write'}` and
        `['ubuntu-latest']` on the page — Python syntax leaking into a UI, quotes and all, which the
        template then HTML-escapes into `&#x27;` soup. A permissions map reads as pairs and a runner
        list reads as a list, because that is what they are.
        """
        if isinstance(value, dict):
            return ", ".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        return str(value)

    @staticmethod
    def _job_label(job: WorkflowJob | None, location: dict[str, Any]) -> str:
        """One label for the job: its key, plus its display name only when that adds something."""
        if job is None:
            return str(location.get("job_key") or "")
        name = (job.name or "").strip()
        key = (job.job_key or "").strip()
        return f"{key} — {name}" if name and name != key else key

    # ------------------------------------------------------------------
    # Joins. Each returns None when the endpoint is genuinely absent; the caller renders the
    # recorded reason rather than a blank.
    # ------------------------------------------------------------------

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
