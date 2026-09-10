"""End-to-end proof of the collector against zizmor's OWN test corpus.

req-zizmor-record (`specs/spec-zizmor-v0.md`).

The live run against a real organisation proves the collector works *today*, on one grid, against
whatever that organisation happens to contain. This proves it *stays* working — offline, in a fork,
with no credential and no network — and it does so against zizmor's expectations rather than ours.

**Why the corpus is vendored from upstream.** A corpus we wrote would test our idea of what zizmor
finds. Each file here is named by zizmor for the audit it demonstrates, so the expectation is the
scanner project's declaration, not a snapshot of our own output played back to us.

**Why the input is seeded in the test rather than shipped.** The collector's input is
`GithubWorkflow` rows, which on a real grid are github_core's observations. Rows created here live
in the test transaction and roll back with it. Shipping them as a GRIFT bundle, or seeding them from
a boot record, would put nodes on a live grid that are indistinguishable from observed ones — and a
boot record's population does not run in CI anyway, so it would prove nothing while creating exactly
that risk.

**The clean case is the load-bearing one.** `neutral.yml` is upstream's known-good workflow. Without
asserting that a scanned-and-clean workflow yields zero findings *and still carries an `evaluated`
coverage edge*, a collector that silently produced nothing at all would satisfy everything else here.

Each test re-runs the collection deliberately. The obvious optimisation — one module-scoped run
shared by twenty tests — fights the repo's pytest harness (`tap/pytest_harness.py`), which binds the
caller context and the below-service write hatch *per test*. Work done outside those escapes the
per-test transaction, and because finding ids are deterministic uuid5, leftover Entity rows collide
with the next run's ids. Three coarse tests keep the harness's guarantees and pay for three scans.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from django.utils import timezone
from tap_plugin.zizmor.collectors.zizmor_collector.collector import (
    EDGE_FLAGS_WORKFLOW,
    EDGE_PRODUCED_FINDING,
    EDGE_SCANNED_WORKFLOW,
    ZizmorCollector,
)
from tap_plugin.zizmor.models.finding import ZizmorFinding
from tap_plugin.zizmor.models.run import ZizmorRun

from tap_cares.collectors.config import CollectorConfig
from tap_cares.models import CollectionJob, CollectionJobStatus
from tap_cares.registry import NAMESPACE_COLLECTOR
from tap_grid.models import Edge, Entity
from tap_grid.services import create_node

CORPUS_DIR = Path(__file__).resolve().parent / "corpus" / "workflows"
CORPUS_REPO = "zizmor-corpus/audits"

#: Upstream file -> the audit id it is named for. zizmor's own grouping is the oracle; the single
#: divergence (`self-hosted.yml` demonstrates the `self-hosted-runner` audit) is spelled out rather
#: than derived from the filename, because a naming rule that mostly works is worse than a table.
#:
#: Only audits that RUN OFFLINE appear here — the five needing a GitHub API token
#: (`impostor-commit`, `ref-confusion`, `known-vulnerable-actions`, `stale-action-refs`,
#: `ref-version-mismatch`) cannot fire under `--offline`, so expecting them would assert a
#: permanent absence.
EXPECTED_AUDIT_BY_FILE: dict[str, str] = {
    "artipacked.yml": "artipacked",
    "anonymous-definition.yml": "anonymous-definition",
    "excessive-permissions.yml": "excessive-permissions",
    "template-injection.yml": "template-injection",
    "unpinned-uses.yml": "unpinned-uses",
    "cache-poisoning.yml": "cache-poisoning",
    "insecure-commands.yml": "insecure-commands",
    "secrets-inherit.yml": "secrets-inherit",
    "self-hosted.yml": "self-hosted-runner",
    "obfuscation.yml": "obfuscation",
    "bot-conditions.yml": "bot-conditions",
    "github-app.yml": "github-app",
    "use-trusted-publishing.yml": "use-trusted-publishing",
}

CLEAN_FILE = "neutral.yml"
INVALID_FILE = "bad-yaml.yml"
#: A workflow github_core collected but captured no YAML for — 40 of 117 on a real organisation
#: (*observed* 2026-09-10), and the state most easily misread as "clean".
NO_YAML_PATH = ".github/workflows/collected-without-yaml.yml"


class Collected:
    """One completed corpus run plus the workflow endpoints it was given."""

    __slots__ = ("run", "workflows")

    def __init__(self, *, run: ZizmorRun, workflows: dict[str, uuid.UUID]) -> None:
        self.run = run
        self.workflows = workflows

    def findings_for(self, key: str) -> list[ZizmorFinding]:
        produced = set(
            Edge.objects.filter(from_entity_id=self.run.entity_id, edge_type=EDGE_PRODUCED_FINDING).values_list(
                "to_entity_id", flat=True
            )
        )
        flagging = set(
            Edge.objects.filter(
                to_entity_id=self.workflows[key],
                edge_type=EDGE_FLAGS_WORKFLOW,
                from_entity_id__in=produced,
            ).values_list("from_entity_id", flat=True)
        )
        return list(ZizmorFinding.objects.filter(entity_id__in=flagging))

    def coverage_for(self, key: str) -> dict[str, Any]:
        edge = Edge.objects.filter(
            from_entity_id=self.run.entity_id,
            to_entity_id=self.workflows[key],
            edge_type=EDGE_SCANNED_WORKFLOW,
        ).first()
        assert edge is not None, f"the run recorded no coverage edge for {key}"
        return dict(edge.properties)


def _seed_upstream_collection() -> None:
    """Give the run a github_core collection to name as its provenance.

    The collector refuses to produce findings it cannot attribute to a collection
    (`req-zizmor-trigger-4`) — correct behaviour, and it means the test must supply the upstream job
    a real grid would already have. Written with the ORM because `collection_job` is an
    INTERNAL_ONLY type whose sole writer is the tap_cares task body: there is no service verb to
    create one, and producing it "properly" would mean running a github_core collection, which needs
    the credential and network this test exists to do without. The harness's autouse write hatch
    sanctions the below-service write.
    """
    # The edge's source must exist on the spine: `Edge.from_entity_id` is a real foreign key, and
    # the github_core collector node is normally created by `reconcile_collector_nodes()` at boot.
    collector_uuid = uuid.uuid5(NAMESPACE_COLLECTOR, "github_core:github_core")
    Entity.objects.get_or_create(
        id=collector_uuid,
        defaults={"entity_type": "collector", "name": "GitHub Core Collector", "dimensions": {}},
    )
    job_entity = Entity.objects.create(
        id=uuid.uuid7(), entity_type="collection_job", name="seeded github_core collection", dimensions={}
    )
    CollectionJob.objects.create(
        entity=job_entity,
        name="seeded github_core collection",
        status=CollectionJobStatus.SUCCESSFUL,
        finished_at=timezone.now(),
    )
    Edge.objects.create(
        entity=Entity.objects.create(id=uuid.uuid7(), entity_type="edge", name="HAS_COLLECTION_JOB", dimensions={}),
        from_entity_id=collector_uuid,
        to_entity_id=job_entity.id,
        edge_type="HAS_COLLECTION_JOB",
        properties={},
    )


def _seed_workflow(*, path: str, raw_yaml: str | None, workflow_id: int) -> uuid.UUID:
    """Create one github_core workflow row through the service layer.

    Service-layer setup rather than direct ORM, per the repo's testing rules: the row the collector
    reads is then shaped by the same write path a real collection uses.
    """
    result = create_node(
        "github_core__github_workflow",
        {
            "name": Path(path).stem,
            "full_name": CORPUS_REPO,
            "workflow_id": workflow_id,
            "path": path,
            "state": "active",
            "configuration": {"raw_yaml": raw_yaml} if raw_yaml is not None else {},
        },
    )
    assert result.success, f"seeding {path} failed: {result.errors}"
    return result.entity_id


@pytest.fixture
def collected(db: None) -> Collected:
    """Seed the corpus and run the collector over it."""
    _seed_upstream_collection()
    workflows: dict[str, uuid.UUID] = {}
    for index, filename in enumerate(sorted([*EXPECTED_AUDIT_BY_FILE, CLEAN_FILE, INVALID_FILE])):
        workflows[filename] = _seed_workflow(
            path=f".github/workflows/{filename}",
            raw_yaml=(CORPUS_DIR / filename).read_text(encoding="utf-8"),
            workflow_id=900_000 + index,
        )
    workflows[NO_YAML_PATH] = _seed_workflow(path=NO_YAML_PATH, raw_yaml=None, workflow_id=999_999)

    collector = ZizmorCollector(
        CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7())
    )
    collector.run()

    run = ZizmorRun.objects.order_by("-started_at").first()
    assert run is not None, "the collector completed without landing a run node"
    return Collected(run=run, workflows=workflows)


def test_every_corpus_workflow_produces_the_audit_zizmor_named_it_for(collected: Collected) -> None:
    """The scanner still finds what its own corpus says it finds.

    Reported in one assertion rather than per file so a version bump shows the whole delta at once —
    "three audits stopped firing" is a different conversation from "one did".
    """
    missing = {
        filename: sorted({f.audit_id for f in collected.findings_for(filename)})
        for filename, audit_id in EXPECTED_AUDIT_BY_FILE.items()
        if audit_id not in {f.audit_id for f in collected.findings_for(filename)}
    }

    assert not missing, f"corpus files whose named audit did not fire (showing what did): {missing}"


def test_the_four_coverage_states_stay_distinguishable(collected: Collected) -> None:
    """Scanned-and-clean, could-not-parse, nothing-to-scan — and never a silent gap.

    This is the assertion the whole design exists for: if these three collapsed into each other, a
    findings page would render "we never looked" as "nothing wrong".
    """
    clean = collected.coverage_for(CLEAN_FILE)
    assert collected.findings_for(CLEAN_FILE) == [], "upstream's known-good workflow produced findings"
    assert clean["outcome"] == "evaluated"

    invalid = collected.coverage_for(INVALID_FILE)
    assert invalid["outcome"] == "parse-failed"
    assert invalid.get("reason"), "an unexplained non-evaluated outcome is exactly the silent gap"

    no_yaml = collected.coverage_for(NO_YAML_PATH)
    assert no_yaml["outcome"] == "no-yaml"
    assert no_yaml.get("reason")

    for key, workflow in collected.workflows.items():
        edges = Edge.objects.filter(
            from_entity_id=collected.run.entity_id, to_entity_id=workflow, edge_type=EDGE_SCANNED_WORKFLOW
        ).count()
        assert edges == 1, f"{key} carries {edges} coverage edges, expected exactly 1"


def test_the_run_accounts_for_everything_it_produced(collected: Collected) -> None:
    """Counts equal findings (req-zizmor-run-2), and no finding escapes the recorded audit set."""
    produced_ids = set(
        Edge.objects.filter(from_entity_id=collected.run.entity_id, edge_type=EDGE_PRODUCED_FINDING).values_list(
            "to_entity_id", flat=True
        )
    )

    assert sum(collected.run.counts_by_audit.values()) == len(produced_ids)
    assert sum(collected.run.counts_by_severity.values()) == len(produced_ids)

    # The audit inventory is derived from the binary's own diagnostics; an empty set would mean the
    # run cannot say what it ran, and every "clean" it reports would be unfalsifiable.
    assert len(collected.run.audit_set) > 20
    assert "impostor-commit" in collected.run.skipped_audits, "the offline-unavailable audits must be named"
    assert set(collected.run.skipped_audits).isdisjoint(collected.run.audit_set)

    outside = {f.audit_id for f in ZizmorFinding.objects.filter(entity_id__in=produced_ids)} - set(
        collected.run.audit_set
    )
    assert not outside, f"findings name audits the run did not report running: {sorted(outside)}"
