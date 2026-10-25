# Python ↔ Java HTTP demo

These two dependency-free HTTP peers are a transport smoke demo for T03.3.
Each peer exposes the same deterministic endpoints:

| Endpoint | Behavior |
| --- | --- |
| `GET /demo/fixed` | Returns `atlas-sentinel-interop-ok` as UTF-8 plain text. |
| `GET /demo/delay?seconds=N` | Sleeps for a bounded `0 ≤ N ≤ 5` seconds, then returns the same text. |

Run from the repository root:

```sh
foundation/contracts/tools/test_managed_rule_publication_v1_interop_demo.sh
```

The harness starts Python and Java peers on temporary loopback ports, tests
Python → Java and Java → Python requests, checks a delayed response, verifies
client timeout behavior and subsequent recovery, and terminates both demo
processes. It does not use a browser or Docker.

This proves only basic cross-language HTTP reachability and timeout handling.
It does not prove that a Java Sentinel runtime loads the managed rule envelope
or reports a production publication receipt.
