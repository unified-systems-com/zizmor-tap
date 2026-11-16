"""Every dimension key this plugin writes has a declared Dimension node (unified-systems-com/tap#711).

Dimension nodes are declared, never minted on the fly: once the dimension map keys by node id, a key
with no node is refused. zizmor owns one key, ``zizmor.scanner_version``, and declares it in its own
seed under a pinned id, because the map stores that id and a regenerated one would orphan every row
carrying the old one. Every other key it writes belongs to a plugin it depends on: a finding is
scoped exactly as the workflow it flags (req-zizmor-finding), so it carries github_core's keys and
git_core's ``git.host``.

The written keys are read from the plugin's own source: every dotted string key of a dict literal
outside the tests and migrations, plus every edge definition's ``default_dimensions``. A new key
with no node, here or in an owner's seed, fails this test.
"""

import ast
import importlib
import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

PACKAGE = Path(__file__).resolve().parent.parent
SEED = PACKAGE / "grift" / "dimension.grift.json"
PINNED = {"zizmor.scanner_version": "01a1e560-f815-76de-91c6-a31f72d40ead"}
# Keys this plugin writes but does not own: the Dimension node ships with the owning plugin.
FOREIGN = {
    "git.host": ("git_core", "01a1d10a-eb22-7742-a0c1-5988c9d08db4"),
    "github.observation": ("github_core", "01a1d10a-e9e7-71e3-bda0-59f5841ece12"),
    "github.surface": ("github_core", "01a1d10a-e9e7-71e3-bda0-59f6cc777266"),
    "github.owner": ("github_core", "01a1e4f0-dcff-735e-a647-6b9f901912f4"),
    "github.repo": ("github_core", "01a1e4f0-dd43-7768-96c4-7ab130e2dfe1"),
}
# Retired on 2026-09-20 in favour of git.host (github-core-tap#168); migration 0002 renames it on old rows.
RETIRED = "github.platform"


def _dimension_nodes() -> list[dict]:
    doc = json.loads(SEED.read_text(encoding="utf-8"))
    return [n for batch in doc["batches"] for n in batch["nodes"] if n["entity"]["entity_type"] == "dimension"]


def _written_keys() -> set[str]:
    keys: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Dict):
                keys |= {
                    k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str) and "." in k.value
                }
    for edge in PACKAGE.rglob("*.edge.json"):
        keys |= set(json.loads(edge.read_text(encoding="utf-8")).get("default_dimensions") or {})
    return keys


def test_every_written_key_has_a_declared_owner() -> None:
    written = _written_keys()
    assert set(PINNED) <= written and "git.host" in written, "the scan no longer sees the keys the collector stamps"
    unowned = written - set(PINNED) - set(FOREIGN)
    assert not unowned, f"dimension keys with no Dimension node here or in a dependency's seed: {sorted(unowned)}"
    assert RETIRED not in written


def test_the_seed_ids_are_pinned_uuid7s() -> None:
    nodes = _dimension_nodes()
    assert {n["node"]["name"]: n["entity"]["entity_id"] for n in nodes} == PINNED
    for node in nodes:
        assert uuid.UUID(node["entity"]["entity_id"]).version == 7, node["entity"]["entity_id"]
        assert node["entity"]["name"] == node["node"]["name"]
        assert node["node"]["description"].strip(), node


def test_a_foreign_key_is_declared_by_its_owner() -> None:
    """The owner is a dependency, so its seed is read from the installed package. A node declared
    under a different id fails. An installed release of the owner that predates the node skips,
    naming the key: this plugin's CI record pins released owners, and the pin moves once the
    owner's release exists."""
    behind: list[str] = []
    for key, (owner, node_id) in FOREIGN.items():
        spec = importlib.util.find_spec(f"tap_plugin.{owner}")
        assert spec is not None and spec.origin, f"{key}: owning plugin {owner} is not installed"
        seed = Path(spec.origin).parent / "grift" / "dimension.grift.json"
        owned: dict[str, str] = {}
        if seed.exists():
            doc = json.loads(seed.read_text(encoding="utf-8"))
            owned = {n["node"]["name"]: n["entity"]["entity_id"] for b in doc["batches"] for n in b["nodes"]}
        if key not in owned:
            behind.append(f"{key} ({owner})")
            continue
        assert owned[key] == node_id, f"{key}: {owner}'s seed has {owned[key]!r}, pinned {node_id}"
    if behind:
        pytest.skip(f"installed owners predate these Dimension nodes: {', '.join(behind)}")


def _legacy_row(entity_type: str, name: str, dimensions: dict[str, str]):
    """A spine row carrying a name-keyed dimensions map, as rows written before core's reshape do. The map is set
    with a queryset update: core main refuses a retired key on save, and an old row never went through that save."""
    from tap_grid.models import Entity

    row = Entity.objects.create(entity_type=entity_type, name=name)
    Entity.objects.filter(pk=row.pk).update(dimensions=dimensions)
    return row


@pytest.mark.django_db
@pytest.mark.spec("req-zizmor-finding-4")
def test_the_migration_renames_the_retired_key_on_zizmor_rows_only() -> None:
    from django.db import connection

    migration = importlib.import_module("tap_plugin.zizmor.migrations.0002_rename_github_platform_to_git_host")
    old = {RETIRED: "github.com", "github.surface": "actions"}
    ours = _legacy_row("zizmor__finding", "f", dict(old))
    both = _legacy_row("zizmor__run", "r", {RETIRED: "github.com", "git.host": "ghe.example"})
    theirs = _legacy_row("github_core__github_workflow", "w", dict(old))
    # An edge's spine row is entity_type "edge"; whose edge it is lives on tap_edge.edge_type.
    our_edge = _legacy_row("edge", "e1", dict(old))
    their_edge = _legacy_row("edge", "e2", dict(old))
    with connection.cursor() as cursor:
        for edge, edge_type in ((our_edge, "FLAGS_WORKFLOW__zizmor"), (their_edge, "DEFINES_JOB__github_core")):
            cursor.execute(
                "INSERT INTO tap_edge (batch_id, flip_map, edge_type, properties, entity_id, from_entity_id, to_entity_id)"
                " VALUES (%s, '{}', %s, '{}', %s, %s, %s)",
                ["test", edge_type, edge.pk, ours.pk, theirs.pk],
            )
    for _ in range(2):  # a second run changes nothing
        migration.rename_platform(None, SimpleNamespace(connection=connection))
    for row in (ours, both, theirs, our_edge, their_edge):
        row.refresh_from_db()
    new = {"git.host": "github.com", "github.surface": "actions"}
    assert ours.dimensions == new and our_edge.dimensions == new
    assert both.dimensions == {"git.host": "ghe.example"}, "a row that already carries git.host keeps that value"
    assert theirs.dimensions == old and their_edge.dimensions == old, "another plugin's rows are not zizmor's to change"
