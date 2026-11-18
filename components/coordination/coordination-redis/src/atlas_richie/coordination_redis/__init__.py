"""Redis-backed leader election.

Acquisition, renewal and release are Lua scripts so each is atomic:

- acquire: only when the lease key is absent, INCR the fencing counter and SET the
  lease with a TTL. The token is minted inside the script, so a failed attempt does
  not burn a token and two holders can never receive the same one.
- renew / release: compare-and-set against the exact `holder:token` value, so a
  stale holder cannot extend or delete the current holder's lease — the same
  guarantee as sentinel-cluster's owner-epoch fencing.

The lease value embeds the fencing token, which means a holder that lost and later
re-acquired the same resource gets a new identity; its old Leadership object can no
longer affect the lease.
"""

from __future__ import annotations

import time

from atlas_richie.coordination_core import Leadership

DEFAULT_PREFIX = "platform:coordination"

_ACQUIRE = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  local token = redis.call('INCR', KEYS[2])
  redis.call('SET', KEYS[1], ARGV[1] .. ':' .. token, 'PX', ARGV[2])
  return token
end
return nil
"""

_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def _text(value) -> str:
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)


class RedisLeaderElector:
    """Cross-instance `LeaderElector` backed by Redis leases."""

    def __init__(self, client, *, prefix: str = DEFAULT_PREFIX, clock=time.time) -> None:
        self._client = client
        self._prefix = prefix or DEFAULT_PREFIX
        self._clock = clock
        self._acquire = client.register_script(_ACQUIRE)
        self._renew = client.register_script(_RENEW)
        self._release = client.register_script(_RELEASE)

    def _lease_key(self, resource: str) -> str:
        return f"{self._prefix}:leader:{resource}"

    def _token_key(self, resource: str) -> str:
        return f"{self._prefix}:fencing:{resource}"

    def try_acquire(self, resource: str, holder_id: str, ttl_seconds: float) -> Leadership | None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        if not holder_id:
            raise ValueError("holder_id must not be blank")
        token = self._acquire(
            keys=[self._lease_key(resource), self._token_key(resource)],
            args=[holder_id, int(ttl_seconds * 1000)],
        )
        if token is None:
            return None
        return Leadership(resource, holder_id, int(token), self._clock() + ttl_seconds)

    def renew(self, lease: Leadership, ttl_seconds: float) -> Leadership | None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        ok = self._renew(
            keys=[self._lease_key(lease.resource)],
            args=[lease.lease_value, int(ttl_seconds * 1000)],
        )
        if not ok:
            return None
        return Leadership(lease.resource, lease.holder_id, lease.fencing_token, self._clock() + ttl_seconds)

    def release(self, lease: Leadership) -> bool:
        return bool(
            self._release(keys=[self._lease_key(lease.resource)], args=[lease.lease_value])
        )

    def current(self, resource: str) -> Leadership | None:
        key = self._lease_key(resource)
        value = self._client.get(key)
        if value is None:
            return None
        ttl_ms = self._client.pttl(key)
        if ttl_ms is None or ttl_ms < 0:
            # -2 means the key vanished between GET and PTTL; -1 means no expiry,
            # which this elector never sets.
            return None
        holder, _, token = _text(value).rpartition(":")
        if not holder or not token.isdigit():
            return None
        return Leadership(resource, holder, int(token), self._clock() + ttl_ms / 1000)


__all__ = ["DEFAULT_PREFIX", "RedisLeaderElector"]
