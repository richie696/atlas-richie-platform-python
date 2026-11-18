"""In-memory leader election tests with a deterministic clock."""

from __future__ import annotations

import threading

import pytest

from atlas_richie.coordination_core import InMemoryLeaderElector, Leadership
from atlas_richie.testing import ManualClock

pytestmark = pytest.mark.unit


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(1000.0)


@pytest.fixture
def elector(clock) -> InMemoryLeaderElector:
    return InMemoryLeaderElector(clock=clock)


class TestAcquire:
    def test_first_acquire_grants(self, elector) -> None:
        lease = elector.try_acquire("job", "a", 30)
        assert lease is not None
        assert lease.holder_id == "a"
        assert lease.fencing_token == 1
        assert lease.expires_at == 1030.0

    def test_second_holder_is_denied(self, elector) -> None:
        elector.try_acquire("job", "a", 30)
        assert elector.try_acquire("job", "b", 30) is None

    def test_resources_are_independent(self, elector) -> None:
        assert elector.try_acquire("job1", "a", 30) is not None
        assert elector.try_acquire("job2", "b", 30) is not None

    def test_expiry_allows_reacquisition_with_higher_token(self, elector, clock) -> None:
        first = elector.try_acquire("job", "a", 30)
        clock.advance(31)
        second = elector.try_acquire("job", "b", 30)
        assert second is not None
        assert second.fencing_token > first.fencing_token
        assert second.holder_id == "b"

    def test_token_is_monotonic_across_many_acquisitions(self, elector, clock) -> None:
        tokens = []
        for index in range(5):
            lease = elector.try_acquire("job", f"h{index}", 10)
            tokens.append(lease.fencing_token)
            clock.advance(11)
        assert tokens == [1, 2, 3, 4, 5]

    def test_non_positive_ttl_rejected(self, elector) -> None:
        with pytest.raises(ValueError):
            elector.try_acquire("job", "a", 0)

    def test_concurrent_acquire_grants_exactly_one(self, elector) -> None:
        results: list[Leadership | None] = []
        barrier = threading.Barrier(8)

        def contend(index: int) -> None:
            barrier.wait()
            results.append(elector.try_acquire("job", f"h{index}", 30))

        threads = [threading.Thread(target=contend, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sum(1 for lease in results if lease is not None) == 1


class TestRenew:
    def test_renew_extends_expiry(self, elector, clock) -> None:
        lease = elector.try_acquire("job", "a", 30)
        clock.advance(20)
        renewed = elector.renew(lease, 30)
        assert renewed is not None
        assert renewed.expires_at == 1050.0
        assert renewed.fencing_token == lease.fencing_token

    def test_renew_after_expiry_fails(self, elector, clock) -> None:
        lease = elector.try_acquire("job", "a", 30)
        clock.advance(31)
        assert elector.renew(lease, 30) is None

    def test_stale_holder_cannot_renew_new_lease(self, elector, clock) -> None:
        old = elector.try_acquire("job", "a", 30)
        clock.advance(31)
        elector.try_acquire("job", "b", 30)
        assert elector.renew(old, 30) is None
        assert elector.current("job").holder_id == "b"

    def test_same_holder_reacquiring_invalidates_old_lease(self, elector, clock) -> None:
        old = elector.try_acquire("job", "a", 30)
        clock.advance(31)
        new = elector.try_acquire("job", "a", 30)
        assert new.fencing_token > old.fencing_token
        assert elector.renew(old, 30) is None, "old token must be inert even for the same holder"
        assert elector.renew(new, 30) is not None

    def test_non_positive_ttl_rejected(self, elector) -> None:
        lease = elector.try_acquire("job", "a", 30)
        with pytest.raises(ValueError):
            elector.renew(lease, 0)


class TestRelease:
    def test_holder_can_release(self, elector) -> None:
        lease = elector.try_acquire("job", "a", 30)
        assert elector.release(lease) is True
        assert elector.current("job") is None
        assert elector.try_acquire("job", "b", 30) is not None

    def test_non_holder_cannot_release(self, elector) -> None:
        elector.try_acquire("job", "a", 30)
        forged = Leadership("job", "b", 1, 1030.0)
        assert elector.release(forged) is False
        assert elector.current("job").holder_id == "a"

    def test_stale_release_does_not_delete_new_lease(self, elector, clock) -> None:
        old = elector.try_acquire("job", "a", 30)
        clock.advance(31)
        elector.try_acquire("job", "b", 30)
        assert elector.release(old) is False
        assert elector.current("job").holder_id == "b"

    def test_double_release_is_false(self, elector) -> None:
        lease = elector.try_acquire("job", "a", 30)
        assert elector.release(lease) is True
        assert elector.release(lease) is False


class TestCurrent:
    def test_reports_holder(self, elector) -> None:
        elector.try_acquire("job", "a", 30)
        current = elector.current("job")
        assert current.holder_id == "a"
        assert current.fencing_token == 1

    def test_none_when_free_or_expired(self, elector, clock) -> None:
        assert elector.current("job") is None
        elector.try_acquire("job", "a", 30)
        clock.advance(31)
        assert elector.current("job") is None

    def test_lease_value_encodes_holder_and_token(self, elector) -> None:
        lease = elector.try_acquire("job", "a", 30)
        assert lease.lease_value == "a:1"

    def test_is_expired(self, elector, clock) -> None:
        lease = elector.try_acquire("job", "a", 30)
        assert lease.is_expired(clock()) is False
        clock.advance(30)
        assert lease.is_expired(clock()) is True
