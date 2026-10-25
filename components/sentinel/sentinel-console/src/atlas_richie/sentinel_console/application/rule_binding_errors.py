"""Shared validation error for binding-scoped Console use cases."""


class InvalidRuleIdentifier(ValueError):
    """A binding-scoped rule route supplied an invalid opaque identifier."""
