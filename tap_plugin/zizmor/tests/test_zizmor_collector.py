"""Unit tests for the zizmor collector's decision-making, without a grid.

req-zizmor-collector-4 (path sanitizing), req-zizmor-binary-2 (version abort), req-zizmor-finding
(decomposition and endpoint claims). These cover the paths where the collector decides to REFUSE
something, because those are the paths a live run does not exercise and therefore the ones that
rot silently.

Endpoints are asserted explicitly rather than by trusting the graph to reject a wrong one: an
edge's declared sources/targets are currently NOT enforced at write time (tap#397), so "the write
succeeded" says nothing about whether the endpoint was right.

The scanner-output fixtures here are verbatim excerpts of real `zizmor 1.30.0 --format json-v1`
output (*observed* 2026-09-10), not hand-imagined shapes — a fixture invented from the docs would
test our idea of the format rather than the format.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tap_plugin.zizmor.collectors.zizmor_collector import binary, identity, scratch
from tap_plugin.zizmor.collectors.zizmor_collector.decompose import decompose, render_route

# ---------------------------------------------------------------------------
# Path sanitizing — req-zizmor-collector-4.
# ---------------------------------------------------------------------------

REPO = "unified-systems-com/tap"


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    root.mkdir()
    return root


def test_ordinary_workflow_path_lands_inside_its_repository(run_root: Path) -> None:
    target = scratch.safe_target(run_root, full_name=REPO, path=".github/workflows/ci.yml")

    assert target.file_path == run_root / "unified-systems-com" / "tap" / ".github" / "workflows" / "ci.yml"
    assert target.relative_path == ".github/workflows/ci.yml"


@pytest.mark.parametrize(
    ("path", "because"),
    [
        ("/etc/cron.d/x", "absolute"),
        ("../../../../etc/passwd", "parent traversal"),
        (".github/workflows/../../../../etc/passwd", "traversal mid-path"),
        ("", "empty"),
        ("C:\\windows\\system32", "windows drive"),
        ("\\\\server\\share", "UNC"),
        (".github/workflows/ci.yml\x00.txt", "embedded NUL"),
    ],
)
def test_a_hostile_workflow_path_is_refused_rather_than_normalized(run_root: Path, path: str, because: str) -> None:
    """`path` is collected data; every one of these would write outside the tree if honoured."""
    with pytest.raises(scratch.UnsafePathError):
        scratch.safe_target(run_root, full_name=REPO, path=path)


@pytest.mark.parametrize("full_name", ["tap", "a/b/c", "../tap", "/abs/tap", ""])
def test_a_repository_name_that_is_not_owner_slash_repo_is_refused(run_root: Path, full_name: str) -> None:
    with pytest.raises(scratch.UnsafePathError):
        scratch.safe_target(run_root, full_name=full_name, path=".github/workflows/ci.yml")


def test_nothing_is_written_outside_the_scratch_tree_when_a_path_is_refused(run_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    with pytest.raises(scratch.UnsafePathError):
        target = scratch.safe_target(run_root, full_name=REPO, path="../../outside.txt")
        scratch.materialize(target, "pwned")
    assert not outside.exists()


def test_materialize_refuses_to_follow_a_symlink_already_at_the_destination(run_root: Path, tmp_path: Path) -> None:
    """Exclusive creation is what stops a pre-placed link redirecting the write."""
    target = scratch.safe_target(run_root, full_name=REPO, path=".github/workflows/ci.yml")
    target.file_path.parent.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("original")
    target.file_path.symlink_to(victim)

    with pytest.raises(FileExistsError):
        scratch.materialize(target, "pwned")
    assert victim.read_text() == "original"


# ---------------------------------------------------------------------------
# Version gate — req-zizmor-binary-2.
# ---------------------------------------------------------------------------


def test_the_pin_is_read_from_the_distribution_rather_than_authored_twice() -> None:
    version = binary.pinned_version()
    assert version and version[0].isdigit()


def test_a_binary_whose_version_differs_from_the_pin_aborts_before_scanning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binary, "locate", lambda: Path("/nonexistent/zizmor"))
    monkeypatch.setattr(binary, "pinned_version", lambda: "1.30.0")
    monkeypatch.setattr(binary, "observed_version", lambda _binary: "1.29.0")

    with pytest.raises(binary.ZizmorBinaryError) as caught:
        binary.verify_version()
    assert "1.30.0" in str(caught.value) and "1.29.0" in str(caught.value)


def test_a_binary_matching_the_pin_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binary, "locate", lambda: Path("/opt/zizmor"))
    monkeypatch.setattr(binary, "pinned_version", lambda: "1.30.0")
    monkeypatch.setattr(binary, "observed_version", lambda _binary: "1.30.0")

    found, version = binary.verify_version()
    assert (found, version) == (Path("/opt/zizmor"), "1.30.0")


# ---------------------------------------------------------------------------
# The audit inventory, derived from the binary's own diagnostics.
# ---------------------------------------------------------------------------

# Verbatim `-vv` stderr lines, zizmor 1.30.0 (*observed* 2026-09-10).
_STDERR = """ INFO zizmor: 🌈 zizmor v1.30.0
DEBUG zizmor::registry: skipping impostor-commit: can't run without a GitHub API token
DEBUG zizmor::registry: skipping ref-confusion: can't run without a GitHub API token
DEBUG audit: zizmor: scheduling artipacked on file://./.github/workflows/bad.yml
DEBUG audit: zizmor: scheduling template-injection on file://./.github/workflows/bad.yml
 INFO audit: zizmor: 🌈 completed ./.github/workflows/bad.yml
