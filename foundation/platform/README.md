# atlas-richie-platform

An installation entry point that pins a tested compatible set of Atlas Richie
components.  It has no global runtime, configuration loader, or DI container.

## Coverage rule

The dependency list covers **every uv workspace member except this package
itself**. The rule is mechanical so the list cannot silently fall behind: when
a component joins `[tool.uv.workspace].members`, it belongs here too, with the
version constraint taken from `versions.toml`.

`atlas-richie-sentinel-console` is deliberately absent — it is not a workspace
member, so it is not part of the verified combination.

## Install weight

This is the "install everything" entry point, so it pulls the full component
set, including the cloud KMS SDK extras' base packages and the dashboard's
Starlette/Jinja2/uvicorn stack. Installing an individual component does **not**
pull this umbrella or its siblings: each component declares only what it needs,
and shared low-level shims live in zero-dependency leaves such as
`atlas-richie-httpx-env`. Choose individual components for a lean install.

## Version

`atlas_richie.platform.__version__` is read from the installed distribution
metadata, so it always matches `pyproject.toml` (which `tools/sync_versions.py`
derives from `versions.toml`). There is no hand-written version string to drift.
