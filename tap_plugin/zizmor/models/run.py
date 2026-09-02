"""zizmor run — one execution of the collector, and the thing that makes absence honest.

A workflow with no `SCANNED` edge from the current run renders as *not observed by this scanner*
in every consumer; the run records what it scanned and with what outcome, which github_core
collection it read, and the counts its findings must add up to (req-zizmor-run).
"""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

from tap_plugin.zizmor.models.finding import PERSONAS

OUTCOMES: tuple[str, ...] = ("running", "ok", "partial", "failed", "skipped")


class ZizmorRun(BaseModel):
    """One collector execution: version, persona, source collection, coverage, counts.

    Spec: specs/spec-zizmor-v0.md (req-zizmor-run)
    """

    ENTITY_TYPE: ClassVar[str] = "zizmor__run"
    ENTITY_NAME: ClassVar[str] = "zizmor Run"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "One execution of the zizmor collector: the scanner version and persona it ran with, the "
        "github_core collection it read, which workflows it evaluated (and which it could not), and "
        "the finding counts its PRODUCED edges must add up to."
    )
    ENTITY_ICON: ClassVar[str] = "zizmor-run"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {
        "github.platform": "github.com",
        "github.surface": "actions",
        "github.observation": "declaration",
    }
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "round-rectangle",
            "colors": {"fill": "#FFFFFF", "border": "#6E7781", "label": "#1F2328"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "scanner_version": {"type": "string", "minLength": 1},
        "persona": {"type": "string", "enum": list(PERSONAS)},
        "audit_set": {"type": "array", "items": {"type": "string"}},
        "skipped_audits": {"type": "array", "items": {"type": "string"}},
        "outcome": {"type": "string", "enum": list(OUTCOMES)},
        "source_collection_job": {"type": ["string", "null"]},
        "started_at": {"type": ["string", "null"]},
        "finished_at": {"type": ["string", "null"]},
        "repositories_scanned": {"type": "integer", "minimum": 0},
        "workflows_evaluated": {"type": "integer", "minimum": 0},
        "workflows_parse_failed": {"type": "integer", "minimum": 0},
        "workflows_skipped": {"type": "integer", "minimum": 0},
        "workflows_no_yaml": {"type": "integer", "minimum": 0},
        "counts_by_audit": {"type": "object"},
        "counts_by_severity": {"type": "object"},
        "tags": {"type": "object"},
    }
    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "scanner_version": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "persona": {"validation": "jsonschema", "schema": {"type": "string", "enum": list(PERSONAS)}},
        "audit_set": {"validation": "jsonschema", "schema": {"type": "array", "items": {"type": "string"}}},
        "skipped_audits": {"validation": "jsonschema", "schema": {"type": "array", "items": {"type": "string"}}},
        "outcome": {"validation": "jsonschema", "schema": {"type": "string", "enum": list(OUTCOMES)}},
        "source_collection_job": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "repositories_scanned": {"validation": "jsonschema", "schema": {"type": "integer", "minimum": 0}},
        "workflows_evaluated": {"validation": "jsonschema", "schema": {"type": "integer", "minimum": 0}},
        "workflows_parse_failed": {"validation": "jsonschema", "schema": {"type": "integer", "minimum": 0}},
        "workflows_skipped": {"validation": "jsonschema", "schema": {"type": "integer", "minimum": 0}},
        "workflows_no_yaml": {"validation": "jsonschema", "schema": {"type": "integer", "minimum": 0}},
        "counts_by_audit": {"validation": "jsonschema", "schema": {"type": "object"}},
        "counts_by_severity": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
        # Datetime fields are typed Django DateTimeFields — their own validation applies.
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["scanner_version", "persona"]

    scanner_version = models.CharField(max_length=64, blank=True, default="", db_index=True)
    persona = models.CharField(max_length=16, blank=True, default="Auditor")
    audit_set = models.JSONField(default=list, blank=True)
    # The four audits zizmor cannot run offline, recorded as skipped on every v0 run.
    skipped_audits = models.JSONField(default=list, blank=True)
    outcome = models.CharField(max_length=16, blank=True, default="running", db_index=True)
    # The github_core collection job (entity id) whose rows this run read — provenance, not timing.
    source_collection_job = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    repositories_scanned = models.IntegerField(default=0)
    workflows_evaluated = models.IntegerField(default=0)
    workflows_parse_failed = models.IntegerField(default=0)
    workflows_skipped = models.IntegerField(default=0)
    # First light (2026-09-02): 39 of 89 collected workflows carried no raw_yaml. Those are the
    # not-observed rows the spec insists on, and they get their own count rather than folding into
    # "skipped".
    workflows_no_yaml = models.IntegerField(default=0)
    counts_by_audit = models.JSONField(default=dict, blank=True)
    counts_by_severity = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "zizmor__run"

    def get_name(self) -> str:
        when = self.started_at.strftime("%Y-%m-%d %H:%M") if self.started_at else "unstarted"
        return f"zizmor {self.scanner_version} ({self.persona.lower()}) {when}".strip()

    def __str__(self) -> str:
        return self.get_name()
