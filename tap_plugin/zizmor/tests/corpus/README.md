# zizmor's own test corpus — vendored

These workflow files are copied verbatim from **zizmor's integration test corpus**,
`crates/zizmor/tests/integration/test-data/` at tag **v1.30.0** — the exact version this plugin
pins (`req-zizmor-binary-1`).

Upstream: https://github.com/zizmorcore/zizmor
License: MIT (see `LICENSE-zizmor` beside this file)

## Why these are here rather than written by us

They are the **oracle**. A corpus we authored would test our idea of what zizmor finds; zizmor's own
corpus tests what zizmor actually finds. Each file is named for the audit it demonstrates, which is
zizmor's declaration — not ours — of what should fire, so the expectation is not circular.

`neutral.yml` is the one that matters most: upstream ships it as a workflow with nothing wrong, so
it is the "scanned and genuinely clean" case. Without it, a collector that silently produced no
findings for every input would still pass every other assertion here.

`bad-yaml.yml` is `invalid/bad-yaml-2.yml` upstream — the unparseable input, so `parse-failed` is
exercised against a file zizmor itself considers broken.

## Updating

These move only when the `zizmor==` pin moves, and re-vendoring is a deliberate act that rides its
own PR — never a build step. A vendored corpus that regenerated itself would silently adopt whatever
upstream changed, which is precisely the drift this corpus exists to detect.
