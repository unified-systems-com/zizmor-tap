"""TAP zizmor plugin AppConfig.

``name`` is derived from this module's package path and ``label`` / ``verbose_name`` come
from tap-plugin.toml (slug / name) — nothing is authored here (req-tap-plugin-manifest-v0-scaffold).
Collector and panel-type registration land in ``ready()`` as those surfaces are built
(req-zizmor-collector, req-zizmor-panel-*).
"""

from tap_plugins.base import TapPluginConfig


class ZizmorConfig(TapPluginConfig):
    pass
