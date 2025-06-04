import pytest
from fastapi.testclient import TestClient
from supplier_quoter.main import app, verify_token, SUPPLIER_ID
from supplier_quoter.catalog import PRODUCT_CATALOG, DEFAULT_UNKNOWN_ITEM_PRICE, DEFAULT_UNKNOWN_ITEM_LEAD_TIME_DAYS
import datetime
import uuid # For JSON-RPC request ID

# Override the verify_token dependency for testing
async def override_verify_token():
    return "mock_token"

app.dependency_overrides[verify_token] = override_verify_token

client = TestClient(app)

def test_get_agent_card():
    response = client.get("/.well-known/agent.json")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Supplier Quoter"
    assert data["entrypoint"] == "/a2a"
    assert "capabilities" in data

def test_handle_rfq_and_quote_success_known_items():
    part_number_1 = "PN-001" 
    qty_1 = 10
    part_number_2 = "PN-003" 
    qty_2 = 5

    rfq_params = {
        "bom": [
            {"partNumber": part_number_1, "qty": qty_1, "spec": "Test spec for PN-001"},
            {"partNumber": part_number_2, "qty": qty_2, "spec": "Test spec for PN-003"}
        ],
        "currency": "USD",
        "deadline": (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    }
    
    rpc_request_id = str(uuid.uuid4())
    json_rpc_payload = {
        "jsonrpc": "2.0",
        "id": rpc_request_id,
        "method": "SubmitRFQ",
        "params": rfq_params
    }

    response = client.post("/a2a", json=json_rpc_payload)
    assert response.status_code == 200
    
    response_data = response.json()
    assert response_data.get("jsonrpc") == "2.0"
    assert response_data.get("id") == rpc_request_id
    assert "result" in response_data
    assert "error" not in response_data

    quote = response_data["result"]
    
    assert "rfqId" in quote 
    assert isinstance(quote["rfqId"], str)
    assert quote["rfqId"].startswith("SQ-RFQ-") 

    assert quote["supplierId"] == SUPPLIER_ID
    assert len(quote["items"]) == len(rfq_params["bom"])
    assert quote["currency"] == rfq_params["currency"]
    
    item1_catalog = PRODUCT_CATALOG[part_number_1]
    item2_catalog = PRODUCT_CATALOG[part_number_2]
    expected_price_item1 = item1_catalog["unit_price"] * qty_1
    expected_price_item2 = item2_catalog["unit_price"] * qty_2
    expected_total_price = round(expected_price_item1 + expected_price_item2, 2)

    assert quote["items"][0]["partNumber"] == part_number_1
    assert quote["items"][0]["quantity"] == qty_1
    assert quote["items"][0]["unitPrice"] == item1_catalog["unit_price"]
    assert quote["items"][0]["leadTimeDays"] == item1_catalog["lead_time_days"]

    assert quote["items"][1]["partNumber"] == part_number_2
    assert quote["items"][1]["quantity"] == qty_2
    assert quote["items"][1]["unitPrice"] == item2_catalog["unit_price"]
    assert quote["items"][1]["leadTimeDays"] == item2_catalog["lead_time_days"]
    
    assert quote["totalPrice"] == expected_total_price
    assert "validUntil" in quote
    
    valid_until_date = datetime.date.fromisoformat(quote["validUntil"])
    expected_valid_until = datetime.date.today() + datetime.timedelta(days=7)
    assert valid_until_date == expected_valid_until

def test_handle_rfq_invalid_rpc_method():
    rpc_request_id = str(uuid.uuid4())
    json_rpc_payload = {
        "jsonrpc": "2.0",
        "id": rpc_request_id,
        "method": "InvalidSubmitRFQMethod", # Incorrect method
        "params": {"bom": [], "currency": "USD", "deadline": datetime.date.today().isoformat()} # Dummy params
    }
    response = client.post("/a2a", json=json_rpc_payload)
    assert response.status_code == 200 # JSON-RPC errors often return HTTP 200
    response_data = response.json()
    assert response_data.get("jsonrpc") == "2.0"
    assert response_data.get("id") == rpc_request_id
    assert "error" in response_data
    assert response_data["error"]["code"] == -32601 # Method not found
    assert "Method not found" in response_data["error"]["message"]

def test_handle_rfq_invalid_params_for_submitrfq():
    # Test for when params for SubmitRFQ are themselves invalid (e.g., missing bom)
    # This should be caught by Pydantic validation of SubmitRFQ within the JsonRpcRequest model.
    # FastAPI typically returns HTTP 422 for this before our custom JSON-RPC error handling.
    rpc_request_id = str(uuid.uuid4())
    json_rpc_payload = {
        "jsonrpc": "2.0",
        "id": rpc_request_id,
        "method": "SubmitRFQ",
        "params": { 
            # "bom" is missing
            "currency": "USD",
            "deadline": (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        }
    }
    response = client.post("/a2a", json=json_rpc_payload)
    assert response.status_code == 422 # Pydantic validation error for JsonRpcRequest.params (SubmitRFQ)

def test_handle_rfq_and_quote_unknown_item():
    unknown_part_number = "PN-UNKNOWN-999"
    qty = 3
    rfq_params = {
        "bom": [
            {"partNumber": unknown_part_number, "qty": qty, "spec": "Spec for unknown item"}
        ],
        "currency": "EUR",
        "deadline": (datetime.date.today() + datetime.timedelta(days=15)).isoformat()
    }
    rpc_request_id = str(uuid.uuid4())
    json_rpc_payload = {
        "jsonrpc": "2.0",
        "id": rpc_request_id,
        "method": "SubmitRFQ",
        "params": rfq_params
    }
    response = client.post("/a2a", json=json_rpc_payload)
    assert response.status_code == 200
    response_data = response.json()
    assert response_data.get("jsonrpc") == "2.0"
    assert response_data.get("id") == rpc_request_id
    assert "result" in response_data
    quote = response_data["result"]

    assert quote["supplierId"] == SUPPLIER_ID
    assert quote["items"][0]["partNumber"] == unknown_part_number
    assert quote["items"][0]["quantity"] == qty
    assert quote["items"][0]["unitPrice"] == DEFAULT_UNKNOWN_ITEM_PRICE
    assert quote["items"][0]["leadTimeDays"] == DEFAULT_UNKNOWN_ITEM_LEAD_TIME_DAYS
    expected_total_price = round(DEFAULT_UNKNOWN_ITEM_PRICE * qty, 2)
    assert quote["totalPrice"] == expected_total_price

def test_handle_rfq_and_quote_mixed_items():
    known_part_number = "PN-002"
    known_qty = 2
    unknown_part_number = "PN-SPECIAL-ORDER-001"
    unknown_qty = 7
    rfq_params = {
        "bom": [
            {"partNumber": known_part_number, "qty": known_qty, "spec": "Spec for PN-002"},
            {"partNumber": unknown_part_number, "qty": unknown_qty, "spec": "Spec for special order"}
        ],
        "currency": "USD",
        "deadline": (datetime.date.today() + datetime.timedelta(days=20)).isoformat()
    }
    rpc_request_id = str(uuid.uuid4())
    json_rpc_payload = {
        "jsonrpc": "2.0",
        "id": rpc_request_id,
        "method": "SubmitRFQ",
        "params": rfq_params
    }
    response = client.post("/a2a", json=json_rpc_payload)
    assert response.status_code == 200
    response_data = response.json()
    assert "result" in response_data
    quote = response_data["result"]

    item_known_catalog = PRODUCT_CATALOG[known_part_number]
    expected_price_known_item = item_known_catalog["unit_price"] * known_qty
    expected_price_unknown_item = DEFAULT_UNKNOWN_ITEM_PRICE * unknown_qty
    expected_total_price = round(expected_price_known_item + expected_price_unknown_item, 2)
    assert quote["totalPrice"] == expected_total_price

def test_handle_rfq_and_quote_empty_bom():
    rfq_params = {
        "bom": [], 
        "currency": "USD",
        "deadline": (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    }
    rpc_request_id = str(uuid.uuid4())
    json_rpc_payload = {
        "jsonrpc": "2.0",
        "id": rpc_request_id,
        "method": "SubmitRFQ",
        "params": rfq_params
    }
    response = client.post("/a2a", json=json_rpc_payload)
    assert response.status_code == 200
    response_data = response.json()
    assert "result" in response_data
    quote = response_data["result"]

    assert len(quote["items"]) == 0
    assert quote["totalPrice"] == 0.0

# Add more test cases as needed 