"""Stable input failure for publication-specific read use cases."""

from __future__ import annotations


class InvalidPublicationReceiptQuery(ValueError):
    """The path or paging arguments are outside the public receipt contract."""
