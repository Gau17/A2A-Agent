from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List

from pydantic import BaseModel, Field, conint


class BomItem(BaseModel):
    partNumber: str
    qty: conint(ge=1)
    spec: str


class Currency(Enum):
    USD = 'USD'
    EUR = 'EUR'
    JPY = 'JPY'


class SubmitRFQ(BaseModel):
    bom: List[BomItem]
    currency: Currency
    deadline: date


# Models based on quote-v1.json
class QuotedItem(BaseModel): # Corresponds to the items in the quote schema
    partNumber: str
    quantity: int = Field(..., ge=1)
    unitPrice: float = Field(..., gt=0) # exclusiveMinimum: 0 means > 0
    leadTimeDays: int = Field(..., ge=0) # minimum: 0 means >= 0


class Quote(BaseModel): # Corresponds to the main Quote schema (was SubmitQuote title)
    rfqId: str
    supplierId: str
    items: List[QuotedItem]
    totalPrice: float = Field(..., gt=0) # exclusiveMinimum: 0 means > 0
    currency: Currency # Reusing the Currency enum from above
    validUntil: date 