# Versioning and Python support

Each distribution uses Semantic Versioning and has an independent release number.
The aggregate `atlas-richie-platform` package publishes only combinations that have
been tested together; it is not a monolithic API version.

All first-line packages require Python 3.12 or newer.  Stable CI covers CPython
3.12, 3.13, and 3.14.  The next CPython release is an allowed-failure compatibility
signal until it is stable.  We keep one code line across compatible Python versions;
Git branches are reserved for incompatible product major versions or extended
maintenance releases.

The prerelease job builds its wheelhouse from source, because no prebuilt wheels exist
for a prerelease yet, so it takes noticeably longer than the stable jobs (about
22 minutes against 5-6 minutes).  A long prerelease job is expected rather than a
regression.
