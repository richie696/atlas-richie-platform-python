# atlas-richie-sentinel-source-file

Sentinel family — source file module (skeleton).

Part of the **Atlas Richie Sentinel** family — the Python equivalent of
Alibaba Sentinel + Resilience4j, providing:

- Resource / rule / slot-chain abstraction
- 5 rule types: Flow / Degrade / ParamFlow / System / Authority
- ASGI ingress protection + httpx pool protection
- Per-resource business rules

## Status

**Skeleton — version 0.0.1a1 (ALPHA).** No implementation yet; only
package metadata, dependency declaration, and `__all__` placeholder.

## Install

```bash
pip install atlas-richie-sentinel-source-file
```

## See also

- `docs/acceptance/R-SENTINEL-design.md` — full design doc
- `components/sentinel/` — sibling wheels in the Sentinel family
