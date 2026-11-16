"""Rename the ``github.platform`` dimension key to ``git.host`` on zizmor's existing rows (George, 2026-11-16).

github_core replaced ``github.platform`` with git_core's ``git.host`` on 2026-09-20 (github-core-tap#168), and this
plugin kept writing the old key. Its spec says a finding is scoped exactly as the workflow it flags, and a workflow
carries ``git.host``, so the old key was one fact under a second spelling. The value does not change
(``github.com``); only the key does.

Why this touches the spine table: dimensions live on ``tap_entity.dimensions``, not on zizmor's typed tables. The
statement is limited to zizmor's own rows (node rows whose ``entity_type`` starts ``zizmor__``, and edge rows, whose
spine ``entity_type`` is ``edge``, whose ``tap_edge.edge_type`` ends ``__zizmor``) and to rows that carry the old key.
It moves only that key's value and leaves every other dimension as it was. A row that already carries ``git.host`` keeps that value. Run twice, it
changes nothing the second time. It runs on the name-keyed map, before core's dimension-map reshape
(unified-systems-com/tap#711), which stops on ``github.platform`` because no seed declares it; on a map already keyed
by node id it matches no row.

Upgrade order: install and migrate this zizmor release while the grid is still on a core that predates the reshape,
then upgrade core. That is the order core's own migration states for plugin key changes ("plugin releases first"). It
is not encoded as ``run_before`` on core's migration, on purpose: that would make this migration a dependency of one
that grids already on the new core have applied, and Django refuses to migrate a database whose applied migration has
an unapplied dependency. On such a grid this migration finds nothing to do anyway.

Batch rows are not touched: the importer creates a batch's spine row without the batch envelope's dimensions, so no
batch row carries the key.

Reversing renames the key back on the same rows, so a rollback to migration 0001 leaves the rows as that code writes
and reads them.
"""

from django.db import migrations

OLD_KEY = "github.platform"
NEW_KEY = "git.host"

#: zizmor's own node types share this prefix; its edge types end in this suffix (the edge's spine row is
#: entity_type "edge", so edges are found through tap_edge).
NODE_PREFIX = "zizmor__"
EDGE_SUFFIX = "__zizmor"

# A constant statement; every value is a bound parameter.
RENAME = """
UPDATE tap_entity AS e
   SET dimensions = (e.dimensions - %(old)s)
       || CASE WHEN e.dimensions ? %(new)s THEN '{}'::jsonb ELSE jsonb_build_object(%(new)s, e.dimensions -> %(old)s) END
 WHERE e.dimensions ? %(old)s
   AND (
        starts_with(e.entity_type, %(prefix)s)
     OR (e.entity_type = 'edge'
         AND EXISTS (SELECT 1 FROM tap_edge AS g
                      WHERE g.entity_id = e.id AND right(g.edge_type, %(suffix_len)s) = %(suffix)s))
   )
"""


def _rename(schema_editor, old: str, new: str) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            RENAME,
            {"old": old, "new": new, "prefix": NODE_PREFIX, "suffix_len": len(EDGE_SUFFIX), "suffix": EDGE_SUFFIX},
        )


def rename_platform(apps, schema_editor):
    _rename(schema_editor, OLD_KEY, NEW_KEY)


def restore_platform(apps, schema_editor):
    """The reverse: zizmor's rows carry ``github.platform`` again, as the code at migration 0001 writes and reads it."""
    _rename(schema_editor, NEW_KEY, OLD_KEY)


class Migration(migrations.Migration):
    dependencies = [
        ("zizmor", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(rename_platform, restore_platform),
    ]
