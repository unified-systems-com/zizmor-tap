"""ZizmorCollector — audit the workflow YAML already on the grid, offline, and land the findings.

Spec: specs/spec-zizmor-v0.md (req-zizmor-collector, req-zizmor-binary-2, req-zizmor-finding,
req-zizmor-run). Registered as `zizmor:zizmor`.

This collector fetches nothing. Its input is `GithubWorkflow.configuration["raw_yaml"]`, which
github_core already collected, so a run is a pure function of grid state plus a pinned binary:
same rows in, same findings out. It declares no `required_secrets` and hands the scanner an
environment with no GitHub token in it, so "offline" is enforced rather than intended.

**Endpoints are read off the spine, never re-minted.** Every node this collector attaches to —
the workflow, the job, the action — is already on the grid, and its entity id is on the row
(`.entity_id`). Re-deriving those ids from github_core's uuid5 recipe would be the same fact
computed twice, and the copy would be wrong the day that recipe changed. Reading the row also
makes the existence check free: if the query returns nothing there is no endpoint, and the
collector records why instead of minting a node that matches nothing.

**Absence is carried in three states, not two.** A workflow that was not evaluated is not a
workflow that was clean. Every workflow the run considered gets a `SCANNED_WORKFLOW__zizmor` edge
carrying its outcome (`evaluated` / `parse-failed` / `skipped` / `no-yaml`), and each non-evaluated
outcome carries the reason. A workflow with no such edge was not observed by this scanner at all.
The `no-yaml` case is the common one on a real grid (*observed* 2026-09-10: 40 of 117), and it is
the one most likely to be misread as a clean result.
"""

from __future__ import annotations

import shutil
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from django.db.models import Q
from tap_plugin.github_core.models.github_action import GithubAction
from tap_plugin.github_core.models.github_workflow import GithubWorkflow
from tap_plugin.github_core.models.workflow_job import WorkflowJob
from tap_plugin.zizmor.collectors.zizmor_collector import batch as batch_mod
from tap_plugin.zizmor.collectors.zizmor_collector import binary as binary_mod
from tap_plugin.zizmor.collectors.zizmor_collector import identity, scratch
from tap_plugin.zizmor.collectors.zizmor_collector.decompose import DecomposedFinding, decompose
from tap_plugin.zizmor.collectors.zizmor_collector.errors import ZizmorCollectorError
from tap_plugin.zizmor.models.finding import ZizmorFinding

from tap_cares.collectors.base import CollectorBase
from tap_cares.models import CollectionJob, CollectionJobStatus

# record_* call-site tokens (minted via scripts/log-site-id; unique within this file).
_SITE_RUN_STARTED = "55c2"
_SITE_BINARY_ABORT = "a65a"
_SITE_NO_SOURCE = "1c35"
_SITE_NO_WORKFLOWS = "3a24"
_SITE_PATH_REFUSED = "ec89"
_SITE_MATERIALIZE_FAILED = "5738"
_SITE_PARSE_FAILED = "5a24"
_SITE_JOB_UNRESOLVED = "62d6"
_SITE_ACTION_UNRESOLVED = "5c3d"
_SITE_ID_COLLISION = "9ef0"
_SITE_AUDIT_SET_EMPTY = "4e3a"
_SITE_COUNTS_MISMATCH = "2461"
_SITE_SCRATCH_RESIDUE = "6f09"
_SITE_RUN_FINISHED = "f9da"
_SITE_NO_WORKFLOW_ENDPOINT = "807b"
_SITE_UPSTREAM_ACTIVE = "a22a"
_SITE_UPSTREAM_RACED = "888d"

EDGE_PRODUCED_FINDING = "PRODUCED_FINDING__zizmor"
EDGE_SCANNED_WORKFLOW = "SCANNED_WORKFLOW__zizmor"
EDGE_FLAGS_WORKFLOW = "FLAGS_WORKFLOW__zizmor"
EDGE_FLAGS_JOB = "FLAGS_JOB__zizmor"
EDGE_FLAGS_ACTION = "FLAGS_ACTION__zizmor"

