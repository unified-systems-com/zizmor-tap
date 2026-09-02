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

## Running it

> **Status:** not installable yet. The two boot records below land with `req-zizmor-record`
> and the collector (`req-zizmor-collector`); this section is the front door they will open.

Two records ship inside the package, and the `--from` pointer fetches either straight from this
repository — the tap clone carries nothing zizmor-specific:

| Record | What it does | Credentials |
| --- | --- | --- |
| `zizmor` | Seeds the **corpus bundle** (known-bad workflows from zizmor's own test data) and fires the collector offline. Sixty seconds from nothing to `/zizmor` showing real findings. Kick the tires; nothing leaves the box. | none |
| `zizmor-live` | Installs github_core, fires its collector against **your** GitHub organization, then fires zizmor over what it collected. | the github_core credential (a read-only GitHub App) |

```bash
mkdir -p ~/tap-sessions
git clone https://github.com/unified-systems-com/tap.git ~/tap-sessions/main
cd ~/tap-sessions/main
scripts/spawn-session.sh zz --from git+https://github.com/unified-systems-com/zizmor-tap@vX.Y.Z#zizmor        # corpus, no credentials
scripts/spawn-session.sh zz --from git+https://github.com/unified-systems-com/zizmor-tap@vX.Y.Z#zizmor-live   # your org
```

You do not need the credential right before running the live record: the record *declares* what it
needs, the boot preflight names exactly what is missing or dead in seconds, and an AI assistant
attached to the session closes the gap — `/provision-secrets` reads the declaration, and
`create-github-app` (shipped by github_core) mints the least-privilege App from the collection
manifest and proves it end to end. The failure output is the setup guide.

**The easier way:** open an AI coding assistant in `~/tap-sessions/main` and say "run zizmor
against my organization". The `/get-started` skill drives the host prep and the spawn; the
provisioning skills drive the credential.

## Developing it

```bash
scripts/spawn-session.sh zz-dev --boot-file <this repo>/tap_plugin/zizmor/boot/zizmor.boot.json --dev-plugins zizmor,github_core
python -m tap_plugins.validate_plugin tap_plugin/zizmor          # structure (Django-free)
python -m tap.preboot --profile <profile>                        # conformance + dependency gates
manage.py plugins                                                # load report + dependency edges
```

Licensed under Apache-2.0 (see `LICENSE`). zizmor is MIT-licensed; the corpus bundle vendors a
subset of its integration test data with attribution (`req-zizmor-record`).
