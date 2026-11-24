# Changelog

## [0.2.1](https://github.com/unified-systems-com/zizmor-tap/compare/v0.2.0...v0.2.1) (2026-11-24)


### Features

* declare event time for every model (tap v0.4.7) ([3d416db](https://github.com/unified-systems-com/zizmor-tap/commit/3d416dbc80752c49399a33ae340e1f1b3d356432))
* declare event time for every model (tap v0.4.7) ([ca76684](https://github.com/unified-systems-com/zizmor-tap/commit/ca76684658ec6be568a4f964538ca193fb46d806))
* tap v0.4.9 — spine copies migration, format "1" documents ([5c94b3b](https://github.com/unified-systems-com/zizmor-tap/commit/5c94b3bd37a7de1af28ccdafefd4d8cff6bca3f7))
* tap v0.4.9 — spine copies migration, format "1" documents ([071dd2a](https://github.com/unified-systems-com/zizmor-tap/commit/071dd2a91716368fdeecd9a38c7e738ec3e60a31))

## [0.2.0](https://github.com/unified-systems-com/zizmor-tap/compare/v0.1.1...v0.2.0) (2026-11-16)


### ⚠ BREAKING CHANGES

* zizmor's findings, runs and edges carry git.host where they carried github.platform. A filter on the old key matches nothing.

### Bug Fixes

* **ci-record:** pin the dependency releases that carry their Dimension seeds ([26eb785](https://github.com/unified-systems-com/zizmor-tap/commit/26eb785ad17c136aac213e645e7256e0e3ee87a9))
* **ci-record:** pin the dependency releases that carry their Dimension seeds ([94aa66f](https://github.com/unified-systems-com/zizmor-tap/commit/94aa66fbe5951143a93c355837a3ab00d44ef92b))
* scope zizmor's rows by git.host; declare zizmor.scanner_version ([291dfd3](https://github.com/unified-systems-com/zizmor-tap/commit/291dfd3599247fa3f83b5d5ca243df54b969078e))
* the rename migration reverses for real; say why batch rows are not touched ([984701b](https://github.com/unified-systems-com/zizmor-tap/commit/984701b6ce09b49b62aef7f4e0189771e6c6753c))

## [0.1.1](https://github.com/unified-systems-com/zizmor-tap/compare/v0.1.0...v0.1.1) (2026-11-05)


### Bug Fixes

* **deps:** depend on github-core-tap and track the current cores ([7009960](https://github.com/unified-systems-com/zizmor-tap/commit/70099603ba2246f899e2e69fb9fdecc722082f22))
* **deps:** depend on github-core-tap and track the current cores ([2556919](https://github.com/unified-systems-com/zizmor-tap/commit/2556919a188c31dea5d1be33a5688eb94a521f9b))
* **manifest:** raise the core floor to 0.3.0 ([2379f96](https://github.com/unified-systems-com/zizmor-tap/commit/2379f96e7bded4881f74fbfa09c0c90dbd866506))
