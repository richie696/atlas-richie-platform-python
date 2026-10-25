# Dashboard performance probe

This test-only probe observes a same-origin dashboard page in the Codex in-app
browser. It collects browser navigation timing, paint entries exposed by the
browser, Largest Contentful Paint, the maximum layout-shift session, long tasks,
resource byte counters, and trusted interaction-to-two-animation-frame timing.
It does not add instrumentation to the product build.

Build the demo profile and start the local probe server:

```sh
npm run build:demo
node tests/performance/serve-build.mjs
```

Open `http://127.0.0.1:5201/__performance-probe` in the Codex in-app browser.
The default sample is the overview. A local hash route can be sampled with the
`target` query parameter, for example:

```text
http://127.0.0.1:5201/__performance-probe?target=%2F%23%2Foverview%3Fapp%3Dall%26range%3D1h
```

To sample production assets after `npm run build`, start the same server with
`SENTINEL_PERF_BUILD_DIR=dist/client`. The server binds to loopback by default;
do not expose it to a network. It serves only the selected build directory and
the probe document.

Interpretation limits:

- Record browser, CSS viewport, DPR, build profile, cache state, route, and
  whether the page reached its content-ready state with every sample.
- `transferSize` may be zero for cached resources. Do not treat that as a cold
  download measurement; use the manifest bundle report for static asset size.
- Some embedded browser contexts do not expose Paint Timing entries. A `null`
  FCP is unavailable data, not zero milliseconds.
- The interaction figure ends after two animation frames. It is a rendering
  response sample, not an INP result or proof that a server-side command
  completed.
- Demo-profile sample data has no artificial HTTP delay. It does not represent
  Python, Collector, SQL, or configuration-center latency.

## Current lab budgets (2026-10-14)

These are engineering guardrails for the dashboard build, not field CWV/SLO
claims:

| Measure                                                |                               Lab budget | Latest evidence                                        |
| ------------------------------------------------------ | ---------------------------------------: | ------------------------------------------------------ |
| Largest JavaScript chunk                               |                                < 500 KiB | 466,798 B live; 470,651 B demo                         |
| Initial JavaScript                                     |                             <= 750,000 B | 745,642 B live; 749,495 B demo                         |
| Initial manifest-linked assets                         | <= 1,000,000 B raw and <= 270,000 B gzip | 965,384 B / 262,948 B live; 969,237 B / 264,067 B demo |
| LCP on a content-ready local demo page                 |                              <= 2,500 ms | 532 ms on a fresh 1280x720 CSS viewport sample         |
| Maximum CLS session on a content-ready local demo page |                                  <= 0.10 | 0.0187 on the same sample                              |
| Trusted interaction to two animation frames            |                                <= 100 ms | 15 ms for the local demo sign-in interaction           |

The build-profile test enforces the chunk boundary and deferred-loading
contracts. Browser timing values are lab samples, not statistically meaningful
p75 results. FCP was unavailable. The fresh IAB navigation transferred
970,437 B, but cache isolation was not explicitly controlled, so this is not a
formal cold-cache guarantee. The checked route was synthetic demo data; this
does not assert production API latency or live-provider readiness. Re-run these
samples after major visual, chart, routing, or transport changes and retain the
route, viewport, DPR, cache, and content-ready details.
