# zizmor Plugin Specification

## Plugin Identity

| Field | Value |
| --- | --- |
| Slug | `zizmor` |
| Display name | TAP zizmor |
| Description | GitHub Actions workflow audits, consumed offline onto the grid — zizmor's findings beside the workflows, jobs, rulesets and credentials they concern. |
| Kind | Leaf plugin (not a `*_core` substrate): consumes github_core's vocabulary, consumed by git-serious. |
| Dist | `zizmor-tap` |
| Import namespace | `tap_plugin.zizmor` |
| Entry point | `zizmor = "tap_plugin.zizmor.apps:ZizmorConfig"` under `[project.entry-points."tap.plugins"]` |
| AppConfig | `tap_plugin.zizmor.apps.ZizmorConfig` (Django dotted path; `name` derived from the module path, `label`/`verbose_name` from the manifest) |
| Repo | `unified-systems-com/zizmor-tap`, standalone from the first commit (every plugin is evicted) |
| Dev workspace | `spawn-session.sh <label> --boot-file <record> --dev-plugins zizmor,github_core` |
| Collector | `ZizmorCollector` (`CollectorBase`), registry key `zizmor:zizmor` — derived and offline: reads workflow YAML github_core already landed, runs the pinned binary, lands findings. No forge access, no credential, no network. |
| Trigger | Own `schedule` node (GRIFT-seeded, user-editable) + boot-record `fire-collector` for first light — `req-zizmor-trigger` |
| Pages | `req-zizmor-page-landing`, `req-zizmor-page-run`, `req-zizmor-page-finding`; one requirement per panel type (`req-zizmor-panel-*`) |
| Persona | Fixed `auditor` in v0, recorded on every run and finding; configurable = `req-zizmor-persona` (Backlog, tap#308 / tap#310) |
| Boot records | `ci` (in-package, `req-boot-bootstrap-ci-record`) and `ci/nightly.boot.json`. The corpus proof is a TEST, not a seeded record — `req-zizmor-record` |

**Entry points**

| Route | Page | Panels mounted |
| --- | --- | --- |
| `/zizmor` | Landing | `zizmor_about`, `zizmor_findings_table`, `zizmor_runs_table` |
| `/zizmor/runs/<run_id>` | Run | `zizmor_run_summary`, `zizmor_run_detail` |
| `/zizmor/findings/<finding_id>` | Finding | `zizmor_finding_detail` |

Pages, panels and searches ship as one GRIFT document (`grift/pages.grift.json`). Every finding cell
in any table links to its finding page and every run cell to its run page; git-serious mounts
`zizmor_findings_table` on its lint-findings surface and inherits the links.

**Default dimensions** (on every plugin-owned node and edge)

| Dimension | Value | Why |
| --- | --- | --- |
| `github.platform`, `github.owner`, `github.repo`, `github.surface` | inherited from the workflow's github_core dimensions (`surface = "actions"`) | A finding is scoped exactly as the workflow it flags |
| `github.observation` | `"declaration"` | A finding is about the pipeline as *written* |
| `zizmor.scanner_version` | the version read from the binary at run time | Findings from two scanner releases are separate partitions and never merge into one fact |

## Philosophy

Workflow static analysis is a solved commodity. zizmor (zizmorcore; MIT; 41 audits; ~650 adopters
including GitHub itself; Trail of Bits hardened it against a 41,253-workflow corpus) does it better
than we ever will, so the prior-art survey's verdict (`doc-git-serious-cicd-security-prior-art.md`,
§2.4) was one word: consume. Re-implementing any of its audits is waste. What zizmor cannot do — and
what this plugin exists for — is put a finding *beside* the ruleset that requires the check, the run
history of the job it flags, and the credential the job can reach. That placement is git-serious's
whole contribution (`req-git-serious-workflow-lint-findings`); the finding itself is zizmor's.

Three consequences shape v0:

