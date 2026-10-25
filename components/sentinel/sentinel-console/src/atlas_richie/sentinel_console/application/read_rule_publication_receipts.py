"""Read one publication's exact, bounded instance receipt page."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_publications import (
    MAX_PUBLICATION_RECEIPT_PAGE,
    MAX_PUBLICATION_RECEIPT_PAGE_SIZE,
    RulePublication,
    RulePublicationReceiptPage,
)
from .rule_publication_errors import InvalidPublicationReceiptQuery
from .rule_publication_ports import (
    RulePublicationDetailReader,
    RulePublicationReceiptReader,
)


class ReadRulePublicationReceipts:
    """Verify publication identity before returning its receipt page."""

    def __init__(
        self,
        publication_reader: RulePublicationDetailReader,
        receipt_reader: RulePublicationReceiptReader,
    ) -> None:
        self._publication_reader = publication_reader
        self._receipt_reader = receipt_reader

    async def execute(
        self,
        binding_id: str,
        publication_id: str,
        page: int,
        page_size: int,
    ) -> RulePublicationReceiptPage:
        """Read and cross-check publication and receipt authority facts."""
        if not all(
            is_rule_binding_identifier(value) for value in (binding_id, publication_id)
        ):
            raise InvalidPublicationReceiptQuery("publication identity is invalid")
        if type(page) is not int or not 1 <= page <= MAX_PUBLICATION_RECEIPT_PAGE:
            raise InvalidPublicationReceiptQuery("receipt page is out of range")
        if (
            type(page_size) is not int
            or not 1 <= page_size <= MAX_PUBLICATION_RECEIPT_PAGE_SIZE
        ):
            raise InvalidPublicationReceiptQuery("receipt page size is out of range")

        publication = await self._publication_reader.read_rule_publication(
            binding_id, publication_id
        )
        if not isinstance(publication, RulePublication) or (
            publication.binding_id != binding_id
            or publication.id != publication_id
        ):
            raise ValueError("publication authority returned another publication")
        receipts = await self._receipt_reader.read_rule_publication_receipts(
            binding_id, publication_id, page, page_size
        )
        if not isinstance(receipts, RulePublicationReceiptPage):
            raise ValueError("receipt authority returned an invalid page")
        receipts.validate_for(publication)
        if receipts.page != page or receipts.page_size != page_size:
            raise ValueError("receipt authority returned another page")
        return receipts
