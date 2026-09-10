"""Locating, version-gating and invoking the pinned zizmor binary.

Spec: specs/spec-zizmor-v0.md (req-zizmor-binary-2 Version Stamped, req-zizmor-collector).

Three facts about the binary are derived here and nowhere else:

**Where it is.** The wheel installs `zizmor` into the environment's script directory. A bare
`zizmor` does NOT resolve under every shell the app runs beneath, so `PATH` is a hint, not the
answer; the reliable locator is the interpreter's own script directory, because the interpreter
running this code is the one the wheel was installed against.

**What version it is.** Read from the binary at run time and compared to the version this
distribution pins. A mismatch aborts before any scan: a finding stamped with a version that did
not produce it is a false declaration, and it is the kind that survives review because the field
is present and well-formed.

**Which audits actually ran.** zizmor publishes no audit inventory — not through a flag, and not
through SARIF, whose `rules` array carries only the audits that fired (*observed* 2026-09-10 on
1.30.0: 7 rules for 7 fired audits, against 36 audits actually scheduled). Authoring the list
ourselves would be a second copy of somebody else's vocabulary, silently wrong one release later.
The binary does say it, at `-vv`: one `scheduling <audit> on <input>` line per audit it runs, and
one `skipping <audit>: <reason>` line per audit it refuses to run offline. Parsing those is
deriving the fact from its source rather than re-asserting it, and it fails CLOSED — a log format
that changes yields an empty audit set, which `ZizmorRun.validate()` refuses to accept on a
completed run. The exact-version pin is what bounds the brittleness: the format can only change
underneath us via a bump, and a bump re-runs these tests.

*Observed 2026-09-10, zizmor 1.30.0 offline:* 36 audits scheduled, 5 skipped for want of a GitHub
API token — `impostor-commit`, `ref-confusion`, `known-vulnerable-actions`, `stale-action-refs`,
`ref-version-mismatch`. (The spec's prose says four; the binary says five, and the binary is the
source of truth. Tracked as a spec correction.)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # noqa: S404 — invoking the pinned scanner IS this collector.
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from tap_plugin.zizmor.collectors.zizmor_collector.errors import ZizmorCollectorError

# The version this distribution pins in pyproject.toml. Duplicating the literal here would be the
# second copy that goes stale, so it is read from the installed distribution's own metadata:
# the requirement `zizmor==X.Y.Z` that pip/uv resolved is the pin, and it is machine-readable.
_PIN_RE: Final = re.compile(r"^zizmor\s*==\s*(?P<version>[^\s;,]+)")
_VERSION_RE: Final = re.compile(r"^zizmor\s+(?P<version>\S+)")
_SCHEDULING_RE: Final = re.compile(r"scheduling (?P<audit>[a-z0-9][a-z0-9-]*) on ")
_SKIPPING_RE: Final = re.compile(r"skipping (?P<audit>[a-z0-9][a-z0-9-]*): (?P<reason>.+?)\s*$")
_PARSE_FAIL_RE: Final = re.compile(r"failed to parse input: (?P<reason>.+?)\s*$")

# A scan of one workflow file is a bounded, offline, local-filesystem operation; 41 ms was the
# observed per-invocation cost (2026-09-10). The timeout exists so a pathological input cannot
# wedge a collection run forever, not as a performance budget.
SCAN_TIMEOUT_SECONDS: Final[int] = 120
VERSION_TIMEOUT_SECONDS: Final[int] = 30

PERSONA: Final[str] = "auditor"


@dataclass(frozen=True, slots=True)
class ScanResult:
    """One zizmor invocation over one workflow file."""

    ok: bool
    findings: list[dict[str, Any]]
    # Audits the binary reported scheduling / refusing, this invocation.
    audits_scheduled: frozenset[str]
    audits_skipped: dict[str, str] = field(default_factory=dict)
    # Populated only when `ok` is False: why this file could not be audited, in the binary's words.
    reason: str = ""


class ZizmorBinaryError(ZizmorCollectorError):
    """The pinned binary is missing, unreadable, or not the pinned version."""


def pinned_version() -> str:
    """The exact zizmor version this distribution declares as its dependency.

    Derived from the installed distribution metadata rather than authored a second time here.
    """
    from importlib.metadata import PackageNotFoundError, requires

    try:
        declared = requires("zizmor-tap") or []
    except PackageNotFoundError as exc:  # pragma: no cover — the plugin is always installed.
        raise ZizmorBinaryError(
            "zizmor-tap is not an installed distribution, so its zizmor pin cannot be read; "
            "refusing to scan with an unverifiable binary version."
        ) from exc
    for requirement in declared:
        match = _PIN_RE.match(requirement.strip())
        if match:
            return match.group("version")
    raise ZizmorBinaryError(
        "zizmor-tap declares no exact `zizmor==` pin; req-zizmor-binary-1 requires one, and "
        "without it there is nothing to hold the running binary against."
    )


def locate() -> Path:
    """The pinned binary's path.

    `PATH` is consulted first because that is where the wheel's script lands for an ordinary
    activation, and the interpreter's own script directory second because that is where it lands
    regardless of how the process was started. A bare `zizmor` is never assumed to resolve.
    """
    found = shutil.which("zizmor")
    if found:
        return Path(found)
    candidate = Path(sys.executable).resolve().parent / "zizmor"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    raise ZizmorBinaryError(
        f"the pinned zizmor binary is not on PATH and is not at {candidate}; the plugin's "
        "`zizmor==` dependency is declared but its wheel does not appear to be installed in "
        "this environment."
    )


def observed_version(binary: Path) -> str:
    """The version the binary reports about itself."""
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, path resolved above.
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ZizmorBinaryError(f"could not execute {binary} --version: {exc}") from exc
    if completed.returncode != 0:
        raise ZizmorBinaryError(f"{binary} --version exited {completed.returncode}: {completed.stderr.strip()[:400]}")
    match = _VERSION_RE.match(completed.stdout.strip())
    if not match:
        raise ZizmorBinaryError(f"could not read a version out of {completed.stdout.strip()[:200]!r}.")
    return match.group("version")


def verify_version() -> tuple[Path, str]:
    """Locate the binary and refuse to go further unless it is the pinned version.

    req-zizmor-binary-2: the binary that ran must be the one that was pinned.
    """
    binary = locate()
    pinned = pinned_version()
    observed = observed_version(binary)
    if observed != pinned:
        raise ZizmorBinaryError(
            f"pinned zizmor=={pinned} but {binary} reports {observed}; refusing to scan, because "
            "every finding this run would land carries a scanner_version that did not produce it."
        )
    return binary, observed


def scan(binary: Path, *, target: Path, cwd: Path) -> ScanResult:
    """Audit one workflow file, offline, and return its findings plus what the binary said it ran.

    `--no-exit-codes` is deliberate: without it zizmor encodes the highest finding severity in its
    exit status, so "found something" and "failed to run" become the same signal to a caller that
    only looks at the return code. With it, a non-zero status means the tool could not do its job,
    which is the distinction the SCANNED_WORKFLOW outcome depends on.
    """
    argv = [
        str(binary),
        "--offline",
        "--format",
        "json-v1",
        "--persona",
        PERSONA,
        "--no-progress",
        "--no-exit-codes",
        "--color",
        "never",
        "-vv",
        str(target),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell; `target` is sanitized.
            argv,
            capture_output=True,
            text=True,
            timeout=SCAN_TIMEOUT_SECONDS,
            cwd=str(cwd),
            check=False,
            # An offline audit needs no inherited credentials, and zizmor reads GH_TOKEN /
            # GITHUB_TOKEN / ZIZMOR_GITHUB_TOKEN from the environment when present. Handing it a
            # minimal environment is what makes "this collector needs no credential" true rather
            # than merely intended.
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(cwd), "ZIZMOR_OFFLINE": "1"},
        )
    except subprocess.TimeoutExpired:
        return ScanResult(
            ok=False,
            findings=[],
            audits_scheduled=frozenset(),
            reason=f"the scanner did not finish within {SCAN_TIMEOUT_SECONDS}s.",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ScanResult(ok=False, findings=[], audits_scheduled=frozenset(), reason=f"could not execute: {exc}")

    scheduled, skipped, parse_reason = parse_diagnostics(completed.stderr)

    if completed.returncode != 0:
        reason = parse_reason or (completed.stderr.strip().splitlines() or ["no diagnostic"])[-1]
        return ScanResult(
            ok=False,
            findings=[],
            audits_scheduled=scheduled,
            audits_skipped=skipped,
            reason=f"exit {completed.returncode}: {reason[:400]}",
        )

    try:
        parsed = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        return ScanResult(
            ok=False,
            findings=[],
            audits_scheduled=scheduled,
            audits_skipped=skipped,
            reason=f"the scanner exited 0 but its json-v1 output did not parse: {exc}",
        )
    if not isinstance(parsed, list):
        return ScanResult(
            ok=False,
            findings=[],
            audits_scheduled=scheduled,
            audits_skipped=skipped,
            reason=f"expected a json-v1 array of findings, got {type(parsed).__name__}.",
        )
    return ScanResult(ok=True, findings=parsed, audits_scheduled=scheduled, audits_skipped=skipped)


def parse_diagnostics(stderr: str) -> tuple[frozenset[str], dict[str, str], str]:
    """Pull the audit inventory and any parse failure out of one invocation's `-vv` stderr.

    Returns (scheduled audit ids, {skipped audit id: reason}, parse-failure reason or "").
    Unrecognised lines are ignored rather than guessed at: an empty scheduled set is a legible
    failure downstream, an invented one is not.
    """
    scheduled: set[str] = set()
    skipped: dict[str, str] = {}
    parse_reason = ""
    for line in stderr.splitlines():
        match = _SCHEDULING_RE.search(line)
        if match:
            scheduled.add(match.group("audit"))
            continue
        match = _SKIPPING_RE.search(line)
        if match:
            skipped[match.group("audit")] = match.group("reason")
            continue
        match = _PARSE_FAIL_RE.search(line)
        if match and not parse_reason:
            parse_reason = match.group("reason")
    return frozenset(scheduled), skipped, parse_reason
