"""Redis leader election tests, run against a real Redis."""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from atlas_richie.coordination_core import Leadership
from atlas_richie.coordination_redis import RedisLeaderElector

pytestmark = pytest.mark.integration


@pytest.fixture
def resource() -> str:
    return f"job-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def prefix() -> str:
    return f"it:coord:{uuid.uuid4().hex[:10]}"


@pytest.fixture
def elector(client, prefix) -> RedisLeaderElector:
    return RedisLeaderElector(client, prefix=prefix)


class TestAcquire:
    def test_first_acquire_grants_with_token(self, elector, resource) -> None:
        lease = elector.try_acquire(resource, "a", 30)
        assert lease is not None
        assert lease.holder_id == "a"
        assert lease.fencing_token == 1

    def test_second_holder_denied(self, elector, resource) -> None:
        elector.try_acquire(resource, "a", 30)
        assert elector.try_acquire(resource, "b", 30) is None

    def test_failed_attempt_does_not_burn_a_token(self, elector, resource) -> None:
        first = elector.try_acquire(resource, "a", 0.05)
        for _ in range(5):
            assert elector.try_acquire(resource, "b", 30) is None
        time.sleep(0.08)
        second = elector.try_acquire(resource, "b", 30)
        assert second.fencing_token == first.fencing_token + 1

    def test_lease_expires_and_is_reacquired(self, elector, resource) -> None:
        first = elector.try_acquire(resource, "a", 0.05)
        time.sleep(0.08)
        second = elector.try_acquire(resource, "b", 30)
        assert second is not None
        assert second.fencing_token > first.fencing_token

    def test_cross_instance_exclusion(self, client, prefix, resource) -> None:
        one = RedisLeaderElector(client, prefix=prefix)
        two = RedisLeaderElector(client, prefix=prefix)
        assert one.try_acquire(resource, "instance-1", 30) is not None
        assert two.try_acquire(resource, "instance-2", 30) is None

    def test_concurrent_acquire_grants_exactly_one(self, client, prefix, resource) -> None:
        results: list[Leadership | None] = []
        barrier = threading.Barrier(8)

        def contend(index: int) -> None:
            elector = RedisLeaderElector(client, prefix=prefix)
            barrier.wait()
            results.append(elector.try_acquire(resource, f"h{index}", 30))

        threads = [threading.Thread(target=contend, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sum(1 for lease in results if lease is not None) == 1

    def test_resources_are_independent(self, elector, resource) -> None:
        assert elector.try_acquire(resource, "a", 30) is not None
        assert elector.try_acquire(resource + "-other", "b", 30) is not None

    def test_validation(self, elector, resource) -> None:
        with pytest.raises(ValueError):
            elector.try_acquire(resource, "a", 0)
        with pytest.raises(ValueError):
            elector.try_acquire(resource, "", 30)


class TestRenew:
    def test_renew_extends_ttl(self, elector, client, prefix, resource) -> None:
        lease = elector.try_acquire(resource, "a", 1)
        time.sleep(0.6)
        renewed = elector.renew(lease, 30)
        assert renewed is not None
        assert client.pttl(f"{prefix}:leader:{resource}") > 20_000

    def test_renew_after_expiry_fails(self, elector, resource) -> None:
        lease = elector.try_acquire(resource, "a", 0.05)
        time.sleep(0.08)
        assert elector.renew(lease, 30) is None

    def test_stale_holder_cannot_renew(self, elector, resource) -> None:
        old = elector.try_acquire(resource, "a", 0.05)
        time.sleep(0.08)
        elector.try_acquire(resource, "b", 30)
        assert elector.renew(old, 30) is None
        assert elector.current(resource).holder_id == "b"

    def test_same_holder_reacquiring_invalidates_old_lease(self, elector, resource) -> None:
        old = elector.try_acquire(resource, "a", 0.05)
        time.sleep(0.08)
        new = elector.try_acquire(resource, "a", 30)
        assert new.fencing_token > old.fencing_token
        assert elector.renew(old, 30) is None
        assert elector.renew(new, 30) is not None


class TestRelease:
    def test_holder_releases(self, elector, resource) -> None:
        lease = elector.try_acquire(resource, "a", 30)
        assert elector.release(lease) is True
        assert elector.current(resource) is None

    def test_stale_release_does_not_delete_new_lease(self, elector, resource) -> None:
        old = elector.try_acquire(resource, "a", 0.05)
        time.sleep(0.08)
        elector.try_acquire(resource, "b", 30)
        assert elector.release(old) is False
        assert elector.current(resource).holder_id == "b"

    def test_forged_lease_cannot_release(self, elector, resource) -> None:
        elector.try_acquire(resource, "a", 30)
        forged = Leadership(resource, "b", 1, time.time() + 30)
        assert elector.release(forged) is False
        assert elector.current(resource).holder_id == "a"

    def test_double_release_is_false(self, elector, resource) -> None:
        lease = elector.try_acquire(resource, "a", 30)
        assert elector.release(lease) is True
        assert elector.release(lease) is False


class TestCurrent:
    def test_reports_holder_token_and_ttl(self, elector, resource) -> None:
        elector.try_acquire(resource, "a", 30)
        current = elector.current(resource)
        assert current.holder_id == "a"
        assert current.fencing_token == 1
        assert current.expires_at > time.time()

    def test_none_when_free(self, elector, resource) -> None:
        assert elector.current(resource) is None

    def test_none_after_expiry(self, elector, resource) -> None:
        elector.try_acquire(resource, "a", 0.05)
        time.sleep(0.08)
        assert elector.current(resource) is None

    def test_holder_id_containing_colon_is_parsed_correctly(self, elector, resource) -> None:
        elector.try_acquire(resource, "tenant:instance-1", 30)
        current = elector.current(resource)
        assert current.holder_id == "tenant:instance-1"
        assert current.fencing_token == 1


class TestFencingToken:
    def test_monotonic_across_instances_and_acquisitions(self, client, prefix, resource) -> None:
        tokens = []
        for index in range(4):
            elector = RedisLeaderElector(client, prefix=prefix)
            lease = elector.try_acquire(resource, f"h{index}", 0.05)
            tokens.append(lease.fencing_token)
            time.sleep(0.08)
        assert tokens == sorted(set(tokens))
        assert len(tokens) == 4

    def test_token_key_is_separate_from_lease_key(self, elector, client, prefix, resource) -> None:
        elector.try_acquire(resource, "a", 30)
        assert client.get(f"{prefix}:fencing:{resource}") == "1"
        assert client.get(f"{prefix}:leader:{resource}") == "a:1"
