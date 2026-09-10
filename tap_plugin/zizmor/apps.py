"""TAP zizmor plugin AppConfig.

``name`` is derived from this module's package path and ``label`` / ``verbose_name`` come
from tap-plugin.toml (slug / name) — nothing is authored here (req-tap-plugin-manifest-v0-scaffold).
Panel-type registration lands in ``ready()`` as those surfaces are built (req-zizmor-panel-*).
"""

from tap_plugins.base import TapPluginConfig


class ZizmorConfig(TapPluginConfig):
    def ready(self) -> None:
        # Base ready() loads tap-plugin.toml and registers the plugin's models/edges.
        super().ready()

        # Imported inside ready(), not at module top, so the app-loading graph stays light: the
        # collector pulls in github_core's models and the subprocess machinery, and none of that
        # is needed until a run is actually requested.
        from tap_plugin.zizmor.collectors.zizmor_collector.collector import ZizmorCollector

        from tap_cares.registry import register_collector

        register_collector(
            key="zizmor",
            # Stable scope (the plugin slug), never inferred from the module path: the derived
            # entity id is a durable grid key and a hardcoded edge target in schedule bundles, so
            # a package rename must not silently re-identify the collector
            # (req-tap-cares-collector-model-10).
            scope="zizmor",
            cls=ZizmorCollector,
            name="zizmor Collector",
            description=(
                "Audits the GitHub Actions workflow YAML already on the grid with the pinned "
                "zizmor binary, offline and with no credential, and lands one run plus its "
                "findings, their workflow/job/action attachments, and a SCANNED_WORKFLOW edge "
                "per workflow considered so that unevaluated is distinguishable from clean."
            ),
        )