"""


def test_the_audit_set_is_derived_from_the_scanners_own_diagnostics() -> None:
    scheduled, skipped, parse_reason = binary.parse_diagnostics(_STDERR)

    assert scheduled == frozenset({"artipacked", "template-injection"})
    assert skipped == {
        "impostor-commit": "can't run without a GitHub API token",
        "ref-confusion": "can't run without a GitHub API token",
    }
    assert parse_reason == ""


def test_a_parse_failure_is_reported_with_the_scanners_own_reason() -> None:
    stderr = (
        " WARN collect_inputs: zizmor::registry::input: failed to parse input: did not find "
        "expected ',' or ']' at line 3 column 5\n"
    )
    _scheduled, _skipped, parse_reason = binary.parse_diagnostics(stderr)

    assert "did not find expected" in parse_reason


def test_diagnostics_that_do_not_match_yield_nothing_rather_than_a_guess() -> None:
    """An unparseable log must fail CLOSED: an empty audit set stops the run downstream."""
    scheduled, skipped, parse_reason = binary.parse_diagnostics("some future log format\n")

    assert (scheduled, skipped, parse_reason) == (frozenset(), {}, "")


# ---------------------------------------------------------------------------
# Decomposition — req-zizmor-finding.
# ---------------------------------------------------------------------------


def _finding(**overrides: object) -> dict:
    """A real `template-injection` finding, trimmed to the fields under test."""
    base = {
        "ident": "template-injection",
        "desc": "code injection via template expansion",
        "url": "https://docs.zizmor.sh/audits/#template-injection",
        "determinations": {"confidence": "High", "severity": "High", "persona": "Regular"},
        "ignored": False,
        "fixes": [],
        "locations": [
            {
                "symbolic": {
                    "key": {"Local": {"verbatim_path": "./.github/workflows/ci.yml"}},
                    "annotation": "this step",
                    "route": {"route": [{"Key": "jobs"}, {"Key": "build"}, {"Key": "steps"}, {"Index": 2}]},
                    "feature_kind": "Normal",
                    "kind": "Hidden",
                },
                "concrete": {"location": {"start_point": {"row": 1, "column": 1}}, "feature": "hidden"},
            },
            {
                "symbolic": {
                    "key": {"Local": {"verbatim_path": "./.github/workflows/ci.yml"}},
                    "annotation": "may expand into attacker-controllable code",
                    "route": {
                        "route": [{"Key": "jobs"}, {"Key": "build"}, {"Key": "steps"}, {"Index": 2}, {"Key": "run"}]
                    },
                    "feature_kind": {"Subfeature": {"after": 198, "fragment": {"Raw": "matrix.image"}}},
                    "kind": "Primary",
                },
                "concrete": {
                    "location": {"start_point": {"row": 6, "column": 8}, "end_point": {"row": 8, "column": 56}},
                    "feature": "|\n          echo ${{ matrix.image }}\n",
                },
            },
        ],
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def test_the_finding_is_decomposed_from_its_primary_location_not_the_first_one() -> None:
    """The first location here is `Hidden`; attaching to it would point at the wrong line."""
    result = decompose(_finding(), workflow_path=".github/workflows/ci.yml")

    assert result.location["route"] == "jobs/build/steps/2/run"
    assert result.location["annotation"] == "may expand into attacker-controllable code"
    assert result.location["row"] == 6


def test_the_workflow_path_stored_is_the_grids_not_the_scratch_trees() -> None:
    """The scratch layout is an implementation detail of one run and must not land on a node."""
    result = decompose(_finding(), workflow_path=".github/workflows/ci.yml")

    assert result.location["path"] == ".github/workflows/ci.yml"


def test_the_job_and_step_are_lifted_out_of_the_route() -> None:
    result = decompose(_finding(), workflow_path=".github/workflows/ci.yml")

    assert result.job_key == "build"
    assert result.location["step_index"] == 2


def test_a_workflow_level_finding_names_no_job_rather_than_guessing_one() -> None:
    finding = _finding()
    finding["locations"][1]["symbolic"]["route"] = {"route": []}  # type: ignore[index]
    result = decompose(finding, workflow_path=".github/workflows/ci.yml")

    assert result.job_key is None
    assert result.location["route"] == ""


def test_the_narrowed_fragment_is_extracted_because_it_is_the_finding() -> None:
    """Four findings can share audit, route, persona, row and column; only this tells them apart."""
    result = decompose(_finding(), workflow_path=".github/workflows/ci.yml")

    assert result.subfeature == "matrix.image"
    assert result.location["subfeature_offset"] == 198


def test_findings_differing_only_by_fragment_get_different_identities() -> None:
    common = {
        "full_name": REPO,
        "workflow_id_int": 42,
        "audit_id": "template-injection",
        "route": "jobs/build/steps/2/run",
        "persona": "Regular",
    }
    first = identity.finding_id(**common, subfeature="matrix.image")
    second = identity.finding_id(**common, subfeature="github.ref")

    assert first != second
    assert first == identity.finding_id(**common, subfeature="matrix.image"), "identity must be stable across runs"


def test_an_occurrence_suffix_only_applies_when_asked_for() -> None:
    common = {
        "full_name": REPO,
        "workflow_id_int": 42,
        "audit_id": "template-injection",
        "route": "jobs/build/steps/2/run",
        "persona": "Regular",
        "subfeature": "matrix.image",
    }
    assert identity.finding_id(**common) != identity.finding_id(**common, occurrence=1)


def test_a_finding_is_not_keyed_on_its_row_so_a_reformat_does_not_re_identify_it() -> None:
    moved = _finding()
    moved["locations"][1]["concrete"]["location"]["start_point"] = {"row": 999, "column": 3}  # type: ignore[index]
    original = decompose(_finding(), workflow_path=".github/workflows/ci.yml")
    shifted = decompose(moved, workflow_path=".github/workflows/ci.yml")

    key = {"full_name": REPO, "workflow_id_int": 42, "audit_id": original.audit_id, "persona": original.persona}
    assert identity.finding_id(
        **key, route=original.location["route"], subfeature=original.subfeature
    ) == identity.finding_id(**key, route=shifted.location["route"], subfeature=shifted.subfeature)


# ---------------------------------------------------------------------------
# `uses:` classification — the endpoint claims.
# ---------------------------------------------------------------------------


def _uses_finding(feature: str) -> dict:
    return {
        "ident": "unpinned-uses",
        "desc": "unpinned action reference",
        "url": "https://docs.zizmor.sh/audits/#unpinned-uses",
        "determinations": {"confidence": "High", "severity": "Medium", "persona": "Regular"},
        "ignored": False,
        "fixes": [],
        "locations": [
            {
                "symbolic": {
                    "annotation": "action is not pinned",
                    "route": {
                        "route": [{"Key": "jobs"}, {"Key": "b"}, {"Key": "steps"}, {"Index": 0}, {"Key": "uses"}]
                    },
                    "feature_kind": "Normal",
                    "kind": "Primary",
                },
                "concrete": {"location": {"start_point": {"row": 6, "column": 14}}, "feature": feature},
            }
        ],
    }


def test_an_action_reference_yields_the_ref_stripped_path_and_keeps_the_pin() -> None:
    """The node is keyed without the ref; the ref rides the edge, or the pin is lost."""
    result = decompose(_uses_finding("actions/checkout@v4"), workflow_path=".github/workflows/ci.yml")

    assert result.uses_kind == "action"
    assert result.action_path == "actions/checkout"
    assert result.uses == "actions/checkout@v4"


def test_a_reusable_workflow_call_is_not_treated_as_an_action() -> None:
    """Same syntax, different concept: github_core mints no action node for one, and is right not to.

    Before this was classified, the only two unresolvable "actions" in a 155-finding run against
    the real org were both reusable-workflow calls (*observed* 2026-09-10).
    """
    result = decompose(
        _uses_finding("unified-systems-com/tap/.github/workflows/plugin-ci.yml@main"),
        workflow_path=".github/workflows/ci.yml",
    )

    assert result.uses_kind == "reusable-workflow"
    assert result.action_path is None


@pytest.mark.parametrize("feature", ["./local/action", "docker://alpine:3", "not a uses value at all"])
def test_a_reference_that_names_no_action_node_claims_nothing(feature: str) -> None:
    result = decompose(_uses_finding(feature), workflow_path=".github/workflows/ci.yml")

    assert result.action_path is None
    assert result.uses_kind is None


def test_a_uses_is_only_read_where_the_route_actually_names_one() -> None:
    """A step-level finding's feature is the whole step body; parsing an action out of it would
    be inferring the finding's subject rather than reading it."""
    finding = _uses_finding("uses: actions/checkout@v4\n        with:\n          ref: x")
    finding["locations"][0]["symbolic"]["route"] = {  # type: ignore[index]
        "route": [{"Key": "jobs"}, {"Key": "b"}, {"Key": "steps"}, {"Index": 0}]
    }
    result = decompose(finding, workflow_path=".github/workflows/ci.yml")

    assert result.action_path is None


