"""Application failures with stable meanings at the HTTP boundary."""


class BootstrapAuthorityUnavailable(RuntimeError):
    """The bootstrap marker or operator-session authority is unavailable."""


class SessionAuthorityUnavailable(RuntimeError):
    """The current account-session authority cannot be read safely."""
