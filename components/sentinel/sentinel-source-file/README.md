# atlas-richie-sentinel-source-file

File source adapter for Atlas Richie Sentinel. Wraps the main
package's `FileRuleSource` as a standalone wheel.

## Install

```bash
uv add atlas-richie-sentinel-source-file
# or with YAML support:
uv add atlas-richie-sentinel-source-file[yaml]
```

## Usage

```python
from atlas_richie.sentinel_source_file import FileRuleSource
from atlas_richie.sentinel.rules.repository import RuleRepository

repo = RuleRepository()
source = FileRuleSource(
    path="/etc/sentinel/rules.json",
    poll_interval_sec=3.0,
    source_id="file",
)
source.start(repo)
```

Rule file format (JSON):

```json
{
  "flow-1": {
    "selector": {"kind": "exact", "pattern": "GET /orders"},
    "priority": 10,
    "grade": "qps",
    "threshold": 100.0,
    "behavior": "reject",
    "control": "reject",
    "scope": "direct"
  }
}
```

YAML is also supported (requires `pyyaml` extra).

## Behavior

- Polls every `poll_interval_sec` (default 3s); only re-parses on mtime change.
- Parse errors keep last-known-good (no in-flight disruption).
- `stop()` cancels the polling task (idempotent).
- `latest()` does a synchronous one-shot read (for tests / initial load).

License: Apache-2.0.
