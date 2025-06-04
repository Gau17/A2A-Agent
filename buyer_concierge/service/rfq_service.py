from sqlalchemy.ext.asyncio import AsyncSession
from ..adapters.a2a_client import A2AClient
from ..models import SubmitRFQ, Quote
from shared.settings import settings
from shared.logging import get_logger
from pydantic import ValidationError
from typing import List, Dict, Any, Optional
import httpx
import uuid

# Import the AbstractRepository port and RFQStatus
from .ports import AbstractRepository
from shared.models_db import RFQStatus, RFQTable, QuoteTable

logger = get_logger(__name__)

class RFQService:
    def __init__(self, a2a_client: A2AClient, db_repository: AbstractRepository, session: AsyncSession):
        self.a2a_client = a2a_client
        self.db_repository = db_repository
        self.session = session

    async def process_rfq(self, rfq_payload: SubmitRFQ, incoming_token: str | None) -> Dict[str, Any]:
        """
        Processes an incoming RFQ.
        Manages the transaction for database operations.
        """
        logger.info(f"RFQService processing RFQ. BOM size: {len(rfq_payload.bom)}")
        db_rfq: Optional[RFQTable] = None
        generated_client_rfq_id = uuid.uuid4().hex
        logger.info(f"Generated client_rfq_id: {generated_client_rfq_id} for new RFQ")

        try:
            # Step 1 - Persist RFQ to database
            db_rfq = await self.db_repository.add_rfq(rfq_payload, client_rfq_id=generated_client_rfq_id)
            await self.db_repository.update_rfq_status(db_rfq.id, RFQStatus.PROCESSING)
            # No commit yet, will commit at the end of successful flow or for FAILED status

            # Step 2 - Call supplier agent(s)
            supplier_url = settings.SUPPLIER_QUOTER_URL
            # auth_token_for_supplier = settings.SUPPLIER_AUTH_TOKEN # This might be None - REMOVED
            # self.a2a_client.token = auth_token_for_supplier # Set token for this specific call if needed - REMOVED
            
            logger.info(f"Sending RFQ to supplier: {supplier_url}")
            supplier_direct_quote_data = await self.a2a_client.post(
                url=supplier_url, 
                action="SubmitRFQ", 
                payload=rfq_payload
            )
            logger.info("Received quote data from supplier")
            logger.debug(f"Supplier quote data: {supplier_direct_quote_data}")

            # Validate and persist the quote received from the supplier
            parsed_supplier_quote = Quote(**supplier_direct_quote_data)
            logger.info(f"Successfully parsed quote from supplier ID: {parsed_supplier_quote.supplierId}")
            
            await self.db_repository.add_quote_to_rfq(rfq_db_id=db_rfq.id, quote_data=parsed_supplier_quote)
            await self.db_repository.update_rfq_status(db_rfq.id, RFQStatus.QUOTED)
            await self.session.commit()
            logger.info(f"Successfully processed RFQ, final status: QUOTED. DB RFQ ID: {db_rfq.id}, Client RFQ ID: {generated_client_rfq_id}")
            return {
                "status": "success", 
                "message": "Quote received and processed successfully", 
                "rfq_id": db_rfq.id,
                "client_rfq_id": generated_client_rfq_id,
                "quote": parsed_supplier_quote.model_dump(mode='json')
            }
        
        except httpx.HTTPStatusError as e:
            rfq_id_for_log = db_rfq.id if db_rfq else "N/A"
            logger.error(f"HTTP error from supplier for RFQ DB ID {rfq_id_for_log}: {e.response.status_code} - {e.response.text}")
            if db_rfq: # If RFQ was created, try to mark as FAILED and commit
                try:
                    await self.db_repository.update_rfq_status(db_rfq.id, RFQStatus.FAILED)
                    await self.session.commit() # Commit the FAILED status
                    logger.info(f"RFQ DB ID {db_rfq.id} status updated to FAILED and committed due to supplier HTTP error.")
                except Exception as db_exc:
                    logger.error(f"Failed to update RFQ status to FAILED and commit for DB ID {db_rfq.id} after supplier HTTP error: {db_exc}. Rolling back.")
                    await self.session.rollback() # Rollback IF the commit of FAILED status fails
            else: # Should not happen if add_rfq succeeded before supplier call, but as a safeguard
                await self.session.rollback()
            return {"status": "error", "message": f"Supplier communication error: {e.response.status_code}", "details": e.response.text, "client_rfq_id": generated_client_rfq_id, "db_rfq_id": rfq_id_for_log}

        except httpx.RequestError as e:
            # Handle connection errors, timeouts, etc.
            logger.error(f"Connection error to supplier for RFQ DB ID {db_rfq.id if db_rfq else 'N/A'}: {e}", exc_info=True)
            if db_rfq:
                await self.db_repository.update_rfq_status(db_rfq.id, RFQStatus.FAILED)
            await self.session.commit()
            return {"status": "error", "message": f"Failed to connect to supplier: {str(e)}"}

        except ValidationError as e:
            rfq_id_for_log = db_rfq.id if db_rfq else "N/A"
            logger.error(f"Failed to validate quote data for RFQ DB ID {rfq_id_for_log}: {e.errors()}. Data: {supplier_direct_quote_data if 'supplier_direct_quote_data' in locals() else 'N/A'}")
            if db_rfq: # Mark as FAILED and commit this status
                await self.db_repository.update_rfq_status(db_rfq.id, RFQStatus.FAILED)
                await self.session.commit()
            return {"status": "error", "message": "Invalid quote format from supplier", "details": e.errors(), "client_rfq_id": generated_client_rfq_id, "db_rfq_id": rfq_id_for_log}
        
        except Exception as e:
            rfq_id_for_log = db_rfq.id if db_rfq else "N/A"
            logger.error(f"Generic error during RFQ processing (RFQ DB ID {rfq_id_for_log}): {str(e)}", exc_info=True)
            if db_rfq: 
                try:
                    await self.db_repository.update_rfq_status(db_rfq.id, RFQStatus.FAILED)
                    # For generic errors after initial RFQ creation, we commit FAILED status if possible,
                    # otherwise the rollback below will handle it.
                    await self.session.commit()
                except Exception as final_update_err:
                    logger.error(f"Could not update RFQ {db_rfq.id} to FAILED before rollback: {final_update_err}")
            
            await self.session.rollback() # Rollback for generic errors
            return {"status": "error", "message": f"Failed to process RFQ (DB ID {rfq_id_for_log}): {str(e)}", "details": str(e), "client_rfq_id": generated_client_rfq_id, "db_rfq_id": rfq_id_for_log} 