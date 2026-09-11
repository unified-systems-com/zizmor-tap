"""zizmor-about — what this scanner is, and what it did NOT look at.

Spec: specs/spec-zizmor-v0.md (req-zizmor-panel-about).

Every fact here is read from the latest `zizmor__run` node. The panel never invokes the binary:
the version, persona and audit inventory are properties of a RUN — of one execution, at one pin, at
one moment — and asking the binary now would report today's installed version against findings that
some other version produced. The collector reads it once at run start and records it; this reads
what was recorded.

The audits zizmor could not run offline are NOT here: they moved to the coverage panel, which is
where "unknown, not zero" is already argued for workflows. An audit that could not run and a
workflow that was never read are the same claim about the same run, and splitting them put half
the story above the findings table and half below it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from tap_plugin.zizmor.models.run import ZizmorRun

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel


class ZizmorAboutPanelType:
    slug: ClassVar[str] = "zizmor-about"
    label: ClassVar[str] = "About zizmor"
    view: ClassVar[str] = "zizmor/panels/about.html"
    css: ClassVar[list[str]] = ["zizmor/css/panels.css"]
    js: ClassVar[list[str]] = []
    editor_view: ClassVar[str] = ""
    config_defaults: ClassVar[dict[str, Any]] = {}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        run = ZizmorRun.objects.order_by("-started_at").first()
        if run is None:
            # Not an error state: a grid where the collector has never run is a legitimate,
            # readable condition, and saying so beats an empty panel that looks broken.
            return {"run": None, "audits_ran": 0, "skipped_count": 0}

        return {
            "run": run,
            "audits_ran": len(run.audit_set or []),
            "skipped_count": len(run.skipped_audits or []),
            "audit_set": sorted(run.audit_set or []),
        }
