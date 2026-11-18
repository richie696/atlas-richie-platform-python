# atlas-richie-scheduling-core

Interval, fixed-delay and one-shot job scheduling with graceful shutdown.
**Zero runtime dependencies** — standard-library threads and events.

Extracted because `secret-rotation-daemon` and the console's activation-plan worker
each hand-roll the same polling loop, stop handling and exception isolation.

## Usage

```python
from atlas_richie.scheduling_core import Scheduler

with Scheduler(name="rotation") as scheduler:
    scheduler.schedule_interval(30.0, poll_once, name="poll")
    scheduler.schedule_fixed_delay(5.0, cleanup, name="cleanup")
    scheduler.schedule_once(60.0, warmup, name="warmup")
    ...
# leaving the block signals every job and joins within the timeout
```

Or manage the lifecycle explicitly:

```python
scheduler = Scheduler()
job = scheduler.schedule_interval(30.0, poll_once)
scheduler.start()
...
unfinished = scheduler.stop(timeout=5.0)   # names of jobs still running
```

## Semantics

- **One daemon thread per job.** Runs are sequential within a job: a run longer
  than the interval delays the next tick rather than overlapping. Different jobs
  run concurrently.
- `schedule_interval` is fixed-**rate** (next tick measured from the previous run's
  start); `schedule_fixed_delay` measures from the previous run's **end**.
- **Exception isolation**: a raising job increments `failures`, records `last_error`,
  and keeps running; it never kills the scheduler or other jobs. An optional
  `error_handler(name, exception)` is notified, and a handler that itself raises is
  logged without stopping the job.
- **Prompt shutdown**: waiting is done on a stop event, so `stop()` does not wait out
  a long interval. It joins each thread within the remaining timeout and returns the
  names of jobs whose in-flight run did not finish.
- `stop()` is idempotent and terminal: registering or starting afterwards raises.
- Jobs registered before `start()` begin at `start()`; jobs registered afterwards
  begin immediately.
- `job.cancel()` stops one job; an in-flight run is allowed to finish.
- `job.stats` exposes `runs`, `failures`, `last_error`, `last_run_at`, `finished`.

## Not included

Cron expression parsing and a persistent job store (Quartz-style scheduling). Those
are separate concerns and would add dependencies; raise a task if needed.
