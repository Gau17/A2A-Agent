import pytest
from fastapi.testclient import TestClient
from fastapi.encoders import jsonable_encoder
from unittest.mock import AsyncMock, patch
import json
import datetime

from buyer_concierge.main import app, get_rfq_service
from buyer_concierge.service.rfq_service import RFQService
from buyer_concierge.models import SubmitRFQ, BomItem, Currency
from shared.settings import settings

client = TestClient(app)

# --- Tests for /.well-known/agent.json ---
def test_get_agent_card_successful():
    response = client.get("/.well-known/agent.json")
    assert response.status_code == 200
    expected_agent_card = {
        "name": "Buyer Concierge",
        "description": "Submits RFQs and collates supplier quotes",
        "entrypoint": "/a2a",
        "capabilities": [
            { "actionType": "SubmitRFQ", "schema": "https://your-domain.com/schemas/rfq-v1.json" }
        ],
        "auth": { "type": "oauth2-service-account" }
    }
    assert response.json() == expected_agent_card

@patch("builtins.open", side_effect=FileNotFoundError("File not found mock"))
@patch("buyer_concierge.main.logger.error")
def test_get_agent_card_file_not_found(mock_logger_error, mock_open):
    response = client.get("/.well-known/agent.json")
    assert response.status_code == 500
    assert response.json() == {"detail": "Agent configuration not available."}
    mock_logger_error.assert_called_once()
    assert "Could not load agent_card.json" in mock_logger_error.call_args[0][0]

# --- Fixtures and Mocks for /a2a endpoint tests ---
@pytest.fixture
def mock_rfq_service() -> AsyncMock:
    service = AsyncMock(spec=RFQService)
    return service

@pytest.fixture(autouse=True)
def override_rfq_service_dependency(mock_rfq_service: AsyncMock):
    app.dependency_overrides[get_rfq_service] = lambda: mock_rfq_service
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def valid_rfq_model_instance() -> SubmitRFQ:
    """Returns a valid SubmitRFQ model instance."""
    return SubmitRFQ(
        bom=[
            BomItem(partNumber="PN-MAIN-001", qty=100, spec="Main test part")
        ],
        currency=Currency.USD,
        deadline=datetime.date.today() + datetime.timedelta(days=15)
    )

# --- Tests for /a2a endpoint ---
@pytest.mark.asyncio
async def test_handle_rfq_successful(mock_rfq_service: AsyncMock, valid_rfq_model_instance: SubmitRFQ):
    mock_rfq_service.process_rfq.return_value = {
        "status": "success",
        "message": "Quote received and processed successfully",
        "rfq_id": 123,
        "client_rfq_id": "client-rfq-abc",
        "quote": {"supplierId": "SupplierTest", "totalPrice": 1200.00}
    }

    payload = jsonable_encoder(valid_rfq_model_instance)
    response = client.post("/a2a", json=payload, headers={"Authorization": "Bearer test-token"})

    if response.status_code != 200:
        print("Unexpected status code:", response.status_code)
        try:
            print("Response JSON:", response.json())
        except Exception as e:
            print("Could not parse response JSON:", e)
            print("Response text:", response.text)

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["status"] == "success"
    assert response_data["rfq_id"] == 123
    assert response_data["quote"]["supplierId"] == "SupplierTest"
    mock_rfq_service.process_rfq.assert_awaited_once()
    called_with_payload, called_with_token = mock_rfq_service.process_rfq.call_args[0]
    assert isinstance(called_with_payload, SubmitRFQ)
    assert called_with_payload.currency == Currency.USD
    assert called_with_token == "test-token"

@pytest.mark.asyncio
async def test_handle_rfq_service_returns_error(mock_rfq_service: AsyncMock, valid_rfq_model_instance: SubmitRFQ):
    mock_rfq_service.process_rfq.return_value = {
        "status": "error",
        "message": "Supplier communication failed",
        "details": "Connection refused"
    }

    payload = jsonable_encoder(valid_rfq_model_instance)
    response = client.post("/a2a", json=payload, headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Connection refused"}
    mock_rfq_service.process_rfq.assert_awaited_once()

@pytest.mark.asyncio
async def test_handle_rfq_pydantic_validation_error():
    invalid_payload_dict = {
        "bom": [
            {"partNumber": "PN-MAIN-001", "qty": 0, "spec": "Qty zero should fail"}
        ],
        "currency": "INVALID_CURRENCY",
        "deadline": "not-a-date"
    }
    response = client.post("/a2a", json=invalid_payload_dict, headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 422

@pytest.mark.asyncio
@patch.object(settings, 'TEST_AUTH_BYPASS', 'true')
async def test_handle_rfq_auth_bypass_enabled(mock_rfq_service: AsyncMock, valid_rfq_model_instance: SubmitRFQ):
    mock_rfq_service.process_rfq.return_value = {"status": "success", "rfq_id": 789}

    payload = jsonable_encoder(valid_rfq_model_instance)
    response = client.post("/a2a", json=payload)

    assert response.status_code == 200
    assert response.json()["rfq_id"] == 789
    mock_rfq_service.process_rfq.assert_awaited_once()
    called_with_payload, called_with_token = mock_rfq_service.process_rfq.call_args[0]
    assert called_with_payload.bom == valid_rfq_model_instance.bom
    assert called_with_payload.currency == valid_rfq_model_instance.currency
    assert called_with_payload.deadline == valid_rfq_model_instance.deadline
    assert called_with_token == "test-bypass-token"

@pytest.mark.asyncio
@patch.object(settings, 'TEST_AUTH_BYPASS', 'false')
async def test_handle_rfq_no_auth_header_bypass_disabled(mock_rfq_service: AsyncMock, valid_rfq_model_instance: SubmitRFQ):
    mock_rfq_service.process_rfq.return_value = {"status": "success", "rfq_id": 101}

    payload = jsonable_encoder(valid_rfq_model_instance)
    response = client.post("/a2a", json=payload)

    assert response.status_code == 200
    assert response.json()["rfq_id"] == 101
    mock_rfq_service.process_rfq.assert_awaited_once()
    called_with_payload, called_with_token = mock_rfq_service.process_rfq.call_args[0]
    assert called_with_payload.bom == valid_rfq_model_instance.bom
    assert called_with_payload.currency == valid_rfq_model_instance.currency
    assert called_with_payload.deadline == valid_rfq_model_instance.deadline
    assert called_with_token == "dummy_token"

@pytest.mark.asyncio
@patch.object(settings, 'TEST_AUTH_BYPASS', 'false')
async def test_handle_rfq_malformed_bearer_token(mock_rfq_service: AsyncMock, valid_rfq_model_instance: SubmitRFQ):
    mock_rfq_service.process_rfq.return_value = {"status": "success", "rfq_id": 102}
    malformed_header = "NotBearer test-token"

    payload = jsonable_encoder(valid_rfq_model_instance)
    response = client.post("/a2a", json=payload, headers={"Authorization": malformed_header})

    assert response.status_code == 200
    assert response.json()["rfq_id"] == 102
    mock_rfq_service.process_rfq.assert_awaited_once()
    called_with_payload, called_with_token = mock_rfq_service.process_rfq.call_args[0]
    assert called_with_payload.bom == valid_rfq_model_instance.bom
    assert called_with_payload.currency == valid_rfq_model_instance.currency
    assert called_with_payload.deadline == valid_rfq_model_instance.deadline
    assert called_with_token == malformed_header 