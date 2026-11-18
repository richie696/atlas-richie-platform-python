"""Testing helpers for contract-oriented component tests.

Framework-free helpers are exported here; pytest-specific helpers live in
`atlas_richie.testing.pytest_support` so importing this package never requires
pytest.
"""

from .clock import ManualClock
from .contracts import assert_capability_descriptor
from .network import host_port_of, tcp_reachable

__all__ = [
    "ManualClock",
    "assert_capability_descriptor",
    "host_port_of",
    "tcp_reachable",
]
