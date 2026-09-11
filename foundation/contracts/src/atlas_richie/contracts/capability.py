"""Portable component capability descriptions."""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """A stable, serializable description of a component capability."""

    name: str
    version: str
    attributes: Mapping[str, str]
