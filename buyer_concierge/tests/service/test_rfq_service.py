import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch # Added patch
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession # Added for spec
import uuid # Import uuid directly
import datetime # Added for datetime

from buyer_concierge.service.rfq_service import RFQService
from buyer_concierge.models import SubmitRFQ, Quote as PydanticQuote, BomItem, Currency as PydanticCurrency, QuotedItem
from shared.models_db import RFQTable, QuoteTable, RFQStatus, PydanticCurrency as DBEnumCurrency, BomItemStored # Corrected import, Added BomItemStored
from buyer_concierge.adapters.a2a_client import A2AClient
from buyer_concierge.adapters.db_repository import SQLModelRepository
from buyer_concierge.service.ports import AbstractRepository
from pydantic import ValidationError # To test validation error scenarios
import httpx # To simulate httpx errors
from fastapi.encoders import jsonable_encoder

# Fixtures for mock dependencies
@pytest.fixture
def mock_a2a_client() -> AsyncMock:
    # client = AsyncMock(spec=A2AClient) # Replaced spec with manual attribute/method setup
    client = AsyncMock()
    # Configure the mock to have a 'token' attribute that can be set and retrieved
    # client.configure_mock(token=None) # Replaced by direct attribute assignment below
    client.token = None # Add 'token' as a simple attribute

    # Mock the 'post' method as it's called by the service
    client.post = AsyncMock()
    
    # Default successful response (direct quote data, not JSON-RPC envelope from A2AClient's perspective)
    client.post.return_value = {
            "rfqId": "rfq_from_supplier_123",
            "supplierId": "SupplierQuoter_MockTestInc",
            "items": [
                {
                    "partNumber": "PN-001",
                    "quantity": 10,
                    "unitPrice": 120.50,
                    "leadTimeDays": 7
                }
            ],
            "totalPrice": 1205.00,
            "currency": "USD",
            "validUntil": "2025-01-15"
    }
    return client

@pytest.fixture
def mock_db_repository() -> AsyncMock:
    repo = AsyncMock(spec=AbstractRepository)
    
    # Default mock for add_rfq - this will be overridden in specific tests if needed
    mock_rfq_table_instance = RFQTable(
        id=1, 
        client_rfq_id=None, # Default, test will often override this
        bom_items=[BomItem(partNumber="PN-001", qty=10, spec="Test Part")],
        currency=DBEnumCurrency.USD,
        deadline=date(2024, 12, 31),
        status=RFQStatus.PENDING
    )
    repo.add_rfq.return_value = mock_rfq_table_instance

    async def mock_update_status(rfq_id, status, client_rfq_id=None):
        # This mock might need to access the actual client_rfq_id if it was set on the instance
        # For now, let's assume the test that sets client_rfq_id also ensures add_rfq returns it correctly.
        current_rfq_mock = await repo.get_rfq_by_id(rfq_id) # Use the existing mock for get_rfq_by_id
        
        updated_rfq = RFQTable(
            id=rfq_id,
            status=status, 
            client_rfq_id=current_rfq_mock.client_rfq_id if current_rfq_mock else None,
            bom_items=current_rfq_mock.bom_items if current_rfq_mock else [], 
            currency=current_rfq_mock.currency if current_rfq_mock else DBEnumCurrency.USD, 
            deadline=current_rfq_mock.deadline if current_rfq_mock else date(2024,1,1)
        )
        return updated_rfq
    repo.update_rfq_status.side_effect = mock_update_status

    repo.add_quote_to_rfq.return_value = QuoteTable(
        id=101, 
        rfq_table_id=1, 
        supplier_id="SupplierQuoter_MockTestInc",
        quoted_items=[QuotedItem(partNumber="PN-001", quantity=10, unitPrice=120.50, leadTimeDays=7)],
        total_price=1205.00,
        currency=DBEnumCurrency.USD,
        valid_until=date(2025, 1, 15)
    )
    repo.get_rfq_by_id.return_value = mock_rfq_table_instance
    return repo

@pytest.fixture # New fixture for mock session
def mock_session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    return session

# Sample RFQ data for tests
@pytest.fixture
def sample_submit_rfq_payload() -> SubmitRFQ:
    return SubmitRFQ(
        bom=[BomItem(partNumber="PN-001", qty=10, spec="Test Part specification")],
        currency=PydanticCurrency.USD,
        deadline=date(2024, 12, 31)
    )

