"""zizmor-about — what this scanner is, and what it did NOT look at.

Spec: specs/spec-zizmor-v0.md (req-zizmor-panel-about).

Every fact here is read from the latest `zizmor__run` node. The panel never invokes the binary:
the version, persona and audit inventory are properties of a RUN — of one execution, at one pin, at
one moment — and asking the binary now would report today's installed version against findings that
some other version produced. The collector reads it once at run start and records it; this reads
what was recorded.

The five audits zizmor cannot run offline are shown with the reason the binary itself gave, because
"36 audits ran" alone invites the reading that the other five found nothing.
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
            return {"run": None, "audits_ran": 0, "skipped": []}

        # `tags.skipped_audit_reasons` carries the binary's own words per audit; fall back to the
        # bare list when an older run predates the tag rather than dropping the audits entirely.
        reasons: dict[str, str] = (run.tags or {}).get("skipped_audit_reasons") or {}
        skipped = [
            {"audit_id": audit, "reason": reasons.get(audit, "not available offline")}
            for audit in sorted(run.skipped_audits or [])
        ]
        return {
            "run": run,
            "audits_ran": len(run.audit_set or []),
            "skipped": skipped,
            "audit_set": sorted(run.audit_set or []),
        }
