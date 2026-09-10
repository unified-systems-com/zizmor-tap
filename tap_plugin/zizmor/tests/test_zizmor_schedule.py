"""The seeded schedule, and the staleness guard that keeps a run honest.

req-zizmor-trigger (`specs/spec-zizmor-v0.md`).

Two independent things are asserted here, and they fail for different reasons.

The **bundle** is a declaration: a schedule node targeting this collector, at a cadence somebody
chose. Its one hard requirement is that the `SCHEDULED_TARGET` edge resolves to the collector's
DERIVED entity id — a hardcoded id that drifts from the registry dangles, and boot population then
aborts on every fresh spawn.

The **guard** is behaviour: a fire that lands while github_core is still writing must skip and
create no run node at all. Not a run with `outcome="skipped"` — no run. A run node asserts that a
scan happened, and one that never started must not leave a record claiming coverage it does not
have. That distinction is the whole point of `req-zizmor-trigger-3`, and it is the kind that gets
quietly collapsed by a later refactor, so it is pinned here.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from django.utils import timezone
from tap_plugin.zizmor.collectors.zizmor_collector.collector import ZizmorCollector
from tap_plugin.zizmor.models.run import ZizmorRun

from tap_cares.collectors.config import CollectorConfig
from tap_cares.models import CollectionJob, CollectionJobStatus
from tap_cares.registry import NAMESPACE_COLLECTOR
from tap_grid.models import Edge, Entity
from tap_grid.services import create_node

BUNDLE = Path(__file__).resolve().parent.parent / "grift" / "schedule.grift.json"
UPSTREAM_KEY = "github_core:github_core"


def _bundle() -> dict:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def test_the_schedule_targets_this_collectors_derived_id() -> None:
    """A hardcoded target that drifts from the registry dangles and breaks every fresh spawn."""
    edges = _bundle()["batches"][0]["edges"]
    target = next(e["edge"]["to_entity_id"] for e in edges if e["edge"]["edge_type"] == "SCHEDULED_TARGET")

    assert target == str(uuid.uuid5(NAMESPACE_COLLECTOR, "zizmor:zizmor"))


def test_the_schedule_node_is_enabled_and_carries_a_cron() -> None:
    node = _bundle()["batches"][0]["nodes"][0]

    assert node["entity"]["entity_type"] == "schedule"
    assert node["node"]["enabled"] is True
    assert node["node"]["cron_expression"] == "23 */6 * * *"
    # Off the hour deliberately, so this does not pile onto the top-of-hour scheduler tick.
    assert not node["node"]["cron_expression"].startswith("0 ")


def test_the_schedule_edge_points_from_the_schedule_node() -> None:
    """The declared edge must actually leave the node this bundle seeds."""
    batch = _bundle()["batches"][0]
    node_id = batch["nodes"][0]["entity"]["entity_id"]
    edge = next(e for e in batch["edges"] if e["edge"]["edge_type"] == "SCHEDULED_TARGET")

    assert edge["edge"]["from_entity_id"] == node_id
    assert edge["entity"]["entity_type"] == "edge"


def _seed_upstream_job(status: str) -> str:
    """One github_core collection job in the given state, linked to its collector."""
    collector_uuid = uuid.uuid5(NAMESPACE_COLLECTOR, UPSTREAM_KEY)
    Entity.objects.get_or_create(
        id=collector_uuid,
        defaults={"entity_type": "collector", "name": "GitHub Core Collector", "dimensions": {}},
    )
    job_entity = Entity.objects.create(
        id=uuid.uuid7(), entity_type="collection_job", name=f"github_core collection ({status})", dimensions={}
    )
    CollectionJob.objects.create(
        entity=job_entity,
        name=f"github_core collection ({status})",
        status=status,
        started_at=timezone.now(),
        finished_at=timezone.now() if status == CollectionJobStatus.SUCCESSFUL else None,
    )
    Edge.objects.create(
        entity=Entity.objects.create(id=uuid.uuid7(), entity_type="edge", name="HAS_COLLECTION_JOB", dimensions={}),
        from_entity_id=collector_uuid,
        to_entity_id=job_entity.id,
        edge_type="HAS_COLLECTION_JOB",
        properties={},
    )
    return str(job_entity.id)


def _collector() -> ZizmorCollector:
    return ZizmorCollector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))


@pytest.mark.parametrize("status", [CollectionJobStatus.RUNNING, CollectionJobStatus.READY])
def test_a_fire_while_github_core_is_writing_creates_no_run_node(db: None, status: str) -> None:
    """req-zizmor-trigger-3: skipped means NO run, not a run recorded as skipped.

    READY counts as in flight: the job row exists and its task is queued, so rows may begin landing
    at any moment.
    """
    active = _seed_upstream_job(status)

    collector = _collector()
    collector.run()

    assert ZizmorRun.objects.count() == 0, "a skipped fire must leave no run node claiming coverage"
    assert active in collector.summary
    codes = {entry["message_code"] for entry in collector.results["info"]}
    assert "UPSTREAM_COLLECTION_ACTIVE" in codes
    assert not collector.results["error"], "skipping is a normal outcome, not a failure"


def test_the_skip_names_the_job_that_caused_it(db: None) -> None:
    """An unexplained skip is a coverage gap nobody can act on."""
    active = _seed_upstream_job(CollectionJobStatus.RUNNING)

    collector = _collector()
    collector.run()

    recorded = [e for e in collector.results["info"] if e["message_code"] == "UPSTREAM_COLLECTION_ACTIVE"]
    assert recorded, "the skip must be recorded, not silent"
    assert recorded[0]["message_data"]["github_core_collection_job"] == active


def test_a_completed_upstream_collection_does_not_block_a_run(db: None) -> None:
    """The guard asks 'is a collection writing now', not 'how old is the last one'.

    A stale-but-quiet grid is safe to audit; blocking on age would stop the collector forever on an
    instance whose github_core collection has finished for good.
    """
    _seed_upstream_job(CollectionJobStatus.SUCCESSFUL)

    collector = _collector()
    assert collector._active_upstream_job() is None


def test_a_run_that_proceeds_names_the_collection_it_read(db: None) -> None:
    """req-zizmor-trigger-4, asserted rather than assumed: the model refuses a completed run whose
    `source_collection_job` is empty, so this proves the collector populates it."""
    job = _seed_upstream_job(CollectionJobStatus.SUCCESSFUL)

    assert ZizmorCollector._latest_upstream_job() == job


def test_an_upstream_collection_that_starts_mid_run_discards_the_scan(db: None) -> None:
    """The check/use race the first guard cannot close, closed at the other end.

    The guard at the top of `run()` proves only that no collection was in flight when the audit
    STARTED. One can begin while rows are being read, and the findings would then describe a grid
    being rewritten underneath them. Re-checking before landing is what makes the published coverage
    number one the run can stand behind; discarding a completed offline pass is the cheap side of
    that trade.
    """
    _seed_upstream_job(CollectionJobStatus.SUCCESSFUL)  # lets the run start
    # A workflow with real YAML, so the run gets past collection and all the way to landing —
    # which is the only place the race can be observed.
    created = create_node(
        "github_core__github_workflow",
        {
            "name": "ci",
            "full_name": "acme/repo",
            "workflow_id": 4242,
            "path": ".github/workflows/ci.yml",
            "state": "active",
            "configuration": {"raw_yaml": "name: ci\non: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@main\n"},
        },
    )
    assert created.success, created.errors
    collector = _collector()

    real_check = collector._active_upstream_job
    calls: list[int] = []

    def _racing() -> str | None:
        calls.append(1)
        # Clear on the way in; a collection appears by the time we are ready to land.
        return None if len(calls) == 1 else _seed_upstream_job(CollectionJobStatus.RUNNING)

    collector._active_upstream_job = _racing  # type: ignore[method-assign]
    collector.run()

    assert ZizmorRun.objects.count() == 0, "a raced run must land nothing at all"
    codes = {e["message_code"] for e in collector.results["info"]}
    assert "UPSTREAM_COLLECTION_RACED" in codes
    assert not collector.results["error"], "losing a race is a normal outcome, not a failure"
    assert real_check is not None
