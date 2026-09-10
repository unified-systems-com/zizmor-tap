# FLAGS_JOB

## Blurb

The finding's location resolves to a job declared in the workflow — present only when that job is actually on the grid.

## Purpose

Almost every privilege decision in CI is made at the declared-job level: what the job's `permissions` grant, which runner it lands on, which environment it deploys to, what it checks out. A finding that says "template injection in this file" is a lint result; the same finding joined to the job that carries `contents: write` and a deploy environment is a risk statement.

This edge is that join. It is deliberately conditional: zizmor's location gives a symbolic route (`jobs/build/steps/2`), and the job key lifted out of it may name a job that — for a workflow github_core parsed differently, or did not parse at all — has no `github_core__workflow_job` node. When the job cannot be resolved, **no edge is written and the finding records why in `tags`** (`req-zizmor-finding-2`). A guessed endpoint would be worse than a missing one: it would put the finding next to the wrong privileges and read as verified.

## Goals

- Join a finding to the privileges of the job it sits in, where the job is known.
- Never mint an endpoint that was not resolved — the missing edge plus a recorded reason is the honest shape.
- Keep step position out of the graph, per the corpus ruling that steps are a field and not a node.

## Identity

Generic `(type, source, target)` edge id.

## Boundaries

Property-free. The job key and the step index are in the finding's `location`, lifted out of the route so a consumer does not re-parse it; the job's own attributes are on the job node.

Not covered:

- **Steps.** A step is not a node (corpus ruling). zizmor reports step indices and the finding keeps them in `location`.
- **The unresolved case.** Absence of this edge is not a fact about the job; it is a fact about resolution, and it is recorded in the finding's `tags` rather than implied by the gap.
- **What the job is permitted to do.** On the job node, reached across this edge.

## Neutrality

**Scanner-neutral in shape, GitHub-specific in target.** The declared-job concept is `workflow_job`'s, which github_core's vocabulary already marks as neutral-when-a-substrate-exists; this edge follows it wherever it goes.

## Observability

Derived. The job key comes out of the scanner's route, and the endpoint id comes from github_core's `identity.workflow_job_id`. Resolution is a lookup against rows already on the grid — no call, no permission.