TEST_UUID_HEX = "test-uuid-abcd-1234"

@pytest.mark.asyncio
@patch('buyer_concierge.service.rfq_service.uuid.uuid4') # Patch where uuid is used
async def test_process_rfq_successful(
    mock_uuid4: MagicMock, # Patched object is passed as an arg
    mock_a2a_client: AsyncMock,
    mock_db_repository: AsyncMock,
    mock_session: AsyncMock,
    sample_submit_rfq_payload: SubmitRFQ
):
    mock_uuid4.return_value.hex = TEST_UUID_HEX

    # Configure the add_rfq mock to return an RFQTable with the correct client_rfq_id
    # This ensures that when the service later uses db_rfq.client_rfq_id, it gets the mocked one.
    mocked_added_rfq = RFQTable(
        id=1, # Consistent with previous mock setup
        client_rfq_id=TEST_UUID_HEX, # <<<< Important for the response check
        bom_items=jsonable_encoder(sample_submit_rfq_payload.bom),
        currency=DBEnumCurrency.USD,
        deadline=sample_submit_rfq_payload.deadline,
        status=RFQStatus.PENDING
    )
    mock_db_repository.add_rfq.return_value = mocked_added_rfq

    rfq_service = RFQService(
        a2a_client=mock_a2a_client, 
        db_repository=mock_db_repository,
        session=mock_session
    )
    incoming_token = "test_auth_token_123"

    result = await rfq_service.process_rfq(sample_submit_rfq_payload, incoming_token)

    assert result["status"] == "success"
    assert result["message"] == "Quote received and processed successfully"
    assert result["rfq_id"] == 1
    assert result["client_rfq_id"] == TEST_UUID_HEX # Assert the generated ID
    assert "quote" in result
    assert result["quote"]["supplierId"] == "SupplierQuoter_MockTestInc"

    mock_a2a_client.post.assert_called_once_with(
        url="http://supplier_quoter:8080/a2a",
        action="SubmitRFQ",
        payload=sample_submit_rfq_payload
    )

    mock_db_repository.add_rfq.assert_called_once_with(
        sample_submit_rfq_payload, 
        client_rfq_id=TEST_UUID_HEX # Assert it was called with the generated ID
    )
    
    update_status_calls = mock_db_repository.update_rfq_status.call_args_list
    assert len(update_status_calls) == 2
    # When update_rfq_status is called, its side_effect 'mock_update_status' might need client_rfq_id too.
    # For simplicity here, we assume the mock_update_status correctly handles/preserves client_rfq_id if it were passed.
    # The key is that add_rfq returned it correctly for the service's response.
    assert update_status_calls[0] == call(1, RFQStatus.PROCESSING) 
    assert update_status_calls[1] == call(1, RFQStatus.QUOTED)

    expected_quote_pydantic = PydanticQuote(
        rfqId="rfq_from_supplier_123",
        supplierId="SupplierQuoter_MockTestInc",
        items=[QuotedItem(partNumber="PN-001", quantity=10, unitPrice=120.50, leadTimeDays=7)],
        totalPrice=1205.00,
        currency=PydanticCurrency.USD,
        validUntil=date(2025, 1, 15)
    )
    mock_db_repository.add_quote_to_rfq.assert_called_once_with(rfq_db_id=1, quote_data=expected_quote_pydantic)

    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_awaited()

@pytest.mark.asyncio
@patch('buyer_concierge.service.rfq_service.uuid.uuid4') # Added patch
async def test_process_rfq_a2a_client_returns_json_rpc_error(
    mock_uuid4: MagicMock, # Added mock_uuid4
    mock_a2a_client: AsyncMock, mock_db_repository: AsyncMock, mock_session: AsyncMock,
    sample_submit_rfq_payload: SubmitRFQ
):
    mock_uuid4.return_value.hex = TEST_UUID_HEX # Configure mock uuid
    rfq_service = RFQService(a2a_client=mock_a2a_client, db_repository=mock_db_repository, session=mock_session)
    json_rpc_error_response_from_client = {
        "jsonrpc": "2.0", "id": "mock_rpc_id_error_456",
        "error": {"code": -32000, "message": "Supplier generic error", "data": "Optional error details"}
    }
    mock_a2a_client.post.return_value = json_rpc_error_response_from_client
    result = await rfq_service.process_rfq(sample_submit_rfq_payload, "test_token")

    assert result["status"] == "error"
    assert result["message"] == "Invalid quote format from supplier" 
    assert "details" in result
    assert isinstance(result["details"], list)
    
    mock_db_repository.add_rfq.assert_called_once_with( # Corrected assertion
        sample_submit_rfq_payload, 
        client_rfq_id=TEST_UUID_HEX
    )

