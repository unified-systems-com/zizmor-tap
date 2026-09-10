"""The landing page and its panels.

req-zizmor-page-landing, req-zizmor-panel-about, req-zizmor-panel-coverage,
req-zizmor-panel-findings-table, req-zizmor-panel-runs-table.

The assertions that matter here are about **what the page refuses to imply**. A findings table on
its own renders a workflow nobody scanned identically to one that came back clean, and on a real
organisation that is 40 workflows in 117 (*observed* 2026-09-10) — a third of the estate reading as
safe because nothing said otherwise. So the coverage panel's counts, and the fact that it is
mounted on the same page as the findings, are tested as behaviour rather than left to layout.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from django.utils import timezone
from tap_plugin.zizmor.models.run import ZizmorRun
from tap_plugin.zizmor.panels.about import ZizmorAboutPanelType
from tap_plugin.zizmor.panels.coverage import ZizmorCoveragePanelType

from tap_grid.models import Edge, Entity
from tap_grid.services import create_node

BUNDLE = Path(__file__).resolve().parent.parent / "grift" / "pages.grift.json"
SCANNED_WORKFLOW = "SCANNED_WORKFLOW__zizmor"


def _bundle() -> dict[str, Any]:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


class _FakePanel:
    """Stand-in for a Panel row; the panel types read only `config`."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}


# ---------------------------------------------------------------------------
# The seeded bundle.
# ---------------------------------------------------------------------------


def _slots_and_wiring(batch: dict[str, Any], page: dict[str, Any]) -> tuple[set[str], set[str]]:
    """A page's declared layout slots, and the panels actually wired into them."""
    slots = {row["panel-id"] for col in page["node"]["layout"]["columns"].values() for row in col["rows"].values()}
    hotlinks = {
        e["edge"]["properties"]["hotlink"]["value"]
        for e in batch["edges"]
        if e["edge"]["edge_type"] == "USES_PANEL" and e["edge"]["from_entity_id"] == page["entity"]["entity_id"]
    }
    return slots, hotlinks


def _page(batch: dict[str, Any], slug: str) -> dict[str, Any]:
    return next(n for n in batch["nodes"] if n["entity"]["entity_type"] == "page" and n["node"]["slug"] == slug)


def test_the_landing_page_mounts_four_panels() -> None:
    """Four, not three: coverage is here because a findings table alone cannot tell the truth."""
    batch = _bundle()["batches"][0]

    slots, hotlinks = _slots_and_wiring(batch, _page(batch, "/zizmor"))

    assert slots == hotlinks == {"about", "findings", "coverage", "runs"}


def test_every_seeded_page_has_all_of_its_slots_wired() -> None:
    """Asserted for EVERY page, so it keeps holding as pages are added.

    A USES_PANEL edge whose hotlink matches no slot renders nothing; a slot with no edge renders an
    empty box. Both fail silently, so both are checked.
    """
    batch = _bundle()["batches"][0]
    pages = [n for n in batch["nodes"] if n["entity"]["entity_type"] == "page"]
    assert pages, "the bundle seeds no pages"

    for page in pages:
        slots, hotlinks = _slots_and_wiring(batch, page)
        assert slots == hotlinks, f"{page['node']['slug']}: slots {slots} != wired panels {hotlinks}"


def test_coverage_sits_with_the_findings_not_on_another_page() -> None:
    """The whole point: coverage has to be visible to the same reader, at the same moment.

    A coverage panel one click away is a coverage panel nobody opens, and the findings list is then
    read as the complete picture.
    """
    page = next(n for n in _bundle()["batches"][0]["nodes"] if n["entity"]["entity_type"] == "page")
    order = [row["panel-id"] for row in page["node"]["layout"]["columns"]["col-1"]["rows"].values()]

    assert order.index("coverage") == order.index("findings") + 1


