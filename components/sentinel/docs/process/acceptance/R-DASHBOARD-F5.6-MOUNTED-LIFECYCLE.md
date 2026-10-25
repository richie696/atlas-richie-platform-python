# F5.6 mounted realtime lifecycle verification

## Scope

This is a focused Happy DOM + React `createRoot` verification of the production
`LiveMonitoringPage` and `createRealtimeMonitor`. It is not browser E2E and does
not validate the HTTP adapter or a running Console service. The metrics Port is
a held synthetic request so cancellation, timer ownership, and late work are
observable without relying on the network.

## Evidence

The verification in
`components/sentinel/dashboard-prototype/tests/verification/realtime-monitor-mounted-lifecycle.test.mjs`
mounts the page under React `StrictMode`, with one memo-stable monitor owner.
It instruments the actual polling interval and wraps only the owner's existing
subscription boundary to count active React listeners.

- StrictMode's initial effect cleanup aborts/releases its scheduled poll; after
  setup-cleanup-setup there is exactly one active poll timer, one subscribed
  React listener, and one live read. The canceled first setup does not issue a
  duplicate metrics request.
- The live read is held across an interval tick; `exhaustMap` retains one
  in-flight read rather than overlapping requests.
- Pausing immediately clears the poll timer and aborts the held read. Waiting
  beyond one interval produces no additional metrics request.
- Resuming immediately starts one fresh read and owns one timer.
- Unmount clears the timer, aborts that read, and releases the external-store
  subscription. Waiting beyond one interval produces no further request.
- A real unmount/remount of the same reusable owner under StrictMode acquires a
  fresh single timer/read and cleans them up again.

## Result and boundary

No production change was needed: the existing Effect cleanup, monitor
`cancel()`/`dispose()` separation, `PollingStore` cancellation, and framework
external-store subscription satisfy this mounted lifecycle contract in this
focused runtime. The parent `RealtimeObservationContainer` remains the owner of
permanent disposal via `useOwnedDisposal`; this test deliberately verifies the
page's cancellation behavior separately from route-owner disposal.

Synthetic Port evidence does not prove real HTTP transport cancellation,
server-side authorization, or live service behavior. Those remain outside this
slice and require the final HTTP/backend/browser acceptance path.