@pytest.mark.asyncio
@patch('buyer_concierge.service.rfq_service.uuid.uuid4')
async def test_process_rfq_a2a_client_raises_http_error(
    mock_uuid4: MagicMock, 
    mock_a2a_client: AsyncMock, mock_db_repository: AsyncMock, mock_session: AsyncMock,
    sample_submit_rfq_payload: SubmitRFQ
):
    mock_uuid4.return_value.hex = TEST_UUID_HEX
    
    mocked_added_rfq_for_http_error = RFQTable(
        id=1, client_rfq_id=TEST_UUID_HEX, 
        bom_items=jsonable_encoder(sample_submit_rfq_payload.bom),
        currency=DBEnumCurrency.USD, deadline=sample_submit_rfq_payload.deadline, status=RFQStatus.PENDING
    )
    mock_db_repository.add_rfq.return_value = mocked_added_rfq_for_http_error
    # Ensure get_rfq_by_id (used by update_status mock if service calls it) also returns this instance
    mock_db_repository.get_rfq_by_id.return_value = mocked_added_rfq_for_http_error 

    rfq_service = RFQService(a2a_client=mock_a2a_client, db_repository=mock_db_repository, session=mock_session)
    mock_request = httpx.Request(method="POST", url="http://supplier_quoter:8080/a2a")
    http_error_response = httpx.Response(status_code=500, request=mock_request, content=b"Server error details")
    http_error = httpx.HTTPStatusError(message="Simulated HTTP 500 error", request=mock_request, response=http_error_response)
    mock_a2a_client.post.side_effect = http_error

    # Simulate that the commit of FAILED status also fails, to trigger rollback
    mock_session.commit.side_effect = Exception("Simulated commit failure during error handling")

    result = await rfq_service.process_rfq(sample_submit_rfq_payload, "test_token")

    assert result["status"] == "error"
    assert result["message"] == f"Supplier communication error: {http_error_response.status_code}"
    assert result["details"] == http_error_response.text
    assert result["client_rfq_id"] == TEST_UUID_HEX
    assert result["db_rfq_id"] == 1 # From mocked add_rfq
    
    mock_db_repository.add_rfq.assert_called_once_with(
        sample_submit_rfq_payload,
        client_rfq_id=TEST_UUID_HEX
    )
    # Check that status was updated to PROCESSING then FAILED
    update_status_calls = mock_db_repository.update_rfq_status.call_args_list
    assert call(1, RFQStatus.PROCESSING) in update_status_calls
    assert call(1, RFQStatus.FAILED) in update_status_calls

    # With the new logic, a commit is attempted for the FAILED status.
    # We are testing the case where this commit FAILS, leading to a rollback.
    mock_session.commit.assert_awaited_once() 
    mock_session.rollback.assert_awaited_once()

@pytest.mark.asyncio
@patch('buyer_concierge.service.rfq_service.uuid.uuid4') 
async def test_process_rfq_supplier_returns_invalid_quote_data(
    mock_uuid4: MagicMock, mock_a2a_client: AsyncMock, mock_db_repository: AsyncMock,
    mock_session: AsyncMock, sample_submit_rfq_payload: SubmitRFQ
):
    mock_uuid4.return_value.hex = TEST_UUID_HEX 
    mocked_added_rfq = RFQTable(id=1, client_rfq_id=TEST_UUID_HEX, bom_items=jsonable_encoder(sample_submit_rfq_payload.bom), currency=DBEnumCurrency.USD, deadline=sample_submit_rfq_payload.deadline, status=RFQStatus.PENDING)
    mock_db_repository.add_rfq.return_value = mocked_added_rfq
    mock_db_repository.get_rfq_by_id.return_value = mocked_added_rfq

    rfq_service = RFQService(a2a_client=mock_a2a_client, db_repository=mock_db_repository, session=mock_session)
    invalid_quote_data_from_client = {
        "rfqId": "rfq_from_supplier_bad_data_123", 
        "supplierId": "SupplierQuoter_MockTestInc_BadData", 
        "items": [{"partNumber": "PN-001", "quantity": 10, "unitPrice": "NOT_A_FLOAT"}],
        "currency": "USD",
        "validUntil": "2025-01-15" 
        # Missing totalPrice
    }
    mock_a2a_client.post.return_value = invalid_quote_data_from_client
    result = await rfq_service.process_rfq(sample_submit_rfq_payload, "test_token")

    assert result["status"] == "error"
    assert result["message"] == "Invalid quote format from supplier"
    assert "details" in result
    assert isinstance(result["details"], list) 
    
    mock_db_repository.add_rfq.assert_called_once_with(
        sample_submit_rfq_payload,
        client_rfq_id=TEST_UUID_HEX # Corrected assertion
    )

