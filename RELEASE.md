# Release evidence

A component release requires, at minimum:

1. a clean source tree check and package metadata validation;
2. wheel and source distribution builds for every changed distribution;
3. an isolated virtual-environment install of each wheel, import smoke test, and
   `pip check`;
4. component unit and contract tests on the supported Python matrix; and
5. a changelog entry that identifies public API, protocol, behavior, and security
   effects.

Build success alone does not prove protocol interoperability, HTTP/OAuth behavior,
or a cloud-provider integration.  Those claims need the corresponding black-box or
environment acceptance evidence.

For packages with third-party runtime dependencies, run
`tools/release/prepare_wheelhouse.py` after the build and before
`verify_isolated_wheels.py`.  It downloads exactly the hash-locked runtime wheels
into ignored build artifacts; the verifier then installs with `--no-index`.