def test_each_panel_instance_points_at_a_real_panel_type_view() -> None:
    """`panel.view` must match the type's `view` exactly, or the slot renders nothing."""
    views = {
        n["node"]["slug"]: n["node"]["view"]
        for n in _bundle()["batches"][0]["nodes"]
        if n["entity"]["entity_type"] == "panel"
    }

    assert views["zizmor-about"] == ZizmorAboutPanelType.view
    assert views["zizmor-coverage"] == ZizmorCoveragePanelType.view
    # The two tables are standard tap_web table panels, not custom types.
    assert views["zizmor-findings-table"] == "tap_web/panels/table_panel.html"
    assert views["zizmor-runs-table"] == "tap_web/panels/table_panel.html"


def test_the_searches_return_a_node_not_a_projection() -> None:
    """Envelope mode. A search that RETURNs aliases yields rows and ZERO nodes, and the table —
    which reads nodes — then renders nothing at all, silently."""
    for search in (n for n in _bundle()["batches"][0]["nodes"] if n["entity"]["entity_type"] == "search"):
        query = " ".join(search["node"]["definition"]["query"])
        assert search["node"]["root"] == "node"
        returned = query.split("RETURN")[1].split("ORDER BY")[0].strip()
        assert returned.isidentifier(), f"{search['node']['name']} returns a projection, not a bound node: {returned!r}"


def test_the_findings_table_surfaces_first_seen_alongside_last_seen() -> None:
    """`known_since` next to `observed_at` is what answers "how long has this been here"."""
    panel = next(
        n
        for n in _bundle()["batches"][0]["nodes"]
        if n["entity"]["entity_type"] == "panel" and n["node"]["slug"] == "zizmor-findings-table"
    )
    fields = {c["field"] for c in panel["node"]["config"]["columns"]}

    assert {"data.observed_at", "data.known_since"} <= fields


# ---------------------------------------------------------------------------
# The About panel.
# ---------------------------------------------------------------------------


def _run(**overrides: Any) -> ZizmorRun:
    fields: dict[str, Any] = {
        "scanner_version": "1.30.0",
        "persona": "Auditor",
        "audit_set": [f"audit-{i}" for i in range(36)],
        "skipped_audits": ["impostor-commit", "ref-confusion"],
        "outcome": "ok",
        "source_collection_job": str(uuid.uuid7()),
        "started_at": timezone.now().isoformat(),
        "finished_at": timezone.now().isoformat(),
        "workflows_evaluated": 2,
        "tags": {"skipped_audit_reasons": {"impostor-commit": "can't run without a GitHub API token"}},
    }
    fields.update(overrides)
    result = create_node("zizmor__run", fields)
    assert result.success, result.errors
    return ZizmorRun.objects.get(entity_id=result.entity_id)


def test_about_reads_the_run_rather_than_asking_the_binary(db: None) -> None:
    """Version and persona are properties of an EXECUTION, at one pin, at one moment.

    Asking the installed binary now would report today's version against findings some other
    version produced.
    """
    _run(scanner_version="1.29.0")

    ctx = ZizmorAboutPanelType.get_view_context(_FakePanel(), None)

    assert ctx["run"].scanner_version == "1.29.0"
    assert ctx["audits_ran"] == 36


def test_about_names_why_each_skipped_audit_could_not_run(db: None) -> None:
    """ "36 audits ran" alone invites the reading that the other five found nothing."""
    _run()

    skipped = {s["audit_id"]: s["reason"] for s in ZizmorAboutPanelType.get_view_context(_FakePanel(), None)["skipped"]}

    assert skipped["impostor-commit"] == "can't run without a GitHub API token"
    # No recorded reason must still say something, not render blank.
    assert skipped["ref-confusion"]


def test_about_on_a_grid_with_no_run_says_so(db: None) -> None:
    """A legitimate, readable state — not an error, and not an empty panel that looks broken."""
    ctx = ZizmorAboutPanelType.get_view_context(_FakePanel(), None)

    assert ctx["run"] is None
    assert ctx["skipped"] == []


# ---------------------------------------------------------------------------
# The Coverage panel — the reason this page can be trusted.
# ---------------------------------------------------------------------------


def _workflow(path: str, workflow_id: int) -> uuid.UUID:
    result = create_node(
        "github_core__github_workflow",
        {
            "name": Path(path).stem,
            "full_name": "acme/repo",
            "workflow_id": workflow_id,
            "path": path,
            "state": "active",
            "configuration": {},
        },
    )
    assert result.success, result.errors
    return result.entity_id