_EDGE_DIMENSIONS = {
    "github.platform": "github.com",
    "github.surface": "actions",
    "github.observation": "declaration",
}

# The collector whose rows this one reads. Its most recent successful job is the provenance a run
# records (req-zizmor-trigger-4).
_UPSTREAM_COLLECTOR_KEY = "github_core:github_core"


class ZizmorCollector(CollectorBase):
    """Read the grid's workflow YAML, run the pinned scanner offline, land one GRIFT batch."""

    def _abort(self, site: str, code: str, message: str, **data: Any) -> None:
        self.record_error(site, code, message, message_data=data)
        raise ZizmorCollectorError(message)

    def run(self) -> None:
        started_at = datetime.now(UTC)
        self.record_info(_SITE_RUN_STARTED, "RUN_STARTED", "Starting a zizmor audit of the workflows on this grid.")

        try:
            binary, version = binary_mod.verify_version()
        except binary_mod.ZizmorBinaryError as exc:
            self._abort(_SITE_BINARY_ABORT, "BINARY_VERSION_ABORT", str(exc))
            raise  # pragma: no cover — _abort always raises; keeps the type checker honest.

        # Staleness guard (req-zizmor-trigger-3). This collector runs on its OWN cadence, so a fire
        # can land in the middle of a github_core collection. Reading workflow rows mid-write would
        # produce a coverage number the run cannot stand behind: some repositories written, some
        # not, and nothing on the finished run to say which. Skip, name the job, and create NO run
        # node — deliberately not a run with `outcome="skipped"`, because a run node asserts a scan
        # happened and this one never started. That outcome exists for the different case of a run
        # that began and found nothing to do.
        active = self._active_upstream_job()
        if active is not None:
            self.summary = (
                f"Skipped: github_core collection job {active} is still running, and auditing rows "
                "mid-write would report coverage this run cannot stand behind."
            )
            self.record_info(
                _SITE_UPSTREAM_ACTIVE,
                "UPSTREAM_COLLECTION_ACTIVE",
                self.summary,
                message_data={"github_core_collection_job": active},
            )
            return

        source_job = self._latest_upstream_job()
        if source_job is None:
            self._abort(
                _SITE_NO_SOURCE,
                "NO_UPSTREAM_COLLECTION",
                "No successful github_core collection job exists on this grid, so there is no "
                "provenance for the workflow rows this run would read. A run that cannot name the "
                "collection it audited is a finding with no source; refusing to produce one.",
            )
            raise  # pragma: no cover

        workflows = list(GithubWorkflow.objects.all().order_by("full_name", "path", "workflow_id"))
        if not workflows:
            self._abort(
                _SITE_NO_WORKFLOWS,
                "NO_WORKFLOWS",
                "No github_core workflows are on this grid; there is nothing to audit.",
            )
            raise  # pragma: no cover

        run_uuid = identity.run_id(self.config.collection_job_entity_id)
        state = _RunState(run_uuid=run_uuid, scanner_version=version, started_at=started_at)

        scratch_root = Path(tempfile.mkdtemp(prefix="tap-zizmor-"))
        try:
            run_root = scratch_root / str(run_uuid)
            run_root.mkdir(parents=True)
            for workflow in workflows:
                self._process_workflow(workflow, binary=binary, run_root=run_root, state=state)
        finally:
            shutil.rmtree(scratch_root, ignore_errors=True)
            if scratch_root.exists():
                self.record_warn(
                    _SITE_SCRATCH_RESIDUE,
                    "SCRATCH_NOT_REMOVED",
                    "The per-run scratch tree could not be fully removed.",
                    message_data={"scratch_root": str(scratch_root)},
                )

        # Re-check before landing anything (closes the check/use race the first guard cannot).
        # The guard at the top of run() only proves no collection was in flight when we STARTED;
        # one can begin while we are reading rows, and the findings would then describe a grid
        # half-written. Discarding a completed scan is cheap — it costs one offline pass — and it is
        # the only way the coverage number this run publishes can be one it stands behind.
        raced = self._active_upstream_job()
        if raced is not None:
            self.summary = (
                f"Discarded: github_core collection job {raced} started while this audit was "
                "reading, so its coverage would describe a grid that was being rewritten underneath "
                "it. Nothing was landed."
            )
            self.record_info(
                _SITE_UPSTREAM_RACED,
                "UPSTREAM_COLLECTION_RACED",
                self.summary,
                message_data={"github_core_collection_job": raced, "findings_discarded": len(state.findings)},
            )
            return

        self._finalize(state, source_job=source_job)

    # ------------------------------------------------------------------
    # Per-workflow handling. Every path through here ends in exactly one
    # SCANNED_WORKFLOW edge, which is what makes coverage complete.
    # ------------------------------------------------------------------

    def _process_workflow(
        self,
        workflow: GithubWorkflow,
        *,
        binary: Path,
        run_root: Path,
        state: _RunState,
    ) -> None:
        workflow_endpoint = workflow.entity_id
        if workflow_endpoint is None:  # pragma: no cover — a BaseModel row always has a spine entity.
            self.record_warn(
                _SITE_NO_WORKFLOW_ENDPOINT,
                "WORKFLOW_NOT_ON_SPINE",
                "A workflow row carries no spine entity and cannot be attached to; not scanned.",
                message_data={"full_name": workflow.full_name, "path": workflow.path},
            )
            return

        state.repositories.add(workflow.full_name)
        raw_yaml = (workflow.configuration or {}).get("raw_yaml")

        if not raw_yaml:
            state.no_yaml += 1
            state.scanned[workflow_endpoint] = (
                "no-yaml",
                "github_core collected this workflow but captured no raw_yaml for it, so there was "
                "nothing for the scanner to read. This workflow's findings are UNKNOWN, not zero.",
            )
            return

        try:
            target = scratch.safe_target(run_root, full_name=workflow.full_name, path=workflow.path)
        except scratch.UnsafePathError as exc:
            state.skipped += 1
            state.scanned[workflow_endpoint] = ("skipped", f"refused before scanning: {exc}")
            self.record_warn(
                _SITE_PATH_REFUSED,
                "PATH_REFUSED",
                "A workflow row was refused by path sanitizing and not scanned.",
                message_data={"full_name": workflow.full_name, "path": workflow.path, "reason": str(exc)},
            )
            return

        try:
            scratch.materialize(target, raw_yaml)
        except OSError as exc:
            state.skipped += 1
            state.scanned[workflow_endpoint] = ("skipped", f"could not be written to the scratch tree: {exc}")
            self.record_warn(
                _SITE_MATERIALIZE_FAILED,
                "MATERIALIZE_FAILED",
                "A workflow could not be materialized into the scratch tree and was not scanned.",
                message_data={"full_name": workflow.full_name, "path": workflow.path, "error": str(exc)},
            )
            return

        result = binary_mod.scan(binary, target=target.file_path, cwd=run_root)
        state.audits_scheduled |= result.audits_scheduled
        state.audits_skipped.update(result.audits_skipped)

        if not result.ok:
            state.parse_failed += 1
            state.scanned[workflow_endpoint] = ("parse-failed", result.reason or "the scanner could not audit it.")
            self.record_warn(
                _SITE_PARSE_FAILED,
                "SCAN_FAILED",
                "The scanner could not audit a workflow; its findings are unknown, not zero.",
                message_data={"full_name": workflow.full_name, "path": workflow.path, "reason": result.reason},
            )
            return

        state.evaluated += 1
        state.scanned[workflow_endpoint] = ("evaluated", "")
        for raw_finding in result.findings:
            self._collect_finding(raw_finding, workflow=workflow, workflow_endpoint=workflow_endpoint, state=state)

    def _collect_finding(
        self,
        raw_finding: dict[str, Any],
        *,
        workflow: GithubWorkflow,
        workflow_endpoint: UUID,
        state: _RunState,
    ) -> None:
        finding = decompose(raw_finding, workflow_path=workflow.path)
        if not finding.audit_id:
            # Provenance-incomplete by req-zizmor-finding-1; a finding with no audit is not one.
            return

        route = finding.location.get("route") or ""
        occurrence = 0
        finding_uuid = identity.finding_id(
            full_name=workflow.full_name,
            workflow_id_int=workflow.workflow_id or 0,
            audit_id=finding.audit_id,
            route=route,
            persona=finding.persona,
            subfeature=finding.subfeature,
        )
        while finding_uuid in state.finding_ids:
            occurrence += 1
            finding_uuid = identity.finding_id(
                full_name=workflow.full_name,
                workflow_id_int=workflow.workflow_id or 0,
                audit_id=finding.audit_id,
                route=route,
                persona=finding.persona,
                subfeature=finding.subfeature,
                occurrence=occurrence,
            )
        if occurrence:
            # Expected, not exceptional: the same expression used twice in one `run:` block is two
            # real findings whose only remaining discriminator is their order in the file. Recorded
            # at info because it is ordinary input — warning on it every run would train a reader
            # to ignore the warn channel. The cost is bounded and worth naming: editing that block
            # re-identifies the later occurrences WITHIN it, so their `known_since` restarts.
            self.record_info(
                _SITE_ID_COLLISION,
                "FINDING_OCCURRENCE_SUFFIXED",
                "Two findings shared an audit, route, persona and fragment in one workflow; the "
                "later one was given an occurrence suffix so both land rather than one silently "
                "replacing the other.",
                message_data={
                    "full_name": workflow.full_name,
                    "path": workflow.path,
                    "audit_id": finding.audit_id,
                    "route": route,
                    "subfeature": finding.subfeature,
                    "occurrence": occurrence,
                },
            )
        state.finding_ids.add(finding_uuid)

        tags: dict[str, Any] = {"ignored_by_config": finding.ignored}
        job_endpoint = self._resolve_job(finding, workflow=workflow, tags=tags)
        action_endpoint = self._resolve_action(finding, workflow=workflow, tags=tags)

        state.findings.append(
            _PendingFinding(
                entity_id=finding_uuid,
                decomposed=finding,
                workflow=workflow,
                workflow_endpoint=workflow_endpoint,
                job_endpoint=job_endpoint,
                action_endpoint=action_endpoint,
                tags=tags,
            )
        )
        state.by_audit[finding.audit_id] += 1
        state.by_severity[finding.severity] += 1

    # ------------------------------------------------------------------
    # Endpoint resolution — look it up, or say why there is no edge.
    # ------------------------------------------------------------------

    def _resolve_job(
        self, finding: DecomposedFinding, *, workflow: GithubWorkflow, tags: dict[str, Any]
    ) -> UUID | None:
        """The declared job this finding sits in, when that job is on the grid.

        req-zizmor-finding-2: an unresolvable job gets NO edge and records why. A guessed job
        endpoint would read, on every page, exactly like an observed one.
        """
        if not finding.job_key:
            return None
        job = (
            WorkflowJob.objects.filter(full_name=workflow.full_name, job_key=finding.job_key)
            .filter(Q(workflow_id=workflow.workflow_id) | Q(workflow_id__isnull=True))
            .order_by("-workflow_id")
            .first()
        )
        if job is None or job.entity_id is None:
            tags["job_unresolved"] = (
                f"the finding's location names job {finding.job_key!r}, but no workflow_job for that key "
                f"is on the grid for {workflow.full_name} — no job edge was attached rather than a guessed one."
            )
            self.record_warn(
                _SITE_JOB_UNRESOLVED,
                "JOB_UNRESOLVED",
                "A finding named a job that is not on the grid; no FLAGS_JOB edge was attached.",
                message_data={
                    "full_name": workflow.full_name,
                    "path": workflow.path,
                    "job_key": finding.job_key,
                    "audit_id": finding.audit_id,
                },
            )
            return None
        return job.entity_id

    def _resolve_action(
        self, finding: DecomposedFinding, *, workflow: GithubWorkflow, tags: dict[str, Any]
    ) -> UUID | None:
        """The action this finding's site references, when it is on the grid.

        The `uses:` string is carried on the EDGE (ref included); the node is keyed on the path
        with the ref stripped, which is how github_core keys it — one `actions/checkout` for the
        whole grid.
        """
        if finding.uses_kind == "reusable-workflow":
            # Not an unresolved action — a different kind of thing entirely, which correctly has
            # no action node. Recorded so the absence reads as "not an action" rather than "an
            # action we could not find".
            tags["uses_reusable_workflow"] = finding.uses
            return None
        if not finding.action_path:
            if finding.uses:  # pragma: no cover — a parsed `uses` always yields a path or a kind.
                tags["action_unresolved"] = f"the reference {finding.uses!r} is not an `owner/repo@ref` action."
            return None
        action = GithubAction.objects.filter(action_path=finding.action_path).first()
        if action is None or action.entity_id is None:
            tags["action_unresolved"] = (
                f"the finding's site references {finding.uses!r}, but no github_action node for "
                f"{finding.action_path!r} is on the grid — no action edge was attached rather than "
                "a node that matches nothing."
            )
            self.record_warn(
                _SITE_ACTION_UNRESOLVED,
                "ACTION_UNRESOLVED",
                "A finding referenced an action that is not on the grid; no FLAGS_ACTION edge was attached.",
                message_data={
                    "full_name": workflow.full_name,
                    "action_path": finding.action_path,
                    "uses": finding.uses,
                    "audit_id": finding.audit_id,
                },
            )
            return None
        return action.entity_id

    # ------------------------------------------------------------------
    # Assembly, post-check, submission.
    # ------------------------------------------------------------------

    def _finalize(self, state: _RunState, *, source_job: str) -> None:
        finished_at = datetime.now(UTC)

        if not state.audits_scheduled:
            # Fail closed: an empty audit set means the binary's diagnostics did not parse, and a
            # run that cannot say which audits it ran cannot honestly say a workflow is clean.
            self._abort(
                _SITE_AUDIT_SET_EMPTY,
                "AUDIT_SET_UNOBSERVED",
                "The scanner reported no audits as scheduled, so this run cannot say which audits "
                "it ran. Its findings would be unaccompanied by their coverage; refusing to land them.",
                scanner_version=state.scanner_version,
            )

        # A run is `partial` when it failed to evaluate something it ATTEMPTED. `no-yaml` rows are
        # counted and carry their own SCANNED edge, but they are an upstream coverage gap rather
        # than a fault in this run, so they do not by themselves make the run partial.
        outcome = "partial" if (state.parse_failed or state.skipped) else "ok"

        known_since = self._existing_known_since(state.finding_ids)
        observed_at = state.started_at.isoformat().replace("+00:00", "Z")

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        # `name` is DERIVED by the model (`get_name()`), so it is not a stored field and must not
        # appear in the node payload — the entity envelope carries the display name.
        run_name = (
            f"zizmor {state.scanner_version} ({binary_mod.PERSONA}) " f"{state.started_at.strftime('%Y-%m-%d %H:%M')}"
        )
        run_fields: dict[str, Any] = {
            "scanner_version": state.scanner_version,
            "persona": binary_mod.PERSONA.capitalize(),
            "audit_set": sorted(state.audits_scheduled),
            "skipped_audits": sorted(state.audits_skipped),
            "outcome": outcome,
            "source_collection_job": source_job,
            "started_at": state.started_at.isoformat().replace("+00:00", "Z"),
            "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
            "repositories_scanned": len(state.repositories),
            "workflows_evaluated": state.evaluated,
            "workflows_parse_failed": state.parse_failed,
            "workflows_skipped": state.skipped,
            "workflows_no_yaml": state.no_yaml,
            "counts_by_audit": dict(sorted(state.by_audit.items())),
            "counts_by_severity": dict(sorted(state.by_severity.items())),
            "tags": {
                # Why each offline-unavailable audit did not run, in the binary's own words, so a
                # reader can tell "clean" from "never looked".
                "skipped_audit_reasons": dict(sorted(state.audits_skipped.items())),
                "audit_set_source": "derived from the scanner's own -vv diagnostics; zizmor publishes "
                "no audit inventory through a flag or through SARIF.",
            },
        }
        nodes.append(
            batch_mod.node_envelope(
                entity_id=state.run_uuid,
                entity_type="zizmor__run",
                name=run_name,
                dimensions={"zizmor.scanner_version": state.scanner_version},
                fields=run_fields,
            )
        )

        for pending in state.findings:
            nodes.append(self._finding_node(pending, state=state, observed_at=observed_at, known_since=known_since))
            edges.append(
                batch_mod.edge_envelope(
                    entity_id=identity.edge_id(EDGE_PRODUCED_FINDING, state.run_uuid, pending.entity_id),
                    edge_type=EDGE_PRODUCED_FINDING,
                    source_id=state.run_uuid,
                    target_id=pending.entity_id,
                    dimensions=_EDGE_DIMENSIONS,
                )
            )
            edges.append(
                batch_mod.edge_envelope(
                    entity_id=identity.edge_id(EDGE_FLAGS_WORKFLOW, pending.entity_id, pending.workflow_endpoint),
                    edge_type=EDGE_FLAGS_WORKFLOW,
                    source_id=pending.entity_id,
                    target_id=pending.workflow_endpoint,
                    dimensions=_EDGE_DIMENSIONS,
                )
            )
            if pending.job_endpoint is not None:
                edges.append(
                    batch_mod.edge_envelope(
                        entity_id=identity.edge_id(EDGE_FLAGS_JOB, pending.entity_id, pending.job_endpoint),
                        edge_type=EDGE_FLAGS_JOB,
                        source_id=pending.entity_id,
                        target_id=pending.job_endpoint,
                        dimensions=_EDGE_DIMENSIONS,
                    )
                )
            if pending.action_endpoint is not None and pending.decomposed.uses:
                edges.append(
                    batch_mod.edge_envelope(
                        entity_id=identity.edge_id(EDGE_FLAGS_ACTION, pending.entity_id, pending.action_endpoint),
                        edge_type=EDGE_FLAGS_ACTION,
                        source_id=pending.entity_id,
                        target_id=pending.action_endpoint,
                        dimensions=_EDGE_DIMENSIONS,
                        properties={"uses": pending.decomposed.uses},
                    )
                )

        for workflow_endpoint, (workflow_outcome, reason) in state.scanned.items():
            properties: dict[str, Any] = {"outcome": workflow_outcome}
            if workflow_outcome != "evaluated":
                properties["reason"] = reason
            edges.append(
                batch_mod.edge_envelope(
                    entity_id=identity.edge_id(EDGE_SCANNED_WORKFLOW, state.run_uuid, workflow_endpoint),
                    edge_type=EDGE_SCANNED_WORKFLOW,
                    source_id=state.run_uuid,
                    target_id=workflow_endpoint,
                    dimensions=_EDGE_DIMENSIONS,
                    properties=properties,
                )
            )

        self._post_check(state, edges=edges, run_fields=run_fields)

        document = batch_mod.assemble_batch(
            batch_name=f"zizmor audit {state.started_at.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            description=(
                f"zizmor {state.scanner_version} ({binary_mod.PERSONA}) audited "
                f"{state.evaluated} workflow(s) across {len(state.repositories)} repository(ies) "
                f"offline and produced {len(state.findings)} finding(s)."
            ),
            nodes=nodes,
            edges=edges,
            summary={
                "outcome": outcome,
                "scanner_version": state.scanner_version,
                "source_collection_job": source_job,
                "workflows_evaluated": state.evaluated,
                "workflows_parse_failed": state.parse_failed,
                "workflows_skipped": state.skipped,
                "workflows_no_yaml": state.no_yaml,
                "findings": len(state.findings),
            },
            batch_dimensions={"github.platform": "github.com", "zizmor.scanner_version": state.scanner_version},
        )
        self.submit_grift(document)

        self.summary = (
            f"zizmor {state.scanner_version}: {len(state.findings)} finding(s) from "
            f"{state.evaluated} evaluated workflow(s); {state.no_yaml} had no YAML, "
            f"{state.parse_failed} failed to parse, {state.skipped} refused ({outcome})."
        )
        self.record_info(
            _SITE_RUN_FINISHED,
            "RUN_FINISHED",
            self.summary,
            message_data={
                "outcome": outcome,
                "audits_run": len(state.audits_scheduled),
                "audits_skipped": sorted(state.audits_skipped),
            },
        )

    def _finding_node(
        self,
        pending: _PendingFinding,
        *,
        state: _RunState,
        observed_at: str,
        known_since: dict[UUID, str],
    ) -> dict[str, Any]:
        finding = pending.decomposed
        owner, _, repo = pending.workflow.full_name.partition("/")
        return batch_mod.node_envelope(
            entity_id=pending.entity_id,
            entity_type="zizmor__finding",
            name=f"{finding.audit_id} @ {pending.workflow.path}" + (f"#{finding.job_key}" if finding.job_key else ""),
            dimensions={
                "github.owner": owner,
                "github.repo": repo,
                "zizmor.scanner_version": state.scanner_version,
            },
            fields={
                "audit_id": finding.audit_id,
                "audit_url": finding.audit_url,
                "severity": finding.severity,
                "confidence": finding.confidence,
                "persona": finding.persona,
                "scanner_version": state.scanner_version,
                "summary": finding.summary,
                "location": finding.location,
                "fixes": finding.fixes,
                "raw": finding.raw,
                "tags": pending.tags,
                # First sighting is preserved across runs: re-observing a finding must not reset
                # how long it has been there, or "how old is this defect" becomes unanswerable.
                "known_since": known_since.get(pending.entity_id, observed_at),
                "observed_at": observed_at,
            },
        )

    def _post_check(self, state: _RunState, *, edges: list[dict[str, Any]], run_fields: dict[str, Any]) -> None:
        """The run's recorded counts must equal the findings reachable from it (req-zizmor-run-2).

        Presence is not correctness: a run node whose counts were merely *written* would pass any
        check that only asks whether the field is filled in. This one compares the declared
        numbers to the edges actually being submitted, and fails the run on a mismatch.
        """
        produced = sum(1 for edge in edges if edge["edge"]["edge_type"] == EDGE_PRODUCED_FINDING)
        declared_by_audit = sum(int(v) for v in run_fields["counts_by_audit"].values())
        declared_by_severity = sum(int(v) for v in run_fields["counts_by_severity"].values())
        if not (produced == declared_by_audit == declared_by_severity == len(state.findings)):
            self._abort(
                _SITE_COUNTS_MISMATCH,
                "COUNTS_MISMATCH",
                "The run's recorded finding counts do not equal the findings it is about to land.",
                produced_edges=produced,
                counts_by_audit_total=declared_by_audit,
                counts_by_severity_total=declared_by_severity,
                findings=len(state.findings),
            )

    # ------------------------------------------------------------------
    # Grid reads.
    # ------------------------------------------------------------------

    @staticmethod
    def _upstream_job_ids() -> list[Any]:
        """Entity ids of every collection job belonging to the upstream github_core collector.

        Matched on the collector's DERIVED entity id (`uuid5(NAMESPACE_COLLECTOR, "scope:key")`) so a
        display-name change cannot break the link. Derived once and shared by both callers below,
        rather than the same join written twice.
        """
        import uuid as uuid_module

        from tap_cares.registry import NAMESPACE_COLLECTOR
        from tap_grid.models import Edge

        collector_uuid = uuid_module.uuid5(NAMESPACE_COLLECTOR, _UPSTREAM_COLLECTOR_KEY)
        return list(
            Edge.objects.filter(from_entity_id=collector_uuid, edge_type="HAS_COLLECTION_JOB").values_list(
                "to_entity_id", flat=True
            )
        )

    @classmethod
    def _active_upstream_job(cls) -> str | None:
        """The github_core collection job currently in flight, if there is one.

        The question is "is a collection writing right now", not "how old is the last one": reading
        rows mid-write is the failure this guards, while a stale-but-quiet grid is perfectly safe to
        audit. READY counts as in flight — the job row exists and its task is queued, so rows may
        start landing at any moment.
        """
        job = (
            CollectionJob.objects.filter(
                entity_id__in=cls._upstream_job_ids(),
                status__in=(CollectionJobStatus.RUNNING, CollectionJobStatus.READY),
            )
            .order_by("-started_at", "-entity_id")
            .first()
        )
        return str(job.entity_id) if job is not None else None

    @classmethod
    def _latest_upstream_job(cls) -> str | None:
        """The most recent SUCCESSFUL github_core collection job on this grid.

        The run records it as provenance: which collection's rows these findings were derived from
        (req-zizmor-trigger-4).
        """
        job = (
            CollectionJob.objects.filter(entity_id__in=cls._upstream_job_ids(), status=CollectionJobStatus.SUCCESSFUL)
            .order_by("-finished_at", "-entity_id")
            .first()
        )
        return str(job.entity_id) if job is not None else None

    @staticmethod
    def _existing_known_since(finding_ids: set[UUID]) -> dict[UUID, str]:
        """First-sighting timestamps for findings already on the grid."""
        if not finding_ids:
            return {}
        rows = ZizmorFinding.objects.filter(entity_id__in=list(finding_ids)).values_list("entity_id", "known_since")
        return {entity_id: value.isoformat().replace("+00:00", "Z") for entity_id, value in rows if value is not None}


