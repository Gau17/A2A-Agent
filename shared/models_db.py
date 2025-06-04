from sqlmodel import Field, SQLModel, JSON, Column, Relationship
from sqlalchemy import Enum as SQLAlchemyEnum # Add this import
from sqlalchemy.dialects.postgresql import JSONB # For PostgreSQL specific JSONB type
from datetime import datetime, date
from typing import List, Optional, Any, Dict
from enum import Enum
# Removed pydantic EmailStr, conint, validator as they are not used directly in these DB models
# Validation should happen at the application layer before DB interaction.

# DO NOT import from buyer_concierge.models here to avoid circular dependencies.
# Define local structures for DB storage if needed, or use very basic types for JSON.

# Enum for currency, shared between RFQ and Quote tables for consistency
class PydanticCurrency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    JPY = "JPY"

# Enum for RFQ Status
class RFQStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    QUOTED = "QUOTED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED" # Retained for historical context or future use
    CANCELLED = "CANCELLED"
    # Added a comment here to try and force re-evaluation / bust cache 06-July

# Local simplified structures for JSONB fields in DB models
# These don't need to be full Pydantic models from buyer_concierge.models for storage.
class BomItemStored(SQLModel): # Renamed to avoid confusion with potential PydanticBomItem
    partNumber: str
    qty: int
    spec: str

class QuotedItemStored(SQLModel): # Renamed for clarity
    partNumber: str
    quantity: int
    unitPrice: float
    leadTimeDays: int

# Base for RFQ, defining common fields
class RFQBase(SQLModel):
    client_rfq_id: Optional[str] = Field(default=None, index=True, description="Client-provided RFQ ID for their tracking")
    # Ensure List type hint uses the locally defined model for JSON storage
    bom_items: List[BomItemStored] = Field(sa_column=Column(JSON))
    currency: PydanticCurrency = Field(default=PydanticCurrency.USD)
    deadline: date
    status: RFQStatus = Field(
        default=RFQStatus.PENDING,
        sa_column=Column(SQLAlchemyEnum(RFQStatus, name="rfqstatus", create_type=True))
    )

# RFQ table model
class RFQTable(RFQBase, table=True):
    __tablename__ = "rfq_table" # Explicit table name
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, sa_column_kwargs={"onupdate": datetime.utcnow})

    # Relationship to quotes
    quotes: List["QuoteTable"] = Relationship(back_populates="rfq")

# Base for Quote, defining common fields
class QuoteBase(SQLModel):
    rfq_table_id: int = Field(foreign_key="rfq_table.id", index=True)
    supplier_id: str = Field(index=True)
    # Ensure List type hint uses the locally defined model for JSON storage
    quoted_items: List[QuotedItemStored] = Field(sa_column=Column(JSON))
    total_price: float
    currency: PydanticCurrency = Field(default=PydanticCurrency.USD)
    valid_until: date

# Quote table model
class QuoteTable(QuoteBase, table=True):
    __tablename__ = "quote_table" # Explicit table name
    id: Optional[int] = Field(default=None, primary_key=True)
    received_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    # Relationship to RFQ
    rfq: "RFQTable" = Relationship(back_populates="quotes")

# Note: pgvector for embeddings would be a separate table, e.g., MessageEmbeddingsTable
# linking to conversation_id or message_id. 

# Explicitly rebuild models to resolve forward references and finalize relationships - REMOVED
# RFQTable.model_rebuild()
# QuoteTable.model_rebuild() 