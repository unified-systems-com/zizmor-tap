"""The per-run scratch tree: sanitizing collected paths, and materializing YAML to disk.

Spec: specs/spec-zizmor-v0.md (req-zizmor-collector-3 Scratch Is Ephemeral And Isolated,
req-zizmor-collector-4 Paths Sanitized).

Both the repository's `full_name` and the workflow's `path` are COLLECTED DATA — they arrived
from an external API and were stored verbatim, which is correct of the collector that stored
them and dangerous here, because this is the module that turns them into filesystem paths. A
workflow path of `../../../../etc/cron.d/x` is a write outside the tree with the process's own
privileges. Path traversal is not hypothetical when the string came from someone else.

The defence is layered deliberately, because each layer catches what the others miss:

1. **Reject the shapes that are never legitimate** — empty, absolute, a `..` segment, a NUL or
   newline, a Windows drive or UNC prefix, a `full_name` that is not exactly `owner/repo`.
   Cheap, and it names the rule that refused in terms a reader can act on.
2. **Resolve and re-check containment** — the authoritative test. Symlinks, case-folding
   collisions and encodings that step 1 cannot enumerate all end up somewhere, and the only
   question that matters is whether that somewhere is inside this repository's directory.
3. **Never follow a symlink on write** — the file is opened `O_NOFOLLOW` via exclusive creation
   into a directory tree we built ourselves this run.

A refused row is `skipped` with the reason, never silently dropped: a workflow that vanished from
the scan without a SCANNED_WORKFLOW edge would render as *not observed*, which is honest, but a
reader deserves to know it was refused rather than merely unseen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

# A single path segment we are willing to create on disk. Deliberately an allow-list: enumerating
# the dangerous characters is a losing game, and workflow paths are ordinary file names.
_SEGMENT_RE: Final = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._@+-]*$")
_WINDOWS_PREFIX_RE: Final = re.compile(r"^(?:[A-Za-z]:|\\\\)")


class UnsafePathError(ValueError):
    """A collected path or repository name is not safe to materialize."""


@dataclass(frozen=True, slots=True)
class SafeTarget:
    """A sanitized, contained destination for one workflow file."""

    repo_dir: Path
    file_path: Path
    relative_path: str


def _check_segments(value: str, *, what: str) -> list[str]:
    if not value or not value.strip():
        raise UnsafePathError(f"the {what} is empty.")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise UnsafePathError(f"the {what} contains a NUL or newline.")
    if _WINDOWS_PREFIX_RE.match(value):
        raise UnsafePathError(f"the {what} carries a Windows drive or UNC prefix: {value!r}.")
    if value.startswith("/") or value.startswith("\\"):
        raise UnsafePathError(f"the {what} is absolute: {value!r}.")
    segments = list(PurePosixPath(value).parts)
    if not segments:
        raise UnsafePathError(f"the {what} has no path segments: {value!r}.")
    for segment in segments:
        if segment in (".", ".."):
            raise UnsafePathError(f"the {what} contains a '{segment}' segment: {value!r}.")
        if not _SEGMENT_RE.match(segment):
            raise UnsafePathError(f"the {what} has a segment that is not a plain file name: {segment!r}.")
    return segments


def repository_dir(run_root: Path, full_name: str) -> Path:
    """The contained directory for one repository, under this run's root.

    `full_name` must be exactly `owner/repo`; anything else is refused rather than normalized,
    because a name that is not that shape did not come from where we think it came from.
    """
    segments = _check_segments(full_name, what="repository name")
    if len(segments) != 2:
        raise UnsafePathError(f"the repository name is not exactly 'owner/repo': {full_name!r}.")
    return run_root / segments[0] / segments[1]


def safe_target(run_root: Path, *, full_name: str, path: str) -> SafeTarget:
    """Resolve one workflow row to a destination inside its repository's directory, or refuse.

    Raises `UnsafePathError` with a reason the collector records verbatim on the skip.
    """
    repo_dir = repository_dir(run_root, full_name)
    segments = _check_segments(path, what="workflow path")
    candidate = repo_dir.joinpath(*segments)

    # Containment is checked against the RESOLVED parents (the file itself does not exist yet).
    # `strict=False` resolves as far as the tree exists, which is what we want on a fresh run.
    resolved_repo = repo_dir.resolve()
    resolved_parent = candidate.parent.resolve()
    if resolved_parent != resolved_repo and resolved_repo not in resolved_parent.parents:
        raise UnsafePathError(
            f"the workflow path resolves outside its repository directory: {path!r} -> {resolved_parent}."
        )
    return SafeTarget(repo_dir=repo_dir, file_path=candidate, relative_path="/".join(segments))


def materialize(target: SafeTarget, content: str) -> None:
    """Write one workflow file, refusing to follow a symlink or overwrite an existing file.

    Exclusive creation ("x") is the O_NOFOLLOW-equivalent that matters here: if anything already
    occupies the destination — including a symlink pointing somewhere else — the write fails
    rather than landing on the target of somebody else's link.
    """
    target.file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target.file_path, "x", encoding="utf-8") as handle:
        handle.write(content)