def _scanned(run: ZizmorRun, workflow: uuid.UUID, outcome: str, reason: str = "") -> None:
    props: dict[str, Any] = {"outcome": outcome}
    if outcome != "evaluated":
        props["reason"] = reason or "because"
    Edge.objects.create(
        entity=Entity.objects.create(id=uuid.uuid7(), entity_type="edge", name=SCANNED_WORKFLOW, dimensions={}),
        from_entity_id=run.entity_id,
        to_entity_id=workflow,
        edge_type=SCANNED_WORKFLOW,
        properties=props,
    )


def test_coverage_counts_the_workflows_the_scanner_never_read(db: None) -> None:
    run = _run()
    _scanned(run, _workflow(".github/workflows/a.yml", 1), "evaluated")
    _scanned(run, _workflow(".github/workflows/b.yml", 2), "no-yaml", "no raw_yaml was captured")
    _scanned(run, _workflow(".github/workflows/c.yml", 3), "parse-failed", "exit 3")

    ctx = ZizmorCoveragePanelType.get_view_context(_FakePanel(), None)

    assert ctx["total"] == 3
    assert ctx["unobserved_total"] == 2, "no-yaml and parse-failed are both 'never actually read'"
    outcomes = {g["outcome"]: g["count"] for g in ctx["groups"]}
    assert outcomes == {"no-yaml": 1, "parse-failed": 1, "evaluated": 1}


def test_coverage_puts_the_unread_states_before_the_scanned_one(db: None) -> None:
    """Reading order is the message: the states whose findings are UNKNOWN come first."""
    run = _run()
    _scanned(run, _workflow(".github/workflows/a.yml", 1), "evaluated")
    _scanned(run, _workflow(".github/workflows/b.yml", 2), "no-yaml", "none captured")

    order = [g["outcome"] for g in ZizmorCoveragePanelType.get_view_context(_FakePanel(), None)["groups"]]

    assert order.index("no-yaml") < order.index("evaluated")


def test_coverage_carries_the_reason_for_every_unread_workflow(db: None) -> None:
    """An unexplained gap is one a reader cannot act on."""
    run = _run()
    _scanned(run, _workflow(".github/workflows/b.yml", 2), "no-yaml", "github_core captured no raw_yaml")

    group = next(
        g for g in ZizmorCoveragePanelType.get_view_context(_FakePanel(), None)["groups"] if g["outcome"] == "no-yaml"
    )

    assert group["named"][0]["reason"] == "github_core captured no raw_yaml"
    assert "acme/repo" in group["named"][0]["workflow"]


def test_coverage_reports_workflows_this_run_never_considered_at_all(db: None) -> None:
    """Distinct from every outcome: not 'scanned and X', but absent from the run entirely.

    This is the state that appears when a workflow lands after a run finished — and the one that
    would otherwise be invisible, because a run cannot record an outcome it never reached.
    """
    run = _run()
    _scanned(run, _workflow(".github/workflows/a.yml", 1), "evaluated")
    _workflow(".github/workflows/orphan.yml", 99)  # on the grid, no edge from this run

    ctx = ZizmorCoveragePanelType.get_view_context(_FakePanel(), None)

    assert ctx["unreached"] == 1


def test_coverage_caps_the_named_list_but_keeps_the_count_whole(db: None) -> None:
    """A panel that printed 40 paths would bury the number that matters."""
    run = _run()
    for i in range(12):
        _scanned(run, _workflow(f".github/workflows/w{i}.yml", 100 + i), "no-yaml", "none captured")

    group = next(
        g
        for g in ZizmorCoveragePanelType.get_view_context(_FakePanel({"max_named": 5}), None)["groups"]
        if g["outcome"] == "no-yaml"
    )

    assert group["count"] == 12
    assert len(group["named"]) == 5
    assert group["remainder"] == 7


def test_coverage_on_a_grid_with_no_run_refuses_to_imply_clean(db: None) -> None:
    ctx = ZizmorCoveragePanelType.get_view_context(_FakePanel(), None)

    assert ctx["run"] is None
    assert ctx["groups"] == []
    assert ctx["total"] == 0
