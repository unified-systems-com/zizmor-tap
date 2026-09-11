"""What zizmor's panels know about a github_core workflow — derived once, used by every panel.

Spec: specs/spec-zizmor-v0.md (req-zizmor-panel-finding-detail, req-zizmor-panel-workflow-source).

Two panels read the same three facts about a workflow: where its own page is on this grid, what its
collected body looks like line by line, and which tone a severity carries. Each fact lives here once;
the finding-detail and workflow-source panels call these rather than restating them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from tap_plugin.github_core.models.github_workflow import GithubWorkflow

    from tap_web.models import Panel

#: Where to send a reader who wants the workflow itself — its anatomy, its jobs, its run history.
#: NOT hardcoded: zizmor depends on github_core, not on any product's pages, so the consuming
#: instance names the target in panel config as a URL template (`workflow_page_template`) with
#: `{full_name}`, `{path}` and `{workflow_id}` placeholders — the same idiom as a graph panel's
#: nav_rules. The link renders only when the page it names exists on this grid, so a deployment
#: without one gets no link rather than a dead one.
WORKFLOW_PAGE_FIELDS = ("full_name", "path", "workflow_id")

#: zizmor's own page for one workflow file — every finding on it, annotated. Zizmor's route, so
#: zizmor may name it; it still renders only when the page is on the grid.
FILE_PAGE_TEMPLATE = "/zizmor/workflow?workflow_id={workflow_id}"

#: Severity → tone, the vocabulary the findings table's badges already use. `muted` is the resting
#: state; anything unknown is muted rather than quietly loud.
SEVERITY_TONE = {"High": "bad", "Medium": "warn", "Low": "muted", "Informational": "muted"}
SEVERITY_RANK = {"High": 0, "Medium": 1, "Low": 2, "Informational": 3}


def line_of(row: object) -> int:
    """The 1-based line a stored `location.row` / `end_row` denotes.

    zizmor's rows come from tree-sitter points, which count from 0 — the finding that reads
    `row: 39` sits on line 40 of the file. Verified against collected bodies on 2026-09-10 (8 of 8
    snippets matched at row + 1, none at row; zizmor-tap#35). Every surface that names a line or
    marks one derives it here, so the convention is decided once. A missing or unparsable row is 0:
    "no line", which callers render as such rather than as line 1.
    """
    try:
        n = int(row)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return 0
    return n + 1 if n >= 0 else 0


def severity_tone(severity: str) -> str:
    return SEVERITY_TONE.get(severity or "", "muted")


def severity_rank(severity: str) -> int:
    return SEVERITY_RANK.get(severity or "", 9)


def fill_page_template(template: str, workflow: GithubWorkflow | None) -> str:
    """Fill a page template over the workflow's fields, and check the page exists.

    Returns "" when there is no template, no workflow, a placeholder with no value (a half-filled
    URL is a wrong page), or no Page on this grid with the template's slug (a dead link that looks
    live is worse than no link; which page plays a role is the instance's choice, not zizmor's).
    """
    from tap_web.models import Page

    template = (template or "").strip()
    if not template or workflow is None:
        return ""
    url = template
    for field in WORKFLOW_PAGE_FIELDS:
        token = "{" + field + "}"
        if token not in url:
            continue
        value = getattr(workflow, field, None)
        if value in (None, ""):
            return ""
        url = url.replace(token, quote(str(value), safe="/"))
    slug = url.split("?", 1)[0]
    return url if Page.objects.filter(slug=slug).exists() else ""


def workflow_page_url(panel: Panel, workflow: GithubWorkflow | None) -> str:
    """The instance-declared page for the workflow itself (`panel.config.workflow_page_template`)."""
    template = ((getattr(panel, "config", None) or {}).get("workflow_page_template") or "").strip()
    return fill_page_template(template, workflow)


def file_page_url(workflow: GithubWorkflow | None) -> str:
    """zizmor's own annotated-file page for this workflow, when it is seeded on this grid."""
    return fill_page_template(FILE_PAGE_TEMPLATE, workflow)


def workflow_body_lines(workflow: GithubWorkflow | None) -> list[str]:
    """The collected workflow body as lines, or [] when github_core captured none.

    An empty list is a fact the caller must render ("no body collected"), never a blank box.
    """
    body = ((getattr(workflow, "configuration", None) or {}).get("raw_yaml") or "") if workflow else ""
    return body.splitlines() if body else []
