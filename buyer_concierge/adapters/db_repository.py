from typing import Optional, List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.encoders import jsonable_encoder

from buyer_concierge.service.ports import AbstractRepository
from buyer_concierge.models import SubmitRFQ as PydanticSubmitRFQ, Quote as PydanticQuote
from shared.models_db import RFQTable, QuoteTable, RFQStatus
from shared.logging import get_logger

logger = get_logger(__name__)

class SQLModelRepository(AbstractRepository):
    """Concrete implementation of the repository using SQLModel and AsyncSession."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_rfq(self, rfq_data: PydanticSubmitRFQ, client_rfq_id: Optional[str] = None) -> RFQTable:
        logger.info(f"Adding RFQ. Client RFQ ID: {client_rfq_id if client_rfq_id else 'N/A'}")
        db_rfq = RFQTable(
            client_rfq_id=client_rfq_id,
            bom_items=jsonable_encoder(rfq_data.bom),
            currency=rfq_data.currency.value,
            deadline=rfq_data.deadline,
            status=RFQStatus.PENDING
        )
        self.session.add(db_rfq)
        await self.session.flush()  # Flush to assign IDs and pending changes
        await self.session.refresh(db_rfq) # Refresh to get DB defaults like ID, created_at
        logger.info(f"RFQ added/flushed with ID: {db_rfq.id}, created_at: {db_rfq.created_at}")
        # No commit here, transaction managed externally
        return db_rfq

    async def get_rfq_by_id(self, rfq_id: int) -> Optional[RFQTable]:
        logger.debug(f"Fetching RFQ by DB ID: {rfq_id}")
        rfq = await self.session.get(RFQTable, rfq_id)
        if rfq:
            logger.debug(f"RFQ found with DB ID: {rfq_id}")
        else:
            logger.debug(f"No RFQ found with DB ID: {rfq_id}")
        return rfq

    async def get_rfq_by_client_id(self, client_rfq_id: str) -> Optional[RFQTable]:
        logger.debug(f"Fetching RFQ by client_rfq_id: {client_rfq_id}")
        statement = select(RFQTable).where(RFQTable.client_rfq_id == client_rfq_id)
        result = await self.session.execute(statement)
        rfq = result.scalar_one_or_none()
        if rfq:
            logger.debug(f"RFQ found with client_rfq_id: {client_rfq_id}")
        else:
            logger.debug(f"No RFQ found with client_rfq_id: {client_rfq_id}")
        return rfq

    async def update_rfq_status(self, rfq_id: int, status: RFQStatus) -> Optional[RFQTable]:
        logger.info(f"Updating status of RFQ ID {rfq_id} to {status.value}")
        db_rfq = await self.get_rfq_by_id(rfq_id)
        if db_rfq:
            db_rfq.status = status
            self.session.add(db_rfq)
            await self.session.flush()
            await self.session.refresh(db_rfq)
            logger.info(f"RFQ ID {rfq_id} status updated/flushed to {status.value}")
            # No commit here
            return db_rfq
        logger.warning(f"Attempted to update status for non-existent RFQ ID: {rfq_id}")
        return None

    async def add_quote_to_rfq(self, rfq_db_id: int, quote_data: PydanticQuote) -> QuoteTable:
        logger.info(f"Adding quote to RFQ ID {rfq_db_id} from supplier {quote_data.supplierId}")
        db_quote = QuoteTable(
            rfq_table_id=rfq_db_id,
            supplier_id=quote_data.supplierId,
            quoted_items=jsonable_encoder(quote_data.items),
            total_price=quote_data.totalPrice,
            currency=quote_data.currency.value,
            valid_until=quote_data.validUntil
        )
        self.session.add(db_quote)
        await self.session.flush()
        await self.session.refresh(db_quote)
        logger.info(f"Quote added/flushed for RFQ ID {rfq_db_id}, new Quote ID: {db_quote.id}")
        # No commit here
        return db_quote

    async def get_quotes_for_rfq(self, rfq_db_id: int) -> List[QuoteTable]:
        logger.debug(f"Fetching all quotes for RFQ DB ID: {rfq_db_id}")
        statement = select(QuoteTable).where(QuoteTable.rfq_table_id == rfq_db_id)
        result = await self.session.execute(statement)
        quotes = result.scalars().all()
        logger.debug(f"Found {len(quotes)} quotes for RFQ DB ID: {rfq_db_id}")
        return list(quotes) 