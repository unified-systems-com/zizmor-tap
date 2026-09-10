# FLAGS_WORKFLOW

## Blurb

The finding concerns this workflow file — the one edge every finding has.

## Purpose

A scanner that produces a list of findings has produced a report. A scanner whose findings are attached to the assets they concern has produced graph data, and the difference is every question that joins across the estate: which of *these* repositories has an injection sink, which flagged workflow is also the one that deploys to production, which finding sits on a workflow protected by a ruleset nobody can bypass.

Every finding zizmor emits locates a workflow file, so this edge is unconditional. [`FLAGS_JOB`](FLAGS_JOB.md) and [`FLAGS_ACTION`](FLAGS_ACTION.md) sharpen the location when the finding supports it; this one is the anchor that is always there, and the reason `req-zizmor-finding-1` can require exactly one of them per finding.

## Goals

- Put every finding next to the asset it is about, unconditionally.
- Give the coverage question a shared endpoint: the same workflow node carries both this edge and [`SCANNED_WORKFLOW`](SCANNED_WORKFLOW.md), so "flagged" and "observed" are read off the same node.
- Keep the count of these edges per finding at exactly one, so a finding can never be about two files.

## Identity

Generic `(type, source, target)` edge id.

## Boundaries

Property-free. Where in the file the finding sits is the finding's `location` — path, route, row, column, the source text at the site — and putting any of it here would derive it twice.

Not covered:

- **Severity, confidence, audit.** Properties of the assertion, on [`zizmor__finding`](../models/finding.py).
- **Whether the workflow was scanned.** [`SCANNED_WORKFLOW`](SCANNED_WORKFLOW.md). A workflow with findings was obviously scanned; a workflow with none needs the other edge to say so.

## Neutrality

**Scanner-neutral in shape, GitHub-specific in target.** "A finding is about an asset" is the compliance-level relationship this node is a disguised instance of. The target is `github_core__github_workflow` because that is what zizmor audits; a neutral findings substrate would generalize the source side long before the target side.

## Observability

Derived. The scanner reports a path; the collector resolves it to the workflow row it materialized from, through github_core's own `identity.workflow_id` — never re-derived here.
