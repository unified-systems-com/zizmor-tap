# FLAGS_ACTION

## Blurb

The finding is about a `uses:` reference to this action — and the specific reference rides the edge, because the action node deliberately has no ref.

## Purpose

Nine of zizmor's audits are about action references: `unpinned-uses`, `stale-action-refs`, `ref-confusion`, `impostor-commit`, `known-vulnerable-actions`, `typosquat-uses`, `archived-uses`, `superfluous-actions`, `forbidden-uses`. Attaching those to the workflow file alone answers "which files have a problem" and loses the question the estate actually has: *which of my jobs hand their token to this action*, and is this finding about the one call site or all of them.

`github_core__github_action` is keyed on the action path with the ref **stripped**, so `actions/checkout` is one node the whole grid points at — which is exactly what makes "every job using an unpinned checkout" a traversal instead of a string comparison across duplicates. The consequence is that the ref cannot live on the node, and a finding about a specific pin has to carry it here.

The v0 spec deferred this edge until `github_action` existed. It exists (github_core v0.6.0, 19 action nodes observed on a real collection 2026-09-10), so the edge lands with the rest.

## Goals

- Make an action-reference finding reachable from the action, not only from the file.
- Carry the reference the finding was reporting on, so a finding about `@v4` is not confused with one about a pinned SHA in the next job.
- Take nothing from `USES_ACTION` — the pin's meaning is github_core's fact, asserted once.

## Identity

Generic `(type, source, target)` edge id. Note the contrast with github_core's `USES_ACTION__github_core`, which keys on `(job, action, declared_ref)` because one job may make two different trust decisions about the same action. A finding is already specific to one site, so the finding is its own discriminator.

## Boundaries

Carries `uses` — the reference exactly as written at the site the finding names, ref included — and nothing else. The ref is derivable from that string, so storing it separately would be the same fact twice.

Not covered:

- **What the pin means.** `pin_kind`, `is_pinned`, `resolved_sha`, `resolution` are `USES_ACTION`'s properties, established by github_core's collector with the resolution machinery to do it honestly. This edge re-deriving any of them would produce a second answer that disagrees on the day a tag moves. The schema refuses them.
- **Local actions** (`./...`) and reusable-workflow calls, which are not `github_action` targets.
- **Which step.** In the finding's `location`.

## Neutrality

**Vendor-specific**, with its target. The `uses:` grammar is GitHub Actions'. Moves with `github_action` if that node ever gets a neutral parent.

## Observability

Derived. The reference comes out of the scanner's finding — the location's feature text and the audit's own subject — and the endpoint id comes from github_core's `identity.github_action_id`, which strips the ref. When the referenced action has no node on the grid, no edge is written and the reference stays in the finding's `tags`, the same honest-absence rule as [`FLAGS_JOB`](FLAGS_JOB.md).
