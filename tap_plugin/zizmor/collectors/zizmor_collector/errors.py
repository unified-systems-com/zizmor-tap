"""The collector's own exception type.

Raised (never swallowed) after a `record_error`, so the tap_cares task body turns it into the
standard FAILED terminal patch — see req-tap-cares-collector-failure-mode.
"""

from __future__ import annotations


class ZizmorCollectorError(Exception):
    """An unrecoverable condition in a zizmor collection run."""
