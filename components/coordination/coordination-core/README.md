# atlas-richie-coordination-core

Leader election contracts with fencing tokens, plus a per-process reference
implementation. **Zero runtime dependencies.**

A shared store is required for real multi-instance election — see
`atlas-richie-coordination-redis`. The in-memory elector here is for single-process
use and tests.

## Contract

```python
from atlas_richie.coordination_core import InMemoryLeaderElector

elector = InMemoryLeaderElector()
lease = elector.try_acquire(" nightly-job", holder_id="instance-a", ttl_seconds=30)
if lease is not None:
    ...                                   # we are the leader
    lease = elector.renew(lease, 30)      # None means leadership was lost
    elector.release(lease)
```

`Leadership` carries `resource`, `holder_id`, `fencing_token` and `expires_at`.
The token **strictly increases on every new acquisition**, so a downstream system
can reject writes from a stale leader (fencing).

## Fencing guarantee

Same principle as sentinel-cluster's owner-epoch fencing: a stale holder's `renew`
or `release` must never affect the current holder. Operations match the exact
`(holder_id, fencing_token)` pair that was granted, exposed as `lease_value`.
A holder that lost leadership and later re-acquired the resource gets a new token,
so its old `Leadership` object is inert.

## Not included

Consensus (Raft/Paxos), membership/gossip, and distributed locks for mutual
exclusion of arbitrary critical sections. Leader election is a lease with a
monotonic token, not a consensus protocol: during a partition two instances may
briefly both believe they hold the lease, which is exactly why consumers must
enforce the fencing token at the resource they protect.
