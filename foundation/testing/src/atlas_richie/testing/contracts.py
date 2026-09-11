"""Assertions reusable without a third-party test framework."""

from atlas_richie.contracts import CapabilityDescriptor


def assert_capability_descriptor(descriptor: CapabilityDescriptor) -> None:
    """Raise AssertionError when a public capability is not minimally valid."""

    assert descriptor.name.strip(), "capability name must not be blank"
    assert descriptor.version.strip(), "capability version must not be blank"
