# zizmor-tap

**TAP zizmor plugin — GitHub Actions workflow audits, consumed offline onto the grid.**

> Status: pre-alpha skeleton (2026-09-02). Nothing collects yet; the spec is the plan.

## What this plugin owns

- A **derived, offline collector** (`zizmor:zizmor`): reads the workflow YAML
  [github_core](https://github.com/unified-systems-com/tap-plugin-github-core) has already
  landed on the grid, runs the pinned [zizmor](https://docs.zizmor.sh/) binary over it with
  `--offline`, and lands typed findings attached to the workflow and job they concern. No forge
  access, no credential, no network.
- The finding and run vocabulary (`zizmor__finding`, `zizmor__run`), the edges to github_core's
  workflow and job nodes, and the landing / run / finding pages with their panel types.

## What lives elsewhere

- The GitHub vocabulary (workflows, jobs, rulesets, runs) and the credential that observes an
  organization: **github_core**. This plugin never holds a credential.
- The product that mounts these findings beside rulesets, run history and credentials:
  **git-serious** (`git-serious-tap`, `req-git-serious-workflow-lint-findings`).
- The scanner itself: **zizmor** (zizmorcore, MIT), pinned exactly as a PyPI wheel in
  `pyproject.toml`. This plugin authors no audit.

## Read first

- `specs/spec-zizmor-v0.md` — the plugin specification: identity, philosophy, the binary shape
  (pinning, SBOM, FIPS, alerts), every requirement with acceptance criteria, models, edges, GRIFT.
- The CI/CD security prior art behind the "consume, do not rebuild" verdict:
  `git-serious-tap/docs/doc-git-serious-cicd-security-prior-art.md` §2.4.

## Scope (v0)

| Surface | State |
| --- | --- |
| Models | `zizmor__finding`, `zizmor__run` — planned (`req-zizmor-finding`, `req-zizmor-run`) |
| Edges | `PRODUCED`, `SCANNED`, `FLAGS_WORKFLOW`, `FLAGS_JOB` — planned |
| Collector | offline, derived, persona `auditor` — planned (`req-zizmor-collector`) |
| Trigger | own schedule + boot-record first light — planned (`req-zizmor-trigger`) |
| Pages / panels | `/zizmor`, `/zizmor/runs/<id>`, `/zizmor/findings/<id>` — planned |
| Boot records | corpus-fed in-package record + `ci/nightly.boot.json` — planned (`req-zizmor-record`) |

## Install and validate

Package-mode plugin: add it to a boot record's `install` section (git source, pinned tag) or
develop it editable with `spawn-session.sh <label> --boot-file <record> --dev-plugins zizmor,github_core`.

```bash
python -m tap_plugins.validate_plugin tap_plugin/zizmor          # structure (Django-free)
python -m tap.preboot --profile <profile>                        # conformance + dependency gates
manage.py plugins                                                # load report + dependency edges
```

Licensed under Apache-2.0 (see `LICENSE`). zizmor is MIT-licensed; the corpus bundle vendors a
subset of its integration test data with attribution (`req-zizmor-record`).