# ---------------------------------------------------------------------------
# Determination mapping.
# ---------------------------------------------------------------------------


def test_an_unrecognised_determination_becomes_Unknown_rather_than_rejecting_the_batch() -> None:
    """A value outside the model's enumeration would take the whole batch down with it."""
    finding = _finding(determinations={"confidence": "Certain", "severity": "Catastrophic", "persona": "Robot"})
    result = decompose(finding, workflow_path=".github/workflows/ci.yml")

    assert (result.severity, result.confidence) == ("Unknown", "Unknown")
    assert result.persona == "Regular"


def test_the_persona_recorded_is_the_findings_own_not_the_runs() -> None:
    """An auditor-persona run emits regular/pedantic/auditor findings together, and which one this
    is decides whether a reader should act on it."""
    result = decompose(_finding(determinations={"confidence": "Low", "severity": "Low", "persona": "Pedantic"}),
                       workflow_path=".github/workflows/ci.yml")

    assert result.persona == "Pedantic"


def test_the_raw_scanner_assertion_is_kept_verbatim() -> None:
    finding = _finding()
    result = decompose(finding, workflow_path=".github/workflows/ci.yml")

    assert result.raw == finding


def test_route_rendering_handles_keys_and_indices() -> None:
    assert render_route([{"Key": "jobs"}, {"Key": "build"}, {"Key": "steps"}, {"Index": 0}]) == "jobs/build/steps/0"
    assert render_route([]) == ""