class _PendingFinding:
    """One decomposed finding plus the endpoints it resolved to, before envelope assembly."""

    __slots__ = ("entity_id", "decomposed", "workflow", "workflow_endpoint", "job_endpoint", "action_endpoint", "tags")

    def __init__(
        self,
        *,
        entity_id: UUID,
        decomposed: DecomposedFinding,
        workflow: GithubWorkflow,
        workflow_endpoint: UUID,
        job_endpoint: UUID | None,
        action_endpoint: UUID | None,
        tags: dict[str, Any],
    ) -> None:
        self.entity_id = entity_id
        self.decomposed = decomposed
        self.workflow = workflow
        self.workflow_endpoint = workflow_endpoint
        self.job_endpoint = job_endpoint
        self.action_endpoint = action_endpoint
        self.tags = tags


class _RunState:
    """Everything one run accumulates before it becomes a batch."""

    __slots__ = (
        "run_uuid",
        "scanner_version",
        "started_at",
        "repositories",
        "evaluated",
        "parse_failed",
        "skipped",
        "no_yaml",
        "scanned",
        "findings",
        "finding_ids",
        "by_audit",
        "by_severity",
        "audits_scheduled",
        "audits_skipped",
    )

    def __init__(self, *, run_uuid: UUID, scanner_version: str, started_at: datetime) -> None:
        self.run_uuid = run_uuid
        self.scanner_version = scanner_version
        self.started_at = started_at
        self.repositories: set[str] = set()
        self.evaluated = 0
        self.parse_failed = 0
        self.skipped = 0
        self.no_yaml = 0
        # workflow entity id -> (outcome, reason). One entry per workflow considered; the run's
        # SCANNED_WORKFLOW edges are built from exactly this, so coverage cannot silently omit a row.
        self.scanned: dict[UUID, tuple[str, str]] = {}
        self.findings: list[_PendingFinding] = []
        self.finding_ids: set[UUID] = set()
        self.by_audit: Counter[str] = Counter()
        self.by_severity: Counter[str] = Counter()
        self.audits_scheduled: frozenset[str] = frozenset()
        self.audits_skipped: dict[str, str] = {}
