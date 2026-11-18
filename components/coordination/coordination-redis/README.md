# atlas-richie-coordination-redis

Redis-backed `LeaderElector`: atomic acquisition, monotonic fencing tokens, and
compare-and-set renew/release. Depends on `redis` and `coordination-core` only.

## Usage

```python
import redis
from atlas_richie.coordination_redis import RedisLeaderElector

elector = RedisLeaderElector(redis.Redis.from_url("redis://localhost:6379/0"))
lease = elector.try_acquire("nightly-job", holder_id="instance-a", ttl_seconds=30)
if lease is not None:
    do_leader_work(fencing_token=lease.fencing_token)
    lease = elector.renew(lease, 30)
```

## How it works

All three operations are Lua scripts, so each is atomic:

- **acquire** — only when the lease key is absent, `INCR` the fencing counter and
  `SET` the lease with a `PX` TTL. The token is minted *inside* the script, so a
  failed attempt does not burn a token and two holders can never get the same one.
- **renew / release** — compare-and-set against the exact `holder:token` value. A
  stale holder cannot extend or delete the current holder's lease.

Keys: `{prefix}:leader:{resource}` (value `holder:token`, TTL) and
`{prefix}:fencing:{resource}` (counter). Default prefix `platform:coordination`.

`current(resource)` reports the live holder, its token and remaining TTL.

## Guarantees and limits

- Lease expiry automatically ends leadership; a holder that fails to renew in time
  loses it, and `renew` returns `None` rather than silently continuing.
- The fencing token is monotonic **per resource** and shared across instances.
- This is a lease, not consensus. During a network partition two instances may
  briefly both believe they are leader — consumers must enforce the fencing token
  at the resource they protect (reject writes carrying an older token).
- Renewal is the caller's responsibility; a background renew loop can be built with
  `atlas-richie-scheduling-core`.

## Tests

Run against a real Redis and skip cleanly when none is reachable. Point
`ATLAS_RICHIE_COORDINATION_REDIS_URL` at your instance.
