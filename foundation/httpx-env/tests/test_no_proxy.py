import os

import pytest

from atlas_richie.httpx_env import no_proxy_ipv6_guard
from atlas_richie.httpx_env.no_proxy import _unbracket_ipv6_hosts

pytestmark = pytest.mark.unit


def test_only_ipv6_brackets_are_removed() -> None:
    assert (
        _unbracket_ipv6_hosts("example.com,[::1],127.0.0.0/8,[2001:db8::1],*")
        == "example.com,::1,127.0.0.0/8,2001:db8::1,*"
    )


def test_non_ipv6_bracketed_text_is_preserved() -> None:
    assert _unbracket_ipv6_hosts("[not-an-ip],example.com") == "[not-an-ip],example.com"


def test_guard_normalizes_both_case_variants_and_restores(monkeypatch) -> None:
    original = "localhost,[::1],::1"
    monkeypatch.setenv("NO_PROXY", original)
    monkeypatch.setenv("no_proxy", original)

    with no_proxy_ipv6_guard():
        assert os.environ["NO_PROXY"] == "localhost,::1,::1"
        assert os.environ["no_proxy"] == "localhost,::1,::1"

    assert os.environ["NO_PROXY"] == original
    assert os.environ["no_proxy"] == original


def test_guard_is_noop_for_clean_values(monkeypatch) -> None:
    clean = "localhost,::1,127.0.0.0/8"
    monkeypatch.setenv("NO_PROXY", clean)
    monkeypatch.delenv("no_proxy", raising=False)

    with no_proxy_ipv6_guard():
        assert os.environ["NO_PROXY"] == clean

    assert os.environ["NO_PROXY"] == clean


def test_guard_restores_environment_on_exception(monkeypatch) -> None:
    original = "localhost,[::1]"
    monkeypatch.setenv("NO_PROXY", original)

    with pytest.raises(RuntimeError):
        with no_proxy_ipv6_guard():
            raise RuntimeError("construction failed")

    assert os.environ["NO_PROXY"] == original
