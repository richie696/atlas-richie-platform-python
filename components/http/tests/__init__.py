"""`atlas-richie-http` test package.

The E2E suite lives in `test_e2e_http.py` and pulls helpers
from the `e2e_helpers/` sub-package. Adding this `__init__.py`
is required so the `from .e2e_helpers...` relative import in
`test_e2e_http.py` resolves correctly under pytest.
"""
