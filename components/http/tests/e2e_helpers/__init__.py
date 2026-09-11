"""E2E test helpers for `atlas-richie-http` (R-M6 E.1).

This sub-package hosts the test fixtures that the E2E suite needs
but the unit suite does not — primarily a small FastAPI test app
and a couple of utility helpers (port probing, request-id
interceptors, counting apps). Keeping them in their own package
prevents the unit tests from accidentally importing FastAPI/uvicorn
at collection time.
"""
