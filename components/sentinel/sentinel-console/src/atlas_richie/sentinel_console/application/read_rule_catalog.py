"""Read the persisted, query-bound rule catalog projection."""

from __future__ import annotations

from ..domain.rule_catalog import RuleCatalogPage, RuleCatalogQuery
from .rule_catalog_ports import RuleCatalogProjection


class ReadRuleCatalog:
    """Delegate catalog reads to the projection authority and verify ownership."""

    def __init__(self, projection: RuleCatalogProjection) -> None:
        self._projection = projection

    async def execute(self, query: RuleCatalogQuery) -> RuleCatalogPage:
        """Return only the exact query and bounded typed page requested."""
        page = await self._projection.read_catalog(query)
        if not isinstance(page, RuleCatalogPage) or page.query != query:
            raise ValueError("rule catalog projection returned a mismatched page")
        return page
