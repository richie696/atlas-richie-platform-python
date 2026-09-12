# atlas-richie-sentinel-dashboard

Per-process embedded admin Dashboard for Atlas Richie Sentinel. Loopback
REST API with read-only by default; write ops require admin token.

## Install

```bash
uv add atlas-richie-sentinel-dashboard
```

## Usage

```python
from atlas_richie.sentinel import SentinelEngine
from atlas_richie.sentinel.metrics import MetricRegistry
from atlas_richie.sentinel.rules import RuleRepository
from atlas_richie.sentinel_dashboard import SentinelDashboard

engine = SentinelEngine()
metric_registry = MetricRegistry()
rule_repo = RuleRepository()

dashboard = SentinelDashboard(
    engine=engine,
    metric_registry=metric_registry,
    rule_repository=rule_repo,
    allow_admin=True,
    admin_token="secret-token",
)
dashboard.start()
# bind on http://127.0.0.1:8719/
```

## Endpoints

### Read-only

- `GET /health` — process health + engine state + in_flight.
- `GET /metrics` — MetricRegistry snapshots.
- `GET /rules` — current rules.
- `GET /rules/<rule_id>` — single rule.
- `GET /state` — engine state + in_flight + last_error + rules_count.

### Admin (require `Authorization: Bearer <admin_token>`)

- `POST /admin/rules/reload` — re-pull from RuleSource.
- `POST /admin/breaker/<rule_id>/reset` — DegradeSlot.force_reset.

## Defaults

- **Bind**: `127.0.0.1:8719` (loopback only by default).
- **Admin**: disabled by default; enable with `allow_admin=True`.
- **Audit log**: every admin op is logged; capped at 1000 entries.

## License

Apache-2.0.
