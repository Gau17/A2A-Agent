from abc import ABC, abstractmethod
from typing import Optional, List, Any, Dict

from buyer_concierge.models import SubmitRFQ, Quote # Pydantic models for data transfer
from shared.models_db import RFQTable, QuoteTable, RFQStatus # DB Models

class AbstractRepository(ABC):
    """Abstract interface for data persistence operations."""

    @abstractmethod
    async def add_rfq(self, rfq_data: SubmitRFQ, client_rfq_id: Optional[str] = None) -> RFQTable:
        """Saves a new RFQ to the database."""
        raise NotImplementedError

    @abstractmethod
    async def get_rfq_by_id(self, rfq_id: int) -> Optional[RFQTable]:
        """Retrieves an RFQ by its internal database ID."""
        raise NotImplementedError
    
    @abstractmethod
    async def get_rfq_by_client_id(self, client_rfq_id: str) -> Optional[RFQTable]:
        """Retrieves an RFQ by a client-provided ID."""
        raise NotImplementedError

    @abstractmethod
    async def update_rfq_status(self, rfq_id: int, status: RFQStatus) -> Optional[RFQTable]:
        """Updates the status of an existing RFQ."""
        raise NotImplementedError

    @abstractmethod
    async def add_quote_to_rfq(self, rfq_db_id: int, quote_data: Quote) -> QuoteTable:
        """Saves a new Quote linked to an RFQ in the database."""
        raise NotImplementedError

    @abstractmethod
    async def get_quotes_for_rfq(self, rfq_db_id: int) -> List[QuoteTable]:
        """Retrieves all quotes associated with a specific RFQ."""
        raise NotImplementedError

    # Add other necessary methods like list_rfqs, etc. 