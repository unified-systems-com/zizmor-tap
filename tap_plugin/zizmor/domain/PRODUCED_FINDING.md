# PRODUCED_FINDING

## Blurb

One execution of the scanner emitted this finding.

## Purpose

A finding without a run behind it is a claim with no conditions attached. Which binary version said it, at which persona, over which set of workflow rows, at what time — none of that is a property of the finding as a statement about the world; all of it is a property of the execution that produced it, and all of it is what turns the claim into data.

The edge is what makes that provenance walkable rather than copied. `scanner_version` and `persona` are on the finding as well, because a finding is often read alone and must carry its own minimum context, but the authoritative account of the conditions — the source collection, the coverage, the counts, the duration — lives once on [`zizmor__run`](../models/run.py) and is reached from here.

It is also the edge that makes a re-scan legible. Two runs a day apart produce two sets of findings; without the run edge, the only way to ask "what changed" is to diff on content and hope the finding identity held.

## Goals

- Give every finding exactly one execution it can be traced back to.
- Keep the run's account of itself in one place, reachable rather than duplicated onto each finding.
- Make "the findings this run produced" a traversal, so the run's own recorded counts can be checked against it rather than trusted (`req-zizmor-run-2`).

## Identity

Generic `(type, source, target)` edge id. Unlike [`FLAGS_ACTION`](FLAGS_ACTION.md), no third discriminator is needed: a run produces a given finding once, and a second production of the same finding is a second run.

## Boundaries

Carries no properties. Everything about the execution belongs to the run node; everything about the assertion belongs to the finding.

Not covered:

- **What changed since the last run.** A diff between two runs is a query over two `PRODUCED_FINDING` sets, not a fact on this edge.
- **Whether the finding is still true.** This edge says a run asserted it, not that it holds now. `known_since` and `observed_at` on the finding carry that.

## Neutrality

**Scanner-neutral in shape, plugin-scoped in name.** "An execution produced a finding" is true of every scanner, and this edge would survive into a neutral findings substrate unchanged — which is the point of the compliance-node-in-disguise note on [`zizmor__finding`](../models/finding.py). It is `__zizmor` today because the endpoints are, and `req-zizmor-second-scanner` is what will force the question.

## Observability

Derived: the collector knows which run it is and which findings it just parsed out of the scanner's `json-v1` output. No call, no permission, no inference.
