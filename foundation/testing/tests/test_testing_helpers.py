"""Tests for the shared testing helpers."""

from __future__ import annotations

import socket
import threading

import pytest

from atlas_richie.contracts import CapabilityDescriptor
from atlas_richie.testing import (
    ManualClock,
    assert_capability_descriptor,
    host_port_of,
    tcp_reachable,
)
from atlas_richie.testing.pytest_support import skip_unless_reachable

pytestmark = pytest.mark.unit


class TestHostPortOf:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("redis://127.0.0.1:16379/0", ("127.0.0.1", 16379)),
            ("redis://:password@127.0.0.1:16379/0", ("127.0.0.1", 16379)),
            ("redis://user:pass@host:6380/2", ("host", 6380)),
            ("redis://localhost", ("localhost", 6379)),
            ("127.0.0.1:8848", ("127.0.0.1", 8848)),
            ("localhost", ("localhost", 6379)),
            ("http://127.0.0.1:8200/v1/sys/health", ("127.0.0.1", 8200)),
            ("redis://[::1]:6379/0", ("::1", 6379)),
            ("redis://[::1]", ("::1", 6379)),
            ("[::1]:6380", ("::1", 6380)),
        ],
    )
    def test_parsing(self, url: str, expected: tuple[str, int]) -> None:
        assert host_port_of(url, 6379) == expected

    @pytest.mark.parametrize("url", ["", "redis://", "redis://:6379", "redis://[::1", "host:notaport"])
    def test_unparseable_returns_none(self, url: str) -> None:
        assert host_port_of(url, 6379) is None

    def test_default_port_is_configurable(self) -> None:
        assert host_port_of("nacos-host", 8848) == ("nacos-host", 8848)

    def test_ipv6_without_brackets_is_not_silently_misparsed(self) -> None:
        # A bare IPv6 literal is ambiguous with host:port; it must not yield a
        # bogus port that would make a reachability probe silently wrong.
        assert host_port_of("::1", 6379) is None


class TestTcpReachable:
    def test_open_port_is_reachable(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            assert tcp_reachable(f"redis://127.0.0.1:{port}/0") is True

    def test_closed_port_is_not_reachable(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        assert tcp_reachable(f"redis://127.0.0.1:{port}") is False

    def test_unparseable_url_is_not_reachable(self) -> None:
        assert tcp_reachable("") is False

    def test_concurrent_probes_are_independent(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(8)
            port = listener.getsockname()[1]
            results: list[bool] = []

            def probe() -> None:
                results.append(tcp_reachable(f"127.0.0.1:{port}"))

            threads = [threading.Thread(target=probe) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            assert results == [True] * 8


class TestManualClock:
    def test_starts_at_zero_and_is_callable(self) -> None:
        clock = ManualClock()
        assert clock() == 0.0

    def test_advance_and_set(self) -> None:
        clock = ManualClock(100.0)
        assert clock.advance(25) == 125.0
        assert clock() == 125.0
        assert clock.set(7) == 7.0
        assert clock.value == 7.0

    def test_does_not_advance_on_its_own(self) -> None:
        clock = ManualClock(5.0)
        assert clock() == clock() == 5.0

    def test_usable_as_injected_clock(self) -> None:
        clock = ManualClock()
        expiry = clock() + 10
        clock.advance(9)
        assert clock() < expiry
        clock.advance(2)
        assert clock() > expiry


class TestSkipUnlessReachable:
    def test_skips_when_unreachable(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with pytest.raises(pytest.skip.Exception, match="Redis"):
            skip_unless_reachable(
                f"redis://127.0.0.1:{port}", "Redis", env_hint="ATLAS_RICHIE_CACHE_REDIS_URL"
            )

    def test_passes_when_reachable(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            skip_unless_reachable(f"redis://127.0.0.1:{port}", "Redis")


class TestCapabilityDescriptorAssertion:
    def test_valid_descriptor_passes(self) -> None:
        assert_capability_descriptor(CapabilityDescriptor(name="cache", version="0.2.0", attributes={}))

    @pytest.mark.parametrize(("name", "version"), [("  ", "0.2.0"), ("cache", " ")])
    def test_blank_fields_rejected(self, name: str, version: str) -> None:
        with pytest.raises(AssertionError):
            assert_capability_descriptor(CapabilityDescriptor(name=name, version=version, attributes={}))


class TestPackageImportIsFrameworkFree:
    def test_init_does_not_require_pytest(self) -> None:
        import subprocess
        import sys

        code = (
            "import sys;"
            "sys.modules['pytest']=None;"
            "import atlas_richie.testing as t;"
            "assert hasattr(t,'ManualClock') and hasattr(t,'tcp_reachable')"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