@pytest.mark.asyncio
@patch('buyer_concierge.service.rfq_service.uuid.uuid4')
async def test_process_rfq_db_add_rfq_fails(
    mock_uuid4: MagicMock, mock_a2a_client: AsyncMock, mock_db_repository: AsyncMock,
    mock_session: AsyncMock, sample_submit_rfq_payload: SubmitRFQ
):
    mock_uuid4.return_value.hex = TEST_UUID_HEX 
    rfq_service = RFQService(a2a_client=mock_a2a_client, db_repository=mock_db_repository, session=mock_session)
    db_error = Exception("Simulated DB error on add_rfq")
    mock_db_repository.add_rfq.side_effect = db_error
    result = await rfq_service.process_rfq(sample_submit_rfq_payload, "test_token")

    assert result["status"] == "error"
    assert result["message"] == f"Failed to process RFQ (DB ID N/A): {str(db_error)}"
    assert result["client_rfq_id"] == TEST_UUID_HEX
    assert result["db_rfq_id"] == "N/A"

    mock_db_repository.add_rfq.assert_called_once_with(
        sample_submit_rfq_payload,
        client_rfq_id=TEST_UUID_HEX
    )

@pytest.mark.asyncio
@patch('buyer_concierge.service.rfq_service.uuid.uuid4')
async def test_process_rfq_db_add_quote_fails(
    mock_uuid4: MagicMock, mock_a2a_client: AsyncMock, mock_db_repository: AsyncMock,
    mock_session: AsyncMock, sample_submit_rfq_payload: SubmitRFQ
):
    mock_uuid4.return_value.hex = TEST_UUID_HEX
    mocked_added_rfq = RFQTable(
        id=1, client_rfq_id=TEST_UUID_HEX, 
        bom_items=[{'partNumber': "PN-001", 'qty': 10, 'spec': "Test Part specification"}], # Use dict conforming to BomItemStored
        currency=DBEnumCurrency.USD, # Corrected from PydanticCurrency to DBEnumCurrency for RFQTable mock
        deadline=sample_submit_rfq_payload.deadline, 
        status=RFQStatus.PENDING,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow()
    )
    mock_db_repository.add_rfq.return_value = mocked_added_rfq
    mock_db_repository.get_rfq_by_id.return_value = mocked_added_rfq

    rfq_service = RFQService(a2a_client=mock_a2a_client, db_repository=mock_db_repository, session=mock_session)
    db_quote_error = Exception("Simulated DB error on add_quote")
    mock_db_repository.add_quote_to_rfq.side_effect = db_quote_error
    result = await rfq_service.process_rfq(sample_submit_rfq_payload, "test_token")

    assert result["status"] == "error"
    assert result["message"] == f"Failed to process RFQ (DB ID 1): {str(db_quote_error)}"
    assert result["client_rfq_id"] == TEST_UUID_HEX
    assert result["db_rfq_id"] == 1

    mock_db_repository.add_rfq.assert_called_once_with(
        sample_submit_rfq_payload,
        client_rfq_id=TEST_UUID_HEX
    )
    # Further assertions for add_quote_to_rfq call, status updates, and session calls can be added here
    # For example, check that add_quote_to_rfq was called with the correct arguments before it raised the error.
    # Check that RFQStatus was set to PROCESSING.
    update_status_calls = mock_db_repository.update_rfq_status.call_args_list
    assert call(1, RFQStatus.PROCESSING) in update_status_calls
    # Depending on the exact path taken by the service with the restored models_db.py, 
    # either commit or rollback will be called for the generic exception.
    # The service now tries to commit FAILED status, then rolls back if that fails.
    # Given the generic exception, it will call rollback in the generic handler.
    mock_session.rollback.assert_awaited_once() 