"""Turning one zizmor json-v1 finding into the facts the grid stores.

Spec: specs/spec-zizmor-v0.md (req-zizmor-finding).

The shape below was read off the binary, not off the documentation (*observed* 2026-09-10,
zizmor 1.30.0). One finding is::

    {"ident": "artipacked", "desc": "...", "url": "https://docs.zizmor.sh/audits/#artipacked",
     "determinations": {"confidence": "Low", "severity": "Medium", "persona": "Regular"},
     "locations": [{"symbolic": {"key": {"Local": {"verbatim_path": "./.github/workflows/x.yml"}},
                                 "annotation": "...", "route": {"route": [{"Key": "jobs"}, ...]},
                                 "feature_kind": "Normal", "kind": "Primary"},
                    "concrete": {"location": {"start_point": {"row": 6, "column": 8}, ...},
                                 "feature": "uses: actions/checkout@main"}}],
     "ignored": false, "fixes": [{"title": "...", "disposition": "unsafe"}]}

Two decisions worth stating.

**The workflow is never parsed out of `verbatim_path`.** The collector invokes the scanner once
per workflow file, so it already knows which grid row it handed over; reading the file back out of
the scanner's output would be re-deriving a fact we hold, and would inherit whatever relative-path
convention the binary happens to use.

**Job and action endpoints are resolved, never constructed.** The symbolic route yields a job KEY
and a `uses:` string, which are claims about what exists. Turning a claim into an edge without
checking the endpoint is on the grid mints a node that matches nothing and reads, in every view,
exactly like a real relationship (req-zizmor-finding-2). So this module extracts; the collector
checks existence before attaching, and records why when it cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

# `owner/repo[/subpath]@ref` — the only `uses:` shape that names a github_action node. A local
# (`./path`) or container (`docker://`) reference is a different kind of thing and has no node.
_USES_RE: Final = re.compile(r"^(?P<path>[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._/-]+)?)@(?P<ref>[^\s@]+)$")
# A job-level `uses:` pointing INTO a repository's `.github/workflows/` is a reusable WORKFLOW
# call, not an action. It is the same syntax and a different concept, and github_core is right not
# to mint a `github_action` node for one — so treating it as an action here would look for an
# endpoint that correctly does not exist. (*Observed* 2026-09-10 on the real org: the only two
# unresolvable "actions" in a 155-finding run were both reusable-workflow calls.)
_REUSABLE_WORKFLOW_RE: Final = re.compile(r"^[^/]+/[^/]+/\.github/workflows/[^/]+\.ya?ml$")

SEVERITY_VALUES: Final[frozenset[str]] = frozenset({"Unknown", "Informational", "Low", "Medium", "High"})
CONFIDENCE_VALUES: Final[frozenset[str]] = frozenset({"Unknown", "Low", "Medium", "High"})
PERSONA_VALUES: Final[frozenset[str]] = frozenset({"Regular", "Pedantic", "Auditor"})


@dataclass(frozen=True, slots=True)
class DecomposedFinding:
    """One json-v1 finding, reduced to the fields the model stores plus its endpoint claims."""

    audit_id: str
    audit_url: str
    severity: str
    confidence: str
    persona: str
    summary: str
    location: dict[str, Any]
    fixes: list[dict[str, Any]]
    raw: dict[str, Any]
    ignored: bool
    # Endpoint CLAIMS — what the finding's site says it is about. Neither is an endpoint until the
    # collector has found it on the grid.
    job_key: str | None
    uses: str | None
    action_path: str | None
    # What the `uses:` at this site refers to: an action (which has a node), a reusable workflow
    # call (which does not), or nothing recognizable. Never None-means-two-things.
    uses_kind: str | None
    # The exact fragment inside the feature that the finding is about, when the scanner narrows
    # to one — `matrix.image` inside a whole `run:` block. Part of the finding's identity.
    subfeature: str | None


def render_route(route: list[Any]) -> str:
    """Render zizmor's symbolic route as a readable path: `jobs/build/steps/0`."""
    parts: list[str] = []
    for element in route:
        if isinstance(element, dict):
            if "Key" in element:
                parts.append(str(element["Key"]))
                continue
            if "Index" in element:
                parts.append(str(element["Index"]))
                continue
        parts.append(str(element))
    return "/".join(parts)


def _route_elements(location: dict[str, Any]) -> list[Any]:
    route = ((location.get("symbolic") or {}).get("route") or {}).get("route")
    return route if isinstance(route, list) else []


def job_key_from_route(route: list[Any]) -> str | None:
    """The YAML job key the route passes through, if it passes through one.

    A route is `jobs/<key>/...`; anything else (a workflow-level finding, an `on:` trigger
    finding) names no job, and says so with None rather than a guess.
    """
    for index, element in enumerate(route):
        if isinstance(element, dict) and element.get("Key") == "jobs" and index + 1 < len(route):
            following = route[index + 1]
            if isinstance(following, dict) and isinstance(following.get("Key"), str):
                return following["Key"]
            return None
    return None


def step_index_from_route(route: list[Any]) -> int | None:
    """The step index under the job, if the route names one."""
    for index, element in enumerate(route):
        if isinstance(element, dict) and element.get("Key") == "steps" and index + 1 < len(route):
            following = route[index + 1]
            if isinstance(following, dict) and isinstance(following.get("Index"), int):
                return following["Index"]
            return None
    return None


def primary_location(finding: dict[str, Any]) -> dict[str, Any]:
    """The location the finding is *about*.

    zizmor marks one location `Primary` and any supporting sites `Related`; attaching a finding to
    a related site would put it next to the wrong line. Falls back to the first location only when
    no primary is marked, so a finding is never dropped for want of a label.
    """
    locations = finding.get("locations")
    if not isinstance(locations, list) or not locations:
        return {}
    for location in locations:
        if isinstance(location, dict) and (location.get("symbolic") or {}).get("kind") == "Primary":
            return location
    first = locations[0]
    return first if isinstance(first, dict) else {}


def _uses_at(location: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """The `uses:` value at this site, when the site IS a `uses:` key, and its ref-stripped path.

    Restricted to routes ending in a `uses` key on purpose. Several audits report at the step or
    workflow level while *being about* an action, and pulling an action reference out of a
    multi-line step body would be inferring the finding's subject rather than reading it. The
    collector records that the reference was not resolvable at the site instead of guessing.
    """
    route = _route_elements(location)
    if not route:
        return None, None, None
    last = route[-1]
    if not (isinstance(last, dict) and last.get("Key") == "uses"):
        return None, None, None
    feature = ((location.get("concrete") or {}).get("feature") or "").strip()
    match = _USES_RE.match(feature)
    if not match:
        return None, None, None
    path = match.group("path")
    if _REUSABLE_WORKFLOW_RE.match(path):
        return feature, None, "reusable-workflow"
    return feature, path, "action"


def subfeature_of(location: dict[str, Any]) -> tuple[str | None, int | None]:
    """The narrowed fragment the finding is actually about, and its offset in the feature.

    zizmor reports many findings against a whole `run:` block while meaning one expression inside
    it: `feature_kind` is then `{"Subfeature": {"after": 198, "fragment": {"Raw": "matrix.image"}}}`.
    That fragment is the finding — four `template-injection` findings on one step differ ONLY by it
    (*observed* 2026-09-10: same audit, same route, same persona, two of them at the same row and
    column) — so without it they are indistinguishable, and a key that ignored it would collapse
    four real defects into one.

    The offset is returned for display, never for identity: it moves whenever anything above it in
    the block is edited.
    """
    feature_kind = (location.get("symbolic") or {}).get("feature_kind")
    if not isinstance(feature_kind, dict):
        return None, None
    subfeature = feature_kind.get("Subfeature")
    if not isinstance(subfeature, dict):
        return None, None
    fragment = subfeature.get("fragment")
    raw = fragment.get("Raw") if isinstance(fragment, dict) else None
    after = subfeature.get("after")
    return (raw if isinstance(raw, str) else None, after if isinstance(after, int) else None)


def _enum_or_unknown(value: Any, allowed: frozenset[str], *, default: str) -> str:
    """Map a determination onto the model's enumeration, defaulting rather than landing junk.

    A value outside the enumeration would be rejected by the field's validation schema and take
    the whole batch with it. `Unknown` is a real member of both enumerations and is the honest
    rendering of "the scanner said something this version of the plugin does not recognize".
    """
    return value if isinstance(value, str) and value in allowed else default


def decompose(finding: dict[str, Any], *, workflow_path: str) -> DecomposedFinding:
    """Reduce one json-v1 finding to stored fields plus its endpoint claims."""
    location = primary_location(finding)
    route = _route_elements(location)
    symbolic = location.get("symbolic") or {}
    concrete = location.get("concrete") or {}
    coordinates = concrete.get("location") or {}
    start = coordinates.get("start_point") or {}
    end = coordinates.get("end_point") or {}
    uses, action_path, uses_kind = _uses_at(location)
    subfeature, subfeature_offset = subfeature_of(location)

    return DecomposedFinding(
        audit_id=str(finding.get("ident") or ""),
        audit_url=str(finding.get("url") or ""),
        severity=_enum_or_unknown(
            (finding.get("determinations") or {}).get("severity"), SEVERITY_VALUES, default="Unknown"
        ),
        confidence=_enum_or_unknown(
            (finding.get("determinations") or {}).get("confidence"), CONFIDENCE_VALUES, default="Unknown"
        ),
        # The persona is a property of the FINDING, not of the run: an auditor-persona run emits
        # regular-, pedantic- and auditor-persona findings together, and which one this is decides
        # whether a reader should act on it.
        persona=_enum_or_unknown(
            (finding.get("determinations") or {}).get("persona"), PERSONA_VALUES, default="Regular"
        ),
        summary=str(finding.get("desc") or ""),
        location={
            # The workflow path as the GRID knows it, not as the scanner rendered it: the scratch
            # tree's layout is an implementation detail of this run and must not leak onto a node.
            "path": workflow_path,
            "route": render_route(route),
            "job_key": job_key_from_route(route),
            "step_index": step_index_from_route(route),
            "row": start.get("row"),
            "column": start.get("column"),
            "end_row": end.get("row"),
            "end_column": end.get("column"),
            "feature": concrete.get("feature"),
            "subfeature": subfeature,
            "subfeature_offset": subfeature_offset,
            "annotation": symbolic.get("annotation"),
        },
        fixes=[
            f for f in (finding.get("fixes") or []) if isinstance(f, dict) and f.get("title") and f.get("disposition")
        ],
        raw=finding,
        ignored=bool(finding.get("ignored")),
        job_key=job_key_from_route(route),
        uses=uses,
        action_path=action_path,
        uses_kind=uses_kind,
        subfeature=subfeature,
    )
