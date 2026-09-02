"""Plugin validation-system tests (new-plugin skill, Step 9): structure and strict levels.

`loads` / `runs` levels need an installed, booted plugin; structure-level works standalone.
"""

from pathlib import Path

from tap_plugins.validate.service import validate_plugin

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


class TestStructure:
    def test_structure_passes(self) -> None:
        result = validate_plugin(PLUGIN_ROOT, level="structure")
        if not result.ok:
            raise AssertionError(result.to_human())

    def test_strict_passes(self) -> None:
        result = validate_plugin(PLUGIN_ROOT, level="structure", strict=True)
        if not result.ok:
            raise AssertionError(result.to_human())