1. **The finding is data with provenance, never a verdict we author.** Every finding carries the
   scanner, its exact version, the audit ID, zizmor's own severity and confidence, and the location
   it reported. GUAC's discipline: origin / collector / justification / known-since on every
   assertion, so disagreement between scanners (CodeQL's Actions pack, poutine, later) is data.
2. **Run offline over what we already hold.** github_core's GraphQL config layer inlines every
   workflow file (`GithubWorkflow.configuration.raw_yaml`; *observed* 2026-09-02: 75 workflows for
   our org in one collection). zizmor accepts a directory of workflow files and `--offline`. So the
   collector needs no credential, makes no request, and its result is a pure function of grid state
   plus a pinned binary — reproducible and replayable.
3. **Three states, never two.** A workflow zizmor did not evaluate — because the online-only audits
   were skipped, because the YAML failed to parse, because the binary was absent — renders as *not
   observed by this scanner*, never as clean. Absence of a finding is not a finding of absence.

**Scope.** v0 is the first execution against our own organisation and the pages to read it. Everything
past that — the online audits, the three input kinds github_core does not collect, the compliance
bridge, fix mode, a second scanner — is a `Backlog` requirement below, not a non-goal (make-it-right
column). The gate between them and v0 is one fact: the plugin has to execute once before any of it
is real.

**Provenance markers.** Claims marked *observed* were measured on 2026-09-02; everything else is
*documented* from the sources named.

## Goals

| # | Name | Description |
| --- | --- | --- |
| 1 | Consume, Do Not Rebuild | Every finding on the grid is zizmor's, with zizmor's ID, severity, confidence and location; the plugin authors no audit. |
| 2 | Offline And Derived | The collector reads workflow YAML already on the grid and runs the pinned binary offline; no credential, no network, reproducible from grid state. |
| 3 | Provenance On Every Finding | Scanner, exact version, persona, audit ID, known-since and observed-at ride on each finding, and each run records which github_core collection it read. |
| 4 | Three States | Unevaluated workflows render as *not observed by this scanner*, never as clean. |
| 5 | Native Distribution | The binary arrives as the pinned PyPI wheel; pinning, SBOM, crypto-BOM and vulnerability alerts ride existing machinery, with the gaps named rather than papered. |
| 6 | Legible Runs | Every execution is a first-class node with its own page; every finding drills into its own page. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-zizmor-binary | [The Pinned Binary](#the-pinned-binary) | Proposed | Exact PyPI pin; honest `[fips]` declaration; SBOM/alert channels named with their gaps |
| req-zizmor-collector | [Offline Derived Collector](#offline-derived-collector) | Implemented | Materialize `raw_yaml` per repo → `zizmor --offline --format json-v1` → GRIFT batch |
| req-zizmor-trigger | [Own Schedule, With A Staleness Guard](#own-schedule-with-a-staleness-guard) | Implemented | Plugin-seeded `schedule` node fires `zizmor:zizmor` on its own cadence; a run names the github_core collection it read, and skips — creating no run node — while one is in flight |
| req-zizmor-record | [The Corpus Proof](#the-corpus-proof) | Implemented | The suite seeds workflow rows in-transaction, fires the collector offline, and asserts against zizmor's own corpus; fixture data never ships or seeds a live grid (ruled 2026-09-10) |
| req-zizmor-finding | [The Finding Node](#the-finding-node) | In Development | `zizmor__finding` with provenance fields; edges to run, workflow and job. A compliance-level node in disguise — see the implementation note |
| req-zizmor-run | [Runs Are First-Class](#runs-are-first-class) | In Development | One `zizmor__run` per execution; findings and scanned workflows hang off it; unevaluated = not observed by this scanner |
| req-zizmor-page-landing | [Page: Landing](#page-landing) | Implemented | `/zizmor` — about, findings table, runs table; every cell drills in |
| req-zizmor-page-run | [Page: Run](#page-run) | Proposed | `/zizmor/runs/<run_id>` — summary + detail of one run |
| req-zizmor-page-finding | [Page: Finding](#page-finding) | Implemented | `/zizmor/finding?finding_id=<id>` — one finding in full, joined to its job, action and run |
| req-zizmor-panel-coverage | [Panel: Coverage](#panel-coverage) | Implemented | What the latest run read and what it never did; the panel that stops a findings list reading as safety |
| req-zizmor-panel-about | [Panel: About](#panel-about) | Implemented | What zizmor is; version observed from the binary; persona; offline posture and skipped audits |
| req-zizmor-panel-findings-table | [Panel: Findings Table](#panel-findings-table) | Implemented | Latest run's findings with not-observed rows; filter by audit and severity; cells drill in |
| req-zizmor-panel-runs-table | [Panel: Runs Table](#panel-runs-table) | Implemented | Recent runs with counts and outcome; cells drill in |
| req-zizmor-panel-run-summary | [Panel: Run Summary](#panel-run-summary) | Proposed | One run's version, persona, source collection, coverage, counts, duration |
| req-zizmor-panel-run-detail | [Panel: Run Detail](#panel-run-detail) | Proposed | Every finding the run produced and every workflow it scanned with outcome |
| req-zizmor-panel-finding-detail | [Panel: Finding Detail](#panel-finding-detail) | Implemented | One finding in full, linked to its workflow, job and run |
| req-zizmor-online-audits | [Online Audits, Aligned To The Graph](#online-audits-aligned-to-the-graph) | Backlog | The four API-backed audits via github_core's auth seam; findings land on `github_action`/`USES_ACTION`; FIPS accounting becomes real |
| req-zizmor-input-kinds | [Actions, Dependabot And Pre-commit Inputs](#actions-dependabot-and-pre-commit-inputs) | Backlog | Pulled by github_core collecting three more file kinds |
| req-zizmor-persona | [Persona As A Collector Setting](#persona-as-a-collector-setting) | Backlog | Blocked on the collector-configuration channel (tap#308); until then `auditor` is fixed |
| req-zizmor-compliance-bridge | [Compliance Bridge](#compliance-bridge) | Backlog | Finding → compliance requirement edges (CICD-SEC-n, SLSA) via compliance_core |
| req-zizmor-fix-mode | [Fixes As Patches](#fixes-as-patches) | Backlog | zizmor's safe fixes surfaced as agent-applicable patches |
| req-zizmor-second-scanner | [A Second Scanner In The Same Shape](#a-second-scanner-in-the-same-shape) | Backlog | poutine / CodeQL Actions pack; scanner disagreement as data |

### The Pinned Binary
----
RID: `req-zizmor-binary`

Status: `Proposed`

The plugin's only Tier-0 runtime dependency is `zizmor==<exact>` from PyPI. The collector locates the
installed binary through the environment (the wheel installs it on `PATH` as `zizmor`), reads its
version at run time, and refuses to run when that version differs from the pinned one. The manifest
`[fips]` table declares `uses-nonvalidated`, naming the providers as the crypto-BOM scanner reports
them — `boringssl` (ring's BoringSSL-derived core) and `rust-aws-lc-rs` — with the offline-invocation
reason. The plugin records the verified upstream publisher identity and the state
of each supply-chain channel below.

#### Implementation

**Adopt native distribution — never roll our own package distribution.** zizmor is on PyPI as a
wheel (*observed* 2026-09-02: `zizmor 1.30.0`, `requires_python >=3.10`; manylinux x86_64 / aarch64
/ armv7l, musllinux, macOS x86_64 / arm64). Each wheel is one static binary
(`zizmor-1.30.0.data/scripts/zizmor`, 26.6 MB on manylinux_2_28 x86_64), a `RECORD`, the MIT license
— **and its own CycloneDX SBOM** (`zizmor-1.30.0.dist-info/sboms/zizmor.cyclonedx.json`, 400 KB,
PEP 770, 328 components) listing every Rust crate compiled in.

```toml
dependencies = ["zizmor==1.30.0"]
```

| Concern | How it is handled | Status |
| --- | --- | --- |
| **Pinning** | Exact `==` in `pyproject.toml`; `uv.lock` in the plugin repo; the boot record's install pin (`zizmor-tap@vX.Y.Z`) pins the closure. No cargo, no GitHub-release download, no vendored binary, no checksum we author twice. | Existing |
| **Release SBOM** | `plugin-release-sbom.yml` runs pinned Syft over our wheel: `zizmor` appears as `pkg:pypi/zizmor@1.30.0`. | Existing |
| **Crate-level SBOM** | *Verified 2026-09-02 (observed):* the pinned Syft (`anchore/syft:v1.51.0`) does **not** ingest the embedded PEP 770 document — a directory scan of the unpacked wheel yields `pkg:pypi/zizmor@1.30.0`, six file entries and zero crate components, with and without `--select-catalogers +sbom-cataloger` (upstream: anchore/syft#737, open). The release lane therefore merges the embedded document explicitly as a nested component keyed to the exact wheel version — a one-time addition to `scripts/sbom/plugin_release.py` (tap#302). | Verified: not ingested → the release lane merges it |
| **Deployed closure** | The wheel installs at boot into the container venv (git-source install of the plugin pulls its deps). The boot record is the BOM of what actually runs. | Existing |
| **Crypto BOM / FIPS** | *Observed* in zizmor's `Cargo.lock`: `ring`, `aws-lc-rs`/`aws-lc-sys`, `rustls`, `rustls-platform-verifier`, `reqwest` — two non-OpenSSL providers, for TLS. AWS-LC has a FIPS 140-3 validated module, but it ships as a separate crate (`aws-lc-fips-sys`, selected by aws-lc-rs's `fips` feature); zizmor's `Cargo.toml` pulls `reqwest` with default features, i.e. the non-FIPS `aws-lc-sys`, and `ring` (never validated) is linked too. **The wheel's binary is not the validated module even though the library it embeds is validatable.** Manifest: `[fips] status = "uses-nonvalidated"`, `providers = ["boringssl", "rust-aws-lc-rs"]` (the scanner reports ring's BoringSSL-derived core as `boringssl`), `reason = "TLS for zizmor's online audits; this plugin invokes zizmor --offline, so the providers are present but never execute a security operation. A FIPS deployment waives per plugin in the boot profile."` A false `compatible` fails conformance; the honest declaration passes (`req-fips-crypto-bom-conformance-2`). **Scan reach, observed 2026-09-02:** `validate_plugin`'s authoring-time scan does NOT fingerprint a declared dependency's wheel (it reports the declaration as "conservative"), but the **boot-time gate does** — the first CI boot aborted with `crypto-bom: FIPS mode is on but 2 crypto provider(s) are non-validated and un-waived: boringssl@…/bin/zizmor, rust-aws-lc-rs@…/bin/zizmor`. So every FIPS-on record that installs this plugin carries two operator `fips_waivers` (plugin `zizmor`, providers `boringssl` and `rust-aws-lc-rs`, reason: offline-only invocation, re-decide when online audits ship); the manifest names the providers as the scanner reports them. | Declared + waived per record; the gate reaches the wheel |
| **Vulnerability notification** | (a) Dependabot alerts are enabled on every plugin repo (*observed*: 204 on `vulnerability-alerts`), so a GitHub Advisory against PyPI `zizmor` alerts the repo. (b) Renovate has `pep621` + `osvVulnerabilityAlerts` enabled but `RENOVATE_REPOSITORIES` names tap alone — plugin repos get no bump PRs (tap#303, under the plugin-baseline issue #269). zizmor releases every 2–3 weeks (*observed*: v1.26.1 → v1.30.0, 2026-06-21 → 2026-08-30); the bump PR is the release notification. (c) Trivy nightly scans images; a boot-installed wheel is not in the image — the boot-record BOM against OSV is the closing move, parked with the dependency-defense thread. | (a) existing; (b) tap#303; (c) parked |
| **Attestation** | The plugin's own wheel is attested by the release lane (SLSA provenance + SBOM predicates). zizmor's PyPI wheels are published via Trusted Publishing from `zizmorcore/zizmor` — verify on the first pin bump and record the accepted upstream identity here. | Verify once |

Rejected shapes: fetching the GitHub release binary at install (an unpinned network fetch in the boot
path plus a hand-authored checksum — presence, not correctness); baking the binary into the tap-web
image (core carrying a product's dependency, 27 MB in every instance that never runs it).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-binary-1 | Exact Pin | Proposed | `pyproject.toml` pins `zizmor==X.Y.Z`; `uv.lock` resolves it; `validate_plugin --strict` passes with the honest `[fips]` declaration. | |
| req-zizmor-binary-2 | Version Stamped | Implemented | Every run and finding carries the binary's reported version (`zizmor --version`), which equals the pinned version, else the collector aborts before scanning. | The binary that ran is the one that was pinned. |
| req-zizmor-binary-3 | SBOM Presence | Proposed | The plugin's release SBOM lists `pkg:pypi/zizmor@X.Y.Z` and carries the embedded crate-level document as a nested component. | |
| req-zizmor-binary-4 | Alert Channel Proven | Proposed | A Dependabot alert or Renovate PR fires for a zizmor advisory or release on the plugin repo — demonstrated once with a real bump, not assumed from configuration. | The Renovate half is tap#303. |

### Offline Derived Collector
----
RID: `req-zizmor-collector`

Status: `Proposed`

`ZizmorCollector` reads, per repository on the grid, each `GithubWorkflow.configuration.raw_yaml`,
materializes them into a per-run scratch tree (`<scratch root>/<run id>/<repo>/.github/workflows/<path>`, never a fixed or cwd-relative location — concurrent runs cannot collide), refusing any workflow `path` that is absolute, contains `..`, or resolves outside its repository's scratch directory, then invokes
`zizmor --offline --format json-v1 --persona auditor` over it, and lands one GRIFT batch: the run
node, the findings, edges from each finding to its workflow (and job when the finding's location
names one), and the run's `SCANNED_WORKFLOW` edges with per-workflow outcomes. The scratch tree lives for the
duration of one subprocess call and is removed on exit. The persona is fixed at `auditor` in v0 and recorded on the run. The collector never contacts a
network and declares no `required_secrets`. Manifest `depends_on` names `github_core` (Tier 1: it imports
github_core's models to resolve workflow and job endpoints).

#### Implementation

Three things the design had to settle once the binary was read rather than assumed
(*observed* 2026-09-10, zizmor 1.30.0, first light against the 24-repository org collection:
155 findings from 77 evaluated workflows, 40 `no-yaml`, 0 parse-failed, 0 refused).

**One invocation per workflow file, not one per repository.** A scan costs ~41 ms, so 77 workflows
cost about three seconds — cheap enough to buy exact attribution. A single invocation over the
whole tree would leave `parse-failed` un-attributable to a file, and the per-workflow
`SCANNED_WORKFLOW` outcome is the entire basis for "unevaluated is not clean". `--no-exit-codes`
is passed deliberately: without it the exit status encodes the highest finding severity, so
"found something" and "could not run" become the same signal.

**The audit set is derived, not authored.** zizmor publishes no audit inventory — not through a
flag, and not through SARIF, whose `rules` array carries only the audits that FIRED (7 rules for 7
fired audits, against 36 actually scheduled). An authored list would be a second copy of somebody
else's vocabulary, wrong one release later and wrong in the reassuring direction. The binary does
say it at `-vv`: one `scheduling <audit>` line per audit run, one `skipping <audit>: <reason>` per
audit refused offline. The collector parses those, and fails CLOSED — an unparseable log yields an
empty audit set, which `ZizmorRun.validate()` refuses on a completed run. The exact-version pin
bounds the brittleness: the format can only move under a bump, and a bump re-runs the tests.

**A finding is keyed on its assertion, including the fragment.** Keying on the run would mint a
fresh node every six hours for a defect nobody touched; keying on row and column would report a
whole file as newly-defective after a reformat. The key is (workflow, audit, symbolic route,
persona, narrowed fragment) — the fragment is load-bearing, because four `template-injection`
findings on one step share audit, route and persona, and two of them share a row and column as
well. Where the same expression genuinely repeats in one block, an occurrence suffix separates
them; that is recorded at info, and its cost is named: editing that block re-identifies the later
occurrences within it.

A job-level `uses:` pointing into a repository's `.github/workflows/` is a reusable WORKFLOW call,
not an action, and github_core correctly mints no `github_action` node for one. It is classified
as such rather than reported as an action that could not be found.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-collector-1 | Pure Function Of Grid State | Proposed | Two runs over unchanged workflow rows with the same pinned binary produce identical finding sets; no network access is attempted (asserted with egress blocked in the test). | |
| req-zizmor-collector-2 | Our Org, First Light | Implemented | Against the viz session's collected org (75 workflows, *observed*), the collector completes and lands findings whose audit IDs appear in zizmor's documented audit list. | The gate for every Backlog requirement. |
| req-zizmor-collector-3 | Scratch Is Ephemeral And Isolated | Implemented | The scratch tree is per run under the scratch root; two concurrent runs never share a path; after a run (or a failed run) no materialized file remains. | |
| req-zizmor-collector-4 | Paths Sanitized | Implemented | A workflow row whose `path` is absolute, contains `..`, or escapes its repository's scratch directory is skipped and recorded as `skipped` with the reason, and nothing is written outside the scratch tree. | Path traversal is not a hypothetical: `path` comes from collected data. |

### Own Schedule, With A Staleness Guard
----
RID: `req-zizmor-trigger`

Status: `Proposed`

The collector runs on its **own schedule**: this plugin's GRIFT
(`tap_plugin/zizmor/grift/schedule.grift.json`, declared under `[grift]`) seeds a tap_cares
`schedule` node targeting `zizmor:zizmor` (default cron `23 */6 * * *`, off the hour so it does not
pile onto the top-of-hour scheduler tick; user-editable, since `Schedule` is user-creatable per
`req-tap-cares-scheduler-model-6`).

The schedule is owned by this plugin rather than by a consumer — a deliberate departure from the
estate norm that the *consumer* declares a collector's schedule (samsite owns aws_core's,
git-serious owns github_core's). The reason is that the finding set is a property of the scanner and
its pin, not of any one product's page: a zizmor bump changes what is true here even when no
workflow changed, and no consumer is positioned to know that. Because the schedule is independent of github_core's collection, the run guards its own
freshness: it records the github_core `collection_job` (and batch) whose rows it read, and a fire
that finds a github_core collection job active is finalized as *skipped* with that reason rather than
scanning rows mid-write.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-trigger-1 | Seeded Schedule Fires | Implemented | After seeding, the schedule node exists with the default cron, and a tick at a matching slot creates a `ScheduleFire` that runs the collector. | |
| req-zizmor-trigger-2 | Fires Unattended | Implemented | A scheduler tick at a matching slot produces a `ScheduleFire` (`TRIGGERED`), a `CollectionJob` that reaches `SUCCESSFUL`, and a run node carrying its counts — *observed* 2026-09-10: 155 findings from 77 evaluated workflows, outcome `ok`. | Re-scoped from the withdrawn corpus boot record (`req-zizmor-record`) to the schedule itself, which is what actually fires. A schedule that exists but has not been seen firing is a declaration that is false until proven. |
| req-zizmor-trigger-3 | Skips While Upstream Writes | Implemented | With a github_core collection job active, a scheduled fire finalizes as skipped naming that job; no run node is created. | |
| req-zizmor-trigger-4 | Source Recorded | Implemented | Every run names the github_core collection job it read. | Provenance, not only timing. |

### The Corpus Proof
----
RID: `req-zizmor-record`

Status: `Implemented`

The offline collector is a pure function of grid state, so it can be proven end to end with no
credential and no network — **in the test suite**, against zizmor's own corpus as the oracle.

The corpus is a curated subset of **zizmor's own integration corpus**
(`crates/zizmor/tests/integration/test-data/` at the pinned tag, MIT, vendored with attribution in
`tap_plugin/zizmor/tests/corpus/`). Upstream groups those files per audit and names each for the
audit it demonstrates, so the expectation is the scanner project's declaration rather than a
snapshot of our own output played back to us. Two entries matter as much as the known-bad ones:
`neutral.yml`, upstream's known-GOOD workflow, and `invalid/bad-yaml-2.yml`, which zizmor itself
cannot parse.

The collector's input is `GithubWorkflow` rows, which on a real grid are github_core's observations.
The test creates them through the service layer inside the test transaction, where they roll back.

**Ruled 2026-09-10 (George): this is a test, and it is built as one.** The earlier shape — an
in-package boot record seeding a `grift/corpus.grift.json` bundle of synthetic workflow nodes, fired
at spawn — is withdrawn, for two reasons. First, a seeded corpus node on a live grid is
indistinguishable from one github_core actually observed; wanting a "this row is synthetic"
dimension to make that safe was the signal that the data belonged in a test, not in the product.
Second, it would not have proven anything anyway: plugin CI's boot-and-test leg does not run
population (`manage.py boot` runs at spawn time only), so the *test* was always doing the work and
the bundle was riding along.

The corpus **does** ship in the wheel, as test data — *verified* 2026-09-10 by building the wheel
and listing it: all 15 files plus the licence and the test that reads them. That is deliberate and
follows the estate convention that a plugin's tests ride in its wheel, so an installed plugin can
prove itself (`pytest --pyargs tap_plugin.zizmor`) and an agent has the corpus to reason from. What
fixture data never does is **seed a live grid**: it is not a GRIFT bundle, no boot record imports
it, and nothing puts a synthetic node on the spine where it would be indistinguishable from an
observed one. (An earlier draft of this section claimed the corpus "does not ship in the wheel",
which was simply false — the distinction that matters is shipped-as-test-data versus
seeded-as-product-data.)

This does not withdraw the in-package `ci` boot record, which exists for a different reason
(`req-boot-bootstrap-ci-record`) and seeds nothing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-record-1 | Oracle Agrees | Implemented | Every vendored corpus workflow produces the audit upstream named its file for, asserted in one report so a version bump shows the whole delta at once. | zizmor's own naming is the oracle; a corpus we authored would test our idea of the scanner. |
| req-zizmor-record-2 | Clean Is Not Silence | Implemented | Upstream's known-good workflow yields zero findings AND an `evaluated` coverage edge. | Without this, a collector that produced nothing at all would pass every other assertion. |
| req-zizmor-record-3 | The States Stay Apart | Implemented | The unparseable entry is `parse-failed` with a reason, the YAML-less row is `no-yaml` with a reason, and every seeded workflow carries exactly one coverage edge. | The three-states rule, mechanized. |
| req-zizmor-record-4 | Runs In CI | Implemented | The suite runs offline, with no credential and no network, in plugin CI's boot-and-test leg. | |
| req-zizmor-record-5 | Re-vendoring Is Deliberate | Proposed | The corpus moves only when the `zizmor==` pin moves, and re-vendoring rides its own PR — never a build step. | A corpus that regenerated itself would silently adopt whatever upstream changed, which is the drift it exists to detect. |
| req-zizmor-record-6 | No Unexpected Findings Either | Implemented | The COMPLETE audit set per corpus file is recorded and asserted, so an extra or misattributed finding fails as loudly as a missing one. | Restores the "no missing, no extra" strength of the withdrawn criterion, which the first draft of this test silently dropped to "the named audit fired". |
| req-zizmor-record-7 | Provenance Is Checkable | Implemented | `tests/corpus/provenance.json` records each file's upstream git blob SHA at the pinned tag, and a test recomputes it offline. | Byte-identity with upstream becomes a fact a reader can re-derive against github.com, not a claim in a README — and a corpus file edited locally to make a test pass is caught. |

**Settled on first build:** nothing forbids a plugin seeding another plugin's node type — a
`github_core__github_workflow` written by zizmor imports cleanly through the registry-resolved
importer (*observed* 2026-09-10). The type-ownership guard does not object. It is not done anyway,
per the ruling above: the constraint that mattered was honesty about fabricated data, not
permission.

### The Finding Node
----
RID: `req-zizmor-finding`

Status: `In Development`

A typed node `zizmor__finding` (BaseModel, table-prefixed per type ownership) carrying: `audit_id`,
`audit_url`, `severity`, `confidence`, `persona`, `scanner_version`, `summary`, `location` (path,
row, column, symbolic route, job key, step index, and the `feature` text as reported), `fixes`
(zizmor's list of title + disposition safe/unsafe), the raw finding JSON, `tags` (JSON: unresolved job key, `uses` string, secret names and other data-carried facts that have no node yet), `known_since` (first
observation) and `observed_at`. Edges: `PRODUCED_FINDING__zizmor` from its run; `FLAGS_WORKFLOW__zizmor`
(finding → `github_workflow`) always; `FLAGS_JOB__zizmor` (finding → `workflow_job`) when the
location resolves to a declared job; `FLAGS_ACTION__zizmor` (finding → `github_action`) when the
finding is about a `uses:` reference whose action is on the grid. Naming follows the vocabulary corpus's edge rules and the
SPDX-first check.

#### Implementation

**A compliance-level node in disguise (George, 2026-09-02).** `zizmor__finding` is a scanner's
assertion about an asset — the same shape compliance_core's `finding` bridges to a requirement. For
the make-it-work phase a scanner-shaped node is the decision. The implementation records, in the
model's docstring and its domain article, that surfacing it *beside other findings* (poutine, CodeQL,
git-serious's conjunction findings, compliance findings) is an open design that
`req-zizmor-compliance-bridge` and `req-zizmor-second-scanner` will force — and it must not paint
itself into a shape only zizmor can occupy: no zizmor-only field names where a scanner-neutral one
exists (`severity`, `confidence`, `scanner_version`, `location`, `fixes` are neutral; `audit_id` is
zizmor's vocabulary and is kept as the neutral `rule_id` with `audit_id` in tags if the second scanner
arrives).

**Endpoints, checked against the corpus (`spec-github-core-vocabulary.md`) and the grid as
collected 2026-09-02:**

| Endpoint | State | v0 handling |
| --- | --- | --- |
| `github_workflow` | built, on the grid | `FLAGS_WORKFLOW__zizmor` always |
| `workflow_job` | built (self tier) | `FLAGS_JOB__zizmor` when the location resolves |
| `github_action` + `USES_ACTION` (`{declared_ref, pin_kind, is_pinned, resolved_sha, resolution, step_indexes}`) | **built** — github_core v0.6.0; *observed* 2026-09-10: 19 `github_action` nodes on a real org collection | Nine audits are about `uses:` references (`unpinned-uses`, `stale-action-refs`, `ref-confusion`, `impostor-commit`, `known-vulnerable-actions`, `typosquat-uses`, `archived-uses`, `superfluous-actions`, `forbidden-uses`). Attaching them to the workflow alone loses the join the conjunction feature needs. The endpoint landed, so `FLAGS_ACTION__zizmor` lands with the rest of the edges rather than waiting (George, 2026-09-10). The node is keyed on the action path with the ref STRIPPED (`identity.github_action_id`), so the finding's reference rides the edge; `pin_kind` / `is_pinned` / `resolved_sha` stay github_core's facts and are never re-derived here. |
| `actions_secret` | proposed, **not built** | Secrets audits name secrets by string in `tags` until the node exists. |
| step | corpus ruling: a field, not a node | zizmor reports step indices; the finding keeps them in `location`. A finding needs the job as its endpoint; the ruling holds. |

zizmor exposes **no parse** — no dump or collect-only mode; its model crates are Rust-only — so the
grid's shape stays github_core's parse. Vocabulary comes from collection, findings from scanners;
never a shape derived from the absence of a finding.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-finding-1 | Provenance Complete | Implemented | Every landed finding has non-empty `audit_id`, `severity`, `confidence`, `scanner_version` and `observed_at`, an edge from its run, and an edge to exactly one workflow. | |
| req-zizmor-finding-2 | Job Resolution Honest | Implemented | A finding whose location names a job that exists on the grid gets `FLAGS_JOB`; one whose job cannot be resolved gets no job edge and records why in `tags`. | |
| req-zizmor-finding-3 | Neutral Shape Recorded | Proposed | The model docstring and domain article carry the compliance-node note and name the two Backlog requirements that will force the design. | |

### Runs Are First-Class
----
RID: `req-zizmor-run`

Status: `In Development`

Each collector execution lands one `zizmor__run` node: scanner version, persona, audit set,
started/finished, the github_core collection job it read, the repositories and workflows it covered,
per-workflow outcome (`evaluated` / `parse-failed` / `skipped`), and finding counts by audit and
severity. Findings hang off the run that produced them (`PRODUCED_FINDING__zizmor`, run → finding) and the
run records what it scanned (`SCANNED_WORKFLOW__zizmor`, run → workflow, with the outcome on the edge). A
workflow with no `SCANNED_WORKFLOW` edge from the current run renders as *not observed by this scanner* in
every consumer. The four online-only audits are recorded as `skipped` on every v0 run.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-run-1 | Not Scanned Is Visible | Proposed | Remove one workflow's `SCANNED_WORKFLOW` edge from the current run; the findings table shows it as *not observed by this scanner*, not as clean. | The three-states rule, mechanized. |
| req-zizmor-run-2 | Counts Match | Implemented | A run's recorded finding counts equal the findings reachable from it by `PRODUCED_FINDING`; a mismatch fails the collector's own post-check. | Presence is not correctness. |

### Page: Landing
----
RID: `req-zizmor-page-landing`

Status: `Proposed`

`/zizmor` — the plugin's entry point. Mounts `zizmor_about` (`req-zizmor-panel-about`),
`zizmor_findings_table` (`req-zizmor-panel-findings-table`) and `zizmor_runs_table`
(`req-zizmor-panel-runs-table`), in that order; built with the add-page skill; page entity, layout
and `USES_PANEL` edges ship in `grift/pages.grift.json`. Every finding cell links to its finding
page and every run cell to its run page. Reached from the site navigation and by direct URL.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-page-landing-1 | Renders With Four Panels | Implemented | `/zizmor` resolves and renders about, findings, coverage and runs in order with the seeded layout — *observed* 2026-09-10: page 200, every panel endpoint 200 with real data. | Four, not three: coverage was added (`req-zizmor-panel-coverage`) because a findings table alone cannot tell the truth. |
| req-zizmor-page-landing-2 | Drill-In | Proposed | One click from the landing page reaches a run page and one click reaches a finding page. | |

### Page: Run
----
RID: `req-zizmor-page-run`

Status: `Proposed`

`/zizmor/runs/<run_id>` — one execution. Page variable `run_id`; mounts `zizmor_run_summary`
(`req-zizmor-panel-run-summary`) and `zizmor_run_detail` (`req-zizmor-panel-run-detail`). Reached
from any run cell. An unknown `run_id` renders a not-found state, never an empty page.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-page-run-1 | Resolves The Run | Proposed | With a valid `run_id` both panels render that run; with an unknown id the page says so. | |
| req-zizmor-page-run-2 | Drill-In To Findings | Proposed | From the run page, one click reaches any finding the run produced. | |

### Page: Finding
----
RID: `req-zizmor-page-finding`

Status: `Implemented`

`/zizmor/finding?finding_id=<id>` — one finding. Page variable `finding_id`; mounts
`zizmor_finding_detail` (`req-zizmor-panel-finding-detail`). Reached from the audit cell of every
row on the findings table; joins out to the workflow, the job and the referenced action, and back to
the producing run.

**The URL is a query parameter, not a path segment** — a correction to this spec's original
`/zizmor/findings/<finding_id>`. TAP pages take page variables from the query string
(`request.GET`), the way github_core's repository page takes `?repository_entity_id=`; there is no
path-variable mechanism to use. Recorded because the original form reads plausible and would be
copied.

The panel is deliberately more than a field dump. A finding on its own is a lint result; what makes
it a *risk statement* is context the grid holds and the scanner cannot, because zizmor reads one
file: which job the flagged line runs in, **what that job is permitted to do**, what runner it lands
on, and which pin the reference actually carries. Those joins are the page's reason to exist. An
unknown or malformed id renders a not-found state, never an empty page reading like a finding with
nothing in it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-page-finding-1 | Resolves The Finding | Implemented | With a valid `finding_id` the detail panel renders that finding; with an unknown id the page says so. | |
| req-zizmor-page-finding-2 | Links Out | Implemented | The workflow, job (when resolved) and run links resolve to their pages. The workflow link is built from `panel.config.workflow_page_template` (`{full_name}` / `{path}` / `{workflow_id}` placeholders; the instance names the page) and rendered ONLY when that Page exists on the grid — never a dead link. | zizmor-tap#31; the shipped instance template is `/github_core/workflow?workflow_id={workflow_id}` |

### Panel: About
----
RID: `req-zizmor-panel-about`

Status: `Proposed`

`zizmor_about` (info-window panel type): what zizmor is and does, the audit families it covers, the scanner version and persona **as recorded on the latest run node** (the collector reads the binary once at run start and records it; the panel never invokes the binary), the offline posture and the five audits it therefore skips (read from the run node, which derives them from the binary), and links to zizmor's audit documentation. Every fact on it is read from the grid (the latest `zizmor__run`) or the binary — nothing is typed into the panel.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-panel-about-1 | Version From The Run | Proposed | The version and persona shown equal the latest run's recorded values; with no run yet, the panel says so rather than showing a default. | Derive, don't declare. |
| req-zizmor-panel-about-2 | Skipped Audits Named | Proposed | The four offline-incapable audits are listed as skipped with the reason. |  |

> **Known gap, named not hidden (zizmor-tap#27):** the findings table lists every finding ever
> observed, not the current state. The collector never tombstones, so a finding that has since been
> FIXED still renders. Scoping the table to the latest run would be worse — a workflow that run could
> not read (`no-yaml`, `parse-failed`) would silently lose everything previously known about it. The
> correct fix is well-founded tombstoning: absence is admissible as evidence exactly on workflows the
> run actually evaluated.

### Panel: Coverage
----
RID: `req-zizmor-panel-coverage`

Status: `Implemented`

`zizmor_coverage` — the four `SCANNED_WORKFLOW__zizmor` outcomes for the latest run, with counts,
the reason recorded for every non-evaluated one, and a capped list of the workflows in each.

**Why this panel exists at all.** A findings table cannot tell the truth on its own: it renders a
workflow nobody scanned identically to one that came back clean. That is not a rare edge —
*observed* 2026-09-10 on the real organisation, **40 of 117 workflows carried no `raw_yaml`**, so a
third of the estate had never been read while the page would have shown a confident list of 155
findings. The panel is mounted directly beneath the findings table for the same reason: coverage one
click away is coverage nobody opens.

It also reports workflows the run never reached at all — on the grid, but carrying no edge from this
run. That state is distinct from every outcome, and invisible otherwise, because a run cannot record
an outcome for something it never considered.

#### Implementation

A custom panel type rather than a standard table instance, for one concrete reason: the standard
table renders NODE results (`spec-web-panels-standard-table.md` defers edge-centric result sets to a
future variant), while `outcome` and `reason` live on the edge. Filed as tap#418; when that lands
this collapses into a standard table instance. The `unknown` tone is amber rather than grey on
purpose — a workflow the scanner never read is not a neutral fact and must not read as one.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-panel-coverage-1 | Unread Is Counted | Implemented | Every non-`evaluated` outcome is counted and shown with the reason recorded on its edge. | |
| req-zizmor-panel-coverage-2 | Unread Comes First | Implemented | The outcomes whose findings are UNKNOWN render above the scanned one. | Reading order is the message. |
| req-zizmor-panel-coverage-3 | Never Considered Is Visible | Implemented | Workflows on the grid with no coverage edge from this run are reported separately from every outcome. | The state a run cannot record for itself. |
| req-zizmor-panel-coverage-4 | Silence Is Not Clean | Implemented | With no run on the grid the panel says nothing has been measured, rather than rendering empty. | |

### Panel: Findings Table
----
RID: `req-zizmor-panel-findings-table`

Status: `Proposed`

`zizmor_findings_table` (table panel type over a Gryphon search): one row per finding from the latest run — repository, workflow, job (when resolved), audit, severity, confidence, summary — plus one row per workflow the latest run did **not** evaluate, rendered as *not observed by this scanner*. Filterable by audit and severity; sortable by severity. Every finding cell links to its finding page; workflow and job cells link to their github_core pages. This is the panel git-serious mounts.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-panel-findings-table-1 | Not-Observed Rows Present | Proposed | A workflow without a `SCANNED_WORKFLOW` edge from the latest run appears as a not-observed row, never as absent. | The three-states rule at the panel. |
| req-zizmor-panel-findings-table-2 | Filter Round-Trips | Proposed | Filtering by an audit ID shows exactly the findings with that ID and keeps the not-observed rows visible. |  |
| req-zizmor-panel-findings-table-3 | Mountable Elsewhere | Proposed | git-serious's lint-findings GRIFT mounts the panel type unchanged and the links resolve. | Serves `req-git-serious-workflow-lint-findings-1`. |

### Panel: Runs Table
----
RID: `req-zizmor-panel-runs-table`

Status: `Proposed`

`zizmor_runs_table` (table panel type): recent `zizmor__run` nodes, newest first — started, duration, scanner version, persona, source collection, repositories and workflows evaluated / parse-failed / skipped, finding counts by severity, outcome. Each run cell links to its run page.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-panel-runs-table-1 | Newest First, Drill-In | Proposed | The most recent run is the first row and its cell links to `/zizmor/runs/<id>`. |  |
| req-zizmor-panel-runs-table-2 | Counts Are The Run's | Proposed | Each row's counts equal the run node's recorded counts (which `req-zizmor-run-2` ties to the findings). |  |

### Panel: Run Summary
----
RID: `req-zizmor-panel-run-summary`

Status: `Proposed`

`zizmor_run_summary` (KPI/info panel type, page-variable `run_id`): one run's scanner version, persona, the github_core collection job it read, coverage (repositories and workflows evaluated / parse-failed / skipped), finding counts by audit and by severity, duration, and outcome.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-panel-run-summary-1 | Reads The Page Variable | Proposed | With `run_id` set, the panel shows that run; with an unknown id it says the run does not exist rather than rendering empty. |  |
| req-zizmor-panel-run-summary-2 | Coverage Adds Up | Proposed | Evaluated + parse-failed + skipped + no-yaml equals the number of `SCANNED_WORKFLOW` edges from the run. |  |

### Panel: Run Detail
----
RID: `req-zizmor-panel-run-detail`

Status: `Proposed`

`zizmor_run_detail` (table panel type, page-variable `run_id`): two tabs or sections — every finding the run produced (as in the findings table, scoped to this run) and every workflow it scanned with the per-workflow outcome from the `SCANNED_WORKFLOW` edge.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-panel-run-detail-1 | Scoped To The Run | Proposed | Only findings with a `PRODUCED_FINDING` edge from this run appear; the scanned-workflows list equals the run's `SCANNED_WORKFLOW` edges. |  |
| req-zizmor-panel-run-detail-2 | Drill-In | Proposed | Finding cells link to finding pages; workflow cells link to github_core pages. |  |

### Panel: Finding Detail
----
RID: `req-zizmor-panel-finding-detail`

Status: `Proposed`

`zizmor_finding_detail` (info-window panel type, page-variable `finding_id`): the finding in full — audit ID linked to its documentation, severity, confidence, persona, scanner version, the location with symbolic route, row/column and the `feature` text, available fixes with disposition, the raw finding JSON (collapsed), the workflow and job it flags linked onto their github_core pages, and the run that produced it linked to its page.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-panel-finding-detail-1 | Complete And Linked | Proposed | Every field named above renders when present, and the workflow, job (when resolved) and run links resolve. |  |
| req-zizmor-panel-finding-detail-2 | Fixes Rendered Honestly | Proposed | A finding with no fixes says so; one with fixes lists each with its safe/unsafe disposition. |  |

### Online Audits, Aligned To The Graph
----
RID: `req-zizmor-online-audits`

Status: `Backlog`

The **five** audits zizmor cannot run offline — *observed* 2026-09-10 by reading the binary's own
`-vv` registry diagnostics on 1.30.0, which name each one and why: `impostor-commit`,
`ref-confusion`, `known-vulnerable-actions`, `stale-action-refs` and `ref-version-mismatch`, each
"can't run without a GitHub API token". This corrects the prior-art survey's guess of four: it
named `typosquat-uses` and `archived-uses`, and BOTH of those in fact run offline (they are among
the 36 audits the binary schedules). The collector derives this set per run rather than carrying a
copy of it. They run with a token through **github_core's auth seam, never a second envelope**. Their findings
are about action references, so they must land on nodes and edges that exist on the grid by then:
`github_action` and `USES_ACTION` carrying `pin_kind`, `pinned_sha`, `declared_ref`,
`resolves_to_fork` — an impostor-commit finding points at the exact reference whose SHA does not
belong to the canonical repository, and `known-vulnerable-actions` attaches advisory identifiers to
the action version. Depends on: `github_action` built in github_core; `req-zizmor-collector-2`
observed. **FIPS becomes load-bearing here:** online means TLS executes inside the binary, so the
`uses-nonvalidated` declaration stops being "present but unreached"; a FIPS profile then needs a
`fips`-feature build of zizmor (not what PyPI ships) or the operator's per-plugin waiver.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-online-audits-1 | Lands On The Reference | Backlog | An impostor-commit finding has an edge to the `github_action` node and the `USES_ACTION` edge it concerns; none lands on the workflow alone. | |
| req-zizmor-online-audits-2 | One Credential | Backlog | The online run resolves its token through github_core's seam; the plugin declares no `required_secrets` of its own. | |

### Actions, Dependabot And Pre-commit Inputs
----
RID: `req-zizmor-input-kinds`

Status: `Backlog`

zizmor audits four input kinds; github_core collects one. When github_core fetches `action.yml` (the
defining side of `github_action`), `.github/dependabot.yml` and pre-commit config — the same GraphQL
config fetch, more paths — the collector materializes them beside the workflows, and the Dependabot
audits (`dependabot-cooldown`, `dependabot-execution`) and action audits gain inputs. Depends on:
github_core collection additions (friends tier).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-input-kinds-1 | Dependabot Audited | Backlog | A repository with a Dependabot config on the grid receives `dependabot-*` findings attached to that config's node. | |

### Persona As A Collector Setting
----
RID: `req-zizmor-persona`

Status: `Backlog`

`regular | pedantic | auditor` selectable per instance, recorded on the run and its findings;
`auditor` stays the default. **Blocked on tap#308**: TAP has no per-collector configuration
channel (`CollectorConfig` carries two IDs; the fire-collector step forbids per-collector config;
github_core routes its settings through its secret envelope, which this plugin does not have).
This plugin is the second concrete collector with a real shape requirement — the demand signal
the collector spec was waiting for — and it must consume the channel core provides rather than
invent a plugin-owned one that becomes a second pattern.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-persona-1 | Persona Recorded | Backlog | A run configured to `regular` records `regular` and its findings carry it; an invalid persona fails before scanning. | |

### Compliance Bridge
----
RID: `req-zizmor-compliance-bridge`

Status: `Backlog`

An edge from a finding to the compliance requirement(s) it evidences — OWASP CICD-SEC-n, SLSA
Source/Build, OSPS Baseline — reusing compliance_core's vocabulary rather than minting a rival. The
prior-art survey's §3.7 / §3.10 mapping is the seed data. This is what makes a finding an attestation
input rather than a lint line, and the first requirement that forces the neutral-shape question.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-compliance-bridge-1 | Tagged Findings Bridge | Backlog | A `template-injection` finding carries an edge to the CICD-SEC-4 requirement node when compliance_core's catalog holds it. | |

### Fixes As Patches
----
RID: `req-zizmor-fix-mode`

Status: `Backlog`

zizmor reports `fixes` per finding and can apply them. Surface a safe fix as a patch an agent can
propose against the repository — read-only from the grid's side; the write is a pull request the
operator's own tooling opens. Depends on: the agent-operable review surface (git-serious).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-fix-mode-1 | Safe Fix Rendered | Backlog | A finding with a safe fix renders the patch text; the plugin never writes to the forge. | |

### A Second Scanner In The Same Shape
----
RID: `req-zizmor-second-scanner`

Status: `Backlog`

poutine or CodeQL's Actions pack lands findings in the same node shape with `scanner` as a
dimension, so two scanners' disagreement on one workflow is a queryable fact. Whether that is a
sibling plugin or a scanner dimension on this one is decided when the second scanner is real.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-second-scanner-1 | Disagreement Queryable | Backlog | For one workflow, a query returns the findings per scanner side by side. | |

## Model catalog

| Model | Entity type | Category | Rationale |
| --- | --- | --- | --- |
| `ZizmorFinding` | `zizmor__finding` | finding | The unit zizmor emits, with provenance; a compliance-level node in disguise (see `req-zizmor-finding`). |
| `ZizmorRun` | `zizmor__run` | run | One per execution: version, persona, source collection, coverage, counts; the page's subject and the thing that makes absence honest. |

## Edge types

| Edge | From → To | Properties | Rationale |
| --- | --- | --- | --- |
| `PRODUCED_FINDING__zizmor` | run → finding | — | Which execution produced the finding. |
| `SCANNED_WORKFLOW__zizmor` | run → `github_workflow` | `{outcome: evaluated \| parse-failed \| skipped \| no-yaml, reason}` | Coverage; the absence of this edge is the not-observed state. `reason` is required for every outcome except `evaluated`. |
| `FLAGS_WORKFLOW__zizmor` | finding → `github_workflow` | — | Every finding locates a workflow file. |
| `FLAGS_JOB__zizmor` | finding → `workflow_job` | — | When the location names a declared job; the conjunction join. |
| `FLAGS_ACTION__zizmor` | finding → `github_action` | `{uses}` | When the finding is about a `uses:` reference. The action node is keyed with the ref stripped, so the reference rides the edge; the pin's MEANING stays github_core's `USES_ACTION` fact. **Unexercised on real data so far:** the 2026-09-10 first light produced 3 such edges, all from the `github-app` audit and NONE from the nine `uses:` audits the edge was built for — the org SHA-pins its third-party actions, so those audits mostly do not fire, and the 14 `unpinned-uses` findings that did fire all name reusable-WORKFLOW calls, which have no action node (see below). The justification stands for a grid carrying unpinned third-party actions; it should not be described as proven until a collection produces a non-zero count from those audits. |
| `FLAGS_CALLED_WORKFLOW__zizmor` | *(not built)* | — | **Gap, zizmor-tap#19.** A job-level `uses:` into a repository's `.github/workflows/` is a reusable WORKFLOW call, not an action, and github_core models that relationship as `CALLS_WORKFLOW` between workflows. A finding about an unpinned mutable reference to code that runs with our token therefore attaches today only to the file it was written in. Reusing `FLAGS_WORKFLOW` toward the called workflow is wrong: a finding would carry two, with no way to tell "the file I am in" from "the file I reference", and `req-zizmor-finding-1` requires exactly one. |

**Slugs.** `PRODUCED` and `SCANNED` were the names through 2026-09-02; both are bare verbs and fail
core's edge-naming guard (`<ACTION>_<OBJECT>`, `tap_plugins/validate/service.py` `_edge_naming_violations`,
verified failing 2026-09-10), so they carry their object nouns. A baseline exemption was rejected: a
brand-new edge does not get to start as debt.

**`no-yaml` is the fourth outcome.** The three named through 2026-09-02 missed the common case. On a
real org collection (24 repositories, *observed* 2026-09-10) **40 of 117 workflows carried no
`raw_yaml`** — collected by github_core, but with no body to scan. That is neither `skipped` nor
clean, and `ZizmorRun.workflows_no_yaml` already treated it as its own state.

## Reference data

Findings are collected, never seeded. Three GRIFT documents ship:

| Document | Contents | Seeded by |
| --- | --- | --- |
| `grift/pages.grift.json` | The three pages, six panel types and their searches | Every record |
| `grift/schedule.grift.json` | The collector's `schedule` node | Every record |
| `grift/corpus.grift.json` | The corpus account: known-bad workflows from zizmor's integration corpus as `github_workflow` nodes with `raw_yaml`, one invalid YAML, one empty repository, with expected audit IDs in `tags`. **Not grid_fixtures** — that plugin is neutral grid-mechanics vocabulary; this is github_core-typed domain data. | The in-package and CI records only — never a production profile |

## Icons

Two `currentColor` glyphs in `static/zizmor/icons/`: `zizmor-finding` and `zizmor-run`. Workflow and
job icons on the far side of the edges are github_core's.
