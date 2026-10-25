"""Read operator guides shipped with the installed Sentinel Console package."""

from __future__ import annotations

from importlib import metadata, resources

_DISTRIBUTION_NAME = "atlas-richie-sentinel-console"
_BUNDLED_DOCUMENTS = {
    "quickstart": (
        "First installation, local initialization, and safe exposure guidance."
    ),
}


def available_documents() -> tuple[tuple[str, str], ...]:
    """Return stable document identifiers and short descriptions for the CLI."""
    return (
        ("quickstart", _BUNDLED_DOCUMENTS["quickstart"]),
        ("reference", "Complete deployment and configuration reference."),
    )


def read_document(name: str) -> str:
    """Read a known bundled guide or the installed distribution's README."""
    if name == "quickstart":
        return (
            resources.files(__package__)
            .joinpath("docs", "quickstart.md")
            .read_text(encoding="utf-8")
        )
    if name == "reference":
        long_description = metadata.metadata(_DISTRIBUTION_NAME).get_payload()
        if not isinstance(long_description, str) or not long_description.strip():
            raise RuntimeError("the installed package has no deployment reference")
        return long_description
    raise ValueError("unknown documentation identifier")


__all__ = ["available_documents", "read_document"]
