# SCANNED_WORKFLOW

## Blurb

The run considered this workflow — and the outcome says what actually happened to it, so that silence never reads as safety.

## Purpose

This is the three-states rule made mechanical. A findings view can show a workflow with no findings for two completely different reasons: the scanner read it and found nothing, or the scanner never read it at all. Collapsing those into one blank cell is the most reassuring possible lie, and it is produced by ordinary, well-meaning code that only knows how to render what it has.

The edge is what makes the second state observable. A workflow carrying no `SCANNED_WORKFLOW` edge from the current run was **not observed by this scanner**; a workflow carrying one with `outcome: evaluated` and no findings is clean. Every consumer — the findings table, git-serious's workflow page, any future conjunction query — reads coverage from here rather than inferring it from the absence of findings.

The `no-yaml` outcome exists because absence turned out to be the common case, not the corner: on a real org collection (24 repositories, observed 2026-09-10) **40 of 117 workflows carried no `raw_yaml`**. github_core had collected the workflow — it is on the grid, it has a name and a path — but there was no body to scan. That is neither "skipped by the collector" nor "clean", and giving it its own value keeps a third of the estate from quietly rendering as fine.

## Goals

- Make absence of evidence distinguishable from evidence of absence, per workflow, per run.
- Refuse an unexplained non-result: any outcome other than `evaluated` must say why, in the schema, not by convention.
- Keep coverage a property of the run→workflow relationship, so it is correct per run rather than a mutable flag on the workflow.

## Identity

Generic `(type, source, target)` edge id. One run considers a given workflow once; a re-scan is a new run and therefore a new edge.

## Boundaries

Carries the outcome and its reason, and nothing else.

Not covered:

- **Finding counts.** Reachable by walking [`PRODUCED_FINDING`](PRODUCED_FINDING.md) and [`FLAGS_WORKFLOW`](FLAGS_WORKFLOW.md); storing a count here would be the same fact derived twice, and the copy is the one that goes stale.
- **Why the workflow has no YAML.** The reason string names the absence; whether github_core *could* have captured it is github_core's fact, not this edge's.
- **Findings themselves.** A scanned workflow with findings has both this edge and the flag edges; neither implies the other.

## Neutrality

**Scanner-neutral in shape.** "This run covered this asset, with this outcome" is the coverage primitive any scanner needs, and the four outcomes are not zizmor-specific — `no-yaml` generalizes to "the input was not on the grid to read". Moves to a neutral findings substrate with `PRODUCED_FINDING` when one is extracted.

## Observability

Derived from grid state. The collector knows which workflow rows it read, which it refused and why, which the scanner failed to parse, and which had no body — every outcome is established during the run, none is looked up.
