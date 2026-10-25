"""Atlas Richie Agent Reporting Protocol V1 — cross-language contract tests.

1:1 mirror of the Python codec at
``foundation/contracts/src/atlas_richie/contracts/reporting/v1/codec.py`` to
the Go and Java SDK mocks under this directory.

These tests verify that the wire spec is consistently implemented across
all three languages and that the byte-level contract is preserved (after
sorting keys, since the spec only mandates *no whitespace + UTF-8*).
"""
