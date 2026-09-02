"""TAP zizmor plugin — GitHub Actions workflow audits, consumed offline onto the grid.

Spec: specs/spec-zizmor-v0.md. The collector reads workflow YAML github_core already landed,
runs the pinned zizmor binary offline, and lands findings beside the workflows and jobs they
concern. No forge access, no credential, no network.
"""
