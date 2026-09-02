"""Behavioural tests for the finding and run models (req-zizmor-finding, req-zizmor-run).

Service-layer setup throughout; the ORM is reached only to read back projections.
"""

from __future__ import annotations

import pytest
from django.utils import timezone
from tap_plugin.zizmor.models import ZizmorFinding

from tap_grid.models import Entity
from tap_grid.services import create_node

FINDING = "zizmor__finding"
RUN = "zizmor__run"


def _finding_payload(**overrides):
    payload = {
        "audit_id": "template-injection",
        "audit_url": "https://docs.zizmor.sh/audits/#template-injection",
        "severity": "High",
        "confidence": "High",
        "persona": "Auditor",
        "scanner_version": "1.30.0",
        "summary": "code injection via template expansion",
        "location": {
            "path": ".github/workflows/plugin-ci.yml",
            "route": "jobs/conformance/steps/3",
            "job_key": "conformance",
            "step_index": 3,
            "row": 123,
            "column": 8,
            "feature": "run: ... ${{ inputs.plugin_subdir }}",
            "annotation": "this step",
        },
        "fixes": [{"title": "move the expression into env", "disposition": "safe"}],
        "raw": {"ident": "template-injection"},
        "tags": {},
        "observed_at": timezone.now().isoformat(),
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestZizmorFinding:
    def test_create_via_service_layer_projects_name_and_dimensions(self) -> None:
        result = create_node(FINDING, _finding_payload())
        assert result.success, result.errors
        entity = Entity.objects.get(id=result.entity_id)
        assert entity.name == "template-injection @ .github/workflows/plugin-ci.yml#conformance"
        for key, value in {
            "github.platform": "github.com",
            "github.surface": "actions",
            "github.observation": "declaration",
        }.items():
            assert entity.dimensions.get(key) == value

    def test_required_fields_are_enforced(self) -> None:
        payload = _finding_payload()
        del payload["audit_id"]
        result = create_node(FINDING, payload)
        assert not result.success
        assert any(e.code == "validation_error" for e in result.errors)

    def test_severity_enum_rejects_unknown_value(self) -> None:
        result = create_node(FINDING, _finding_payload(severity="Catastrophic"))
        assert not result.success

    def test_fix_disposition_is_constrained(self) -> None:
        result = create_node(FINDING, _finding_payload(fixes=[{"title": "x", "disposition": "maybe"}]))
        assert not result.success

    def test_location_and_fixes_require_their_core_fields(self) -> None:
        assert not create_node(FINDING, _finding_payload(location={})).success
        assert not create_node(FINDING, _finding_payload(fixes=[{}])).success

    def test_name_resyncs_on_save(self) -> None:
        result = create_node(FINDING, _finding_payload())
        assert result.success
        node = ZizmorFinding.objects.get(entity_id=result.entity_id)
        node.audit_id = "unpinned-uses"
        node.save()
        entity = Entity.objects.get(id=result.entity_id)
        assert entity.name.startswith("unpinned-uses @ ")


@pytest.mark.django_db
class TestZizmorRun:
    def test_create_via_service_layer_projects_name(self) -> None:
        result = create_node(
            RUN,
            {
                "scanner_version": "1.30.0",
                "persona": "Auditor",
                "audit_set": ["template-injection", "unpinned-uses"],
                "skipped_audits": ["impostor-commit", "known-vulnerable-actions", "ref-confusion", "typosquat-uses"],
                "outcome": "ok",
                "source_collection_job": "01a062f9-c662-7759-a7b0-bc0bdc2a2dd3",
                "started_at": "2026-09-02T21:40:00Z",
                "finished_at": "2026-09-02T21:40:01Z",
                "repositories_scanned": 17,
                "workflows_evaluated": 50,
                "workflows_no_yaml": 39,
                "counts_by_severity": {"High": 34, "Medium": 11, "Low": 58, "Informational": 22},
            },
        )
        assert result.success, result.errors
        entity = Entity.objects.get(id=result.entity_id)
        assert entity.name == "zizmor 1.30.0 (auditor) 2026-09-02 21:40"
        assert entity.dimensions.get("github.observation") == "declaration"

    def test_completed_outcome_requires_evidence_of_a_scan(self) -> None:
        """An `ok` run with no source, no audit set and no coverage is a lie the model refuses."""
        empty_ok = create_node(RUN, {"scanner_version": "1.30.0", "persona": "Auditor", "outcome": "ok"})
        assert not empty_ok.success
        no_source = create_node(
            RUN,
            {
                "scanner_version": "1.30.0",
                "persona": "Auditor",
                "outcome": "ok",
                "audit_set": ["unpinned-uses"],
                "started_at": "2026-09-02T21:40:00Z",
                "finished_at": "2026-09-02T21:40:01Z",
                "workflows_evaluated": 1,
            },
        )
        assert not no_source.success
        negative_count_value = create_node(
            RUN,
            {"scanner_version": "1.30.0", "persona": "Auditor", "counts_by_severity": {"High": -1}},
        )
        assert not negative_count_value.success

    def test_outcome_enum_and_non_negative_counts(self) -> None:
        bad_outcome = create_node(RUN, {"scanner_version": "1.30.0", "persona": "Auditor", "outcome": "green"})
        assert not bad_outcome.success
        negative = create_node(RUN, {"scanner_version": "1.30.0", "persona": "Auditor", "workflows_evaluated": -1})
        assert not negative.success
