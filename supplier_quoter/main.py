from fastapi import FastAPI, Depends, HTTPException, Header, Body
from fastapi.responses import JSONResponse
import json
from typing import List, Optional, Union, Annotated
import datetime
import uuid
from pydantic import BaseModel, conint, Field
from enum import Enum

# Use models from the new models.py
from .models import SubmitRFQ, Quote, QuotedItem, BomItem, JsonRpcRequest, JsonRpcSuccessResponse, JsonRpcErrorResponse, JsonRpcErrorDetail
from .catalog import PRODUCT_CATALOG, DEFAULT_UNKNOWN_ITEM_PRICE, DEFAULT_UNKNOWN_ITEM_LEAD_TIME_DAYS

# from shared.auth import verify_token # Placeholder
from shared.logging import get_logger
from shared.settings import settings # Import settings

logger = get_logger(__name__)

app = FastAPI(title="Supplier Quoter", version="v1")

SUPPLIER_ID = "SupplierQuoter_OnlineMartInc-v1"

async def verify_token(authorization: Annotated[str | None, Header()] = None) -> str:
    # In a real app, this would involve JWT decoding and verification.
    # For MVP, we'll use a simple hardcoded bearer token check.

    # If TEST_AUTH_BYPASS is true, allow the request
    if settings.TEST_AUTH_BYPASS.lower() == 'true':
        logger.warning("SupplierQuoter auth bypassed via TEST_AUTH_BYPASS=true")
        # Return a consistent bypass token, or the original if present
        if authorization:
            try:
                _, _, actual_token = authorization.partition(" ")
                return actual_token if actual_token else "test-bypass-token"
            except ValueError:
                return "test-bypass-token" # Should not happen with typical headers
        return "test-bypass-token"

    expected_scheme = "Bearer"
    expected_token = "test-token" # Only this token is valid for supplier_quoter

    if not authorization:
        logger.warning("SupplierQuoter verify_token: No Authorization header. Raising 401.")
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        scheme, _, actual_token = authorization.partition(" ")
    except ValueError:
        logger.warning("SupplierQuoter verify_token: Invalid Authorization header format. Raising 401.")
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    if scheme.lower() != expected_scheme.lower():
        logger.warning(f"SupplierQuoter verify_token: Scheme '{scheme}' not '{expected_scheme}'. Raising 401.")
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")

    if actual_token != expected_token:
        # Corrected f-string: use single quotes for internal literals directly
        logger.warning(f"SupplierQuoter token '{actual_token if actual_token else '<None>'}' not 'test-token'. Raising 401.")
        raise HTTPException(status_code=401, detail="Invalid token")
    
    logger.info(f"SupplierQuoter verify_token: Successfully verified token for '{actual_token}'")
    return actual_token # Return token if valid, for potential logging or user identification

@app.post("/a2a", response_model=None)
async def handle_rfq_and_quote(rpc_request: JsonRpcRequest = Body(...), token_claims: str = Depends(verify_token)):
    logger.info(f"SupplierQuoter received JSON-RPC request with token: '{token_claims}', method: {rpc_request.method}, id: {rpc_request.id}")
    
    if rpc_request.method != "SubmitRFQ":
        error_detail = JsonRpcErrorDetail(code=-32601, message="Method not found")
        return JSONResponse(status_code=200, content=JsonRpcErrorResponse(id=rpc_request.id, error=error_detail).model_dump(mode='json'))

    actual_rfq_payload: SubmitRFQ = rpc_request.params
    logger.debug(f"Extracted RFQ payload: {actual_rfq_payload.model_dump_json(indent=2)}")

    try:
        quoted_items = []
        total_price = 0.0

        for item in actual_rfq_payload.bom:
            catalog_entry = PRODUCT_CATALOG.get(item.partNumber)
            if catalog_entry:
                unit_price = catalog_entry["unit_price"]
                lead_time = catalog_entry["lead_time_days"]
            else:
                unit_price = DEFAULT_UNKNOWN_ITEM_PRICE
                lead_time = DEFAULT_UNKNOWN_ITEM_LEAD_TIME_DAYS
                logger.warning(f"Part number {item.partNumber} not found in catalog, using defaults.")
            
            if unit_price <= 0: unit_price = 0.01

            quoted_items.append(QuotedItem(
                partNumber=item.partNumber,
                quantity=item.qty,
                unitPrice=unit_price,
                leadTimeDays=lead_time
            ))
            total_price += unit_price * item.qty

        total_price = round(total_price, 2)
        if total_price <= 0 and quoted_items: total_price = 0.01 
        elif not quoted_items: total_price = 0.0

        quote_rfq_id = f"SQ-RFQ-{uuid.uuid4().hex[:8]}"

        quote_result = Quote(
            rfqId=quote_rfq_id, 
            supplierId=SUPPLIER_ID,
            items=quoted_items,
            totalPrice=total_price,
            currency=actual_rfq_payload.currency, 
            validUntil=datetime.date.today() + datetime.timedelta(days=7)
        )
        
        logger.info(f"SupplierQuoter responding with Quote: {quote_result.model_dump_json(indent=2)}")
        success_response = JsonRpcSuccessResponse(id=rpc_request.id, result=quote_result)
        return JSONResponse(status_code=200, content=success_response.model_dump(mode='json'))

    except Exception as e:
        logger.error(f"Error processing RFQ in supplier_quoter: {e}", exc_info=True)
        error_detail = JsonRpcErrorDetail(code=-32000, message=f"Server error: {str(e)}")
        # For unhandled errors, JSON-RPC spec says id can be null if request id cannot be determined.
        # Here, we always have rpc_request.id.
        return JSONResponse(status_code=200, content=JsonRpcErrorResponse(id=rpc_request.id, error=error_detail).model_dump(mode='json'))

@app.get("/.well-known/agent.json", include_in_schema=False)
async def get_agent_card():
    try:
        with open("supplier_quoter/agent_card.json", "r") as f:
            agent_card_data = json.load(f)
        return agent_card_data
    except Exception as e:
        logger.error(f"Could not load supplier_quoter/agent_card.json: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Agent configuration not available.") 