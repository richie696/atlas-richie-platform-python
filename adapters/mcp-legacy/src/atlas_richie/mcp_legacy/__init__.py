"""MCP 2025-11-25 wire compatibility, isolated from the modern core."""

from .dialect import LegacyMcpClientDialect, LegacyMcpServerDialect

__all__ = ["LegacyMcpClientDialect", "LegacyMcpServerDialect"]
