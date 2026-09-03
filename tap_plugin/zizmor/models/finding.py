"""zizmor finding — one audit result, with its provenance, attached to the workflow it flags.

A compliance-level node in disguise (George, 2026-09-02): a scanner's assertion about an asset is
the same shape compliance_core's `finding` bridges to a requirement. For the make-it-work phase it
is a scanner-shaped node; surfacing it beside other findings (poutine, CodeQL, git-serious's
conjunction findings, compliance findings) is an open design that `req-zizmor-compliance-bridge`
and `req-zizmor-second-scanner` will force. Field names are scanner-neutral wherever a neutral name
exists (`severity`, `confidence`, `scanner_version`, `location`, `fixes`); `audit_id` is zizmor's
vocabulary and becomes the neutral `rule_id` the day a second scanner lands.
"""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

SEVERITIES: tuple[str, ...] = ("Unknown", "Informational", "Low", "Medium", "High")
CONFIDENCES: tuple[str, ...] = ("Unknown", "Low", "Medium", "High")
PERSONAS: tuple[str, ...] = ("Regular", "Pedantic", "Auditor")

# What zizmor reports per location (json-v1): the symbolic route into the YAML (`jobs/build/steps/2`),
# the concrete start/end row+column, the `feature` text at the site, and the annotation. Job key and
# step index are lifted out of the route so a consumer can resolve the `workflow_job` without
# re-parsing the route (req-zizmor-finding).
_LOCATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Workflow file path inside the repository (.github/workflows/…)."},
        "route": {"type": "string", "description": "zizmor's symbolic route into the YAML, joined with '/'."},
        "job_key": {"type": ["string", "null"], "description": "The YAML job key the route passes through, if any."},
        "step_index": {
            "type": ["integer", "null"],
            "description": "The step index under that job, if the route names one.",
        },
        "row": {"type": ["integer", "null"], "description": "0-based start row (zizmor json-v1 numbering)."},
        "column": {"type": ["integer", "null"], "description": "0-based start column."},
        "end_row": {"type": ["integer", "null"]},
        "end_column": {"type": ["integer", "null"]},
        "feature": {"type": ["string", "null"], "description": "The source text at the site, as zizmor reported it."},
        "annotation": {"type": ["string", "null"], "description": "zizmor's annotation for the location."},
    },
    # A location that names no file and no route is not a location; the rest may legitimately be
    # absent (zizmor reports some findings at the workflow level with no row/column).
    "required": ["path", "route"],
    "additionalProperties": True,
}

_FIXES_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "disposition": {"type": "string", "enum": ["safe", "unsafe"]},
        },
        "required": ["title", "disposition"],
        "additionalProperties": True,
    },
}


class ZizmorFinding(BaseModel):
    """One zizmor audit result on one workflow, with the provenance that makes it data.

    Spec: specs/spec-zizmor-v0.md (req-zizmor-finding)
    """

    ENTITY_TYPE: ClassVar[str] = "zizmor__finding"
    ENTITY_NAME: ClassVar[str] = "zizmor Finding"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "One audit result from zizmor on one workflow file: the audit, its severity and confidence, "
        "the location it reported, and the fixes it offers. Provenance (scanner version, persona, run) "
        "rides every finding."
    )
    ENTITY_ICON: ClassVar[str] = "zizmor-finding"
    # Repository scope (`github.owner` / `github.repo`) and `zizmor.scanner_version` are set by the
    # collector per node — they vary per finding — so only the static part lives here.
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {
        "github.platform": "github.com",
        "github.surface": "actions",
        "github.observation": "declaration",
    }
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "diamond",
            "colors": {"fill": "#FFFFFF", "border": "#CF222E", "label": "#1F2328"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "audit_id": {"type": "string", "minLength": 1},
        "audit_url": {"type": "string"},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "confidence": {"type": "string", "enum": list(CONFIDENCES)},
        "persona": {"type": "string", "enum": list(PERSONAS)},
        "scanner_version": {"type": "string", "minLength": 1},
        "summary": {"type": "string"},
        "location": _LOCATION_SCHEMA,
        "fixes": _FIXES_SCHEMA,
        "raw": {"type": "object"},
        "tags": {"type": "object"},
        "known_since": {"type": ["string", "null"]},
        "observed_at": {"type": ["string", "null"]},
    }
    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "audit_id": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "audit_url": {"validation": "jsonschema", "schema": {"type": "string"}},
        "severity": {"validation": "jsonschema", "schema": {"type": "string", "enum": list(SEVERITIES)}},
        "confidence": {"validation": "jsonschema", "schema": {"type": "string", "enum": list(CONFIDENCES)}},
        "persona": {"validation": "jsonschema", "schema": {"type": "string", "enum": list(PERSONAS)}},
        "scanner_version": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "summary": {"validation": "jsonschema", "schema": {"type": "string"}},
        "location": {"validation": "jsonschema", "schema": _LOCATION_SCHEMA},
        "fixes": {"validation": "jsonschema", "schema": _FIXES_SCHEMA},
        "raw": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
        # Datetime fields are typed Django DateTimeFields — their own validation applies.
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["audit_id", "severity", "confidence", "scanner_version"]

    audit_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    audit_url = models.CharField(max_length=512, blank=True, default="")
    severity = models.CharField(max_length=16, blank=True, default="Unknown", db_index=True)
    confidence = models.CharField(max_length=16, blank=True, default="Unknown", db_index=True)
    persona = models.CharField(max_length=16, blank=True, default="Regular")
    scanner_version = models.CharField(max_length=64, blank=True, default="", db_index=True)
    summary = models.TextField(blank=True, default="")
    location = models.JSONField(default=dict, blank=True)
    fixes = models.JSONField(default=list, blank=True)
    # zizmor's raw json-v1 finding, verbatim — the scanner's assertion, never rewritten.
    raw = models.JSONField(default=dict, blank=True)
    # Data-carried facts that have no node yet: an unresolved job key, the `uses:` string, secret
    # names — the honest home until `github_action` / `actions_secret` exist (spec: endpoints table).
    tags = models.JSONField(default=dict, blank=True)
    known_since = models.DateTimeField(null=True, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta(BaseModel.Meta):
        db_table = "zizmor__finding"

    def get_name(self) -> str:
        loc = self.location or {}
        where = loc.get("path") or ""
        job = loc.get("job_key")
        if job:
            where = f"{where}#{job}"
        return f"{self.audit_id} @ {where}".strip(" @") if (self.audit_id or where) else ""

    def __str__(self) -> str:
        return self.get_name()
