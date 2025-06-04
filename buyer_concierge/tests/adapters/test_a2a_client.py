import pytest
import httpx
from pydantic import BaseModel
from uuid import uuid4
import json # Import json at the top

from buyer_concierge.adapters.a2a_client import A2AClient

# Dummy Pydantic model for testing payloads
class DummyPayload(BaseModel):
    message: str
    value: int

@pytest.mark.asyncio
async def test_a2a_client_post_successful(httpx_mock):
    target_url = "http://supplier.example.com/a2a"
    action = "TestAction"
    payload = DummyPayload(message="Hello", value=123)
    expected_result_content = {"status": "success", "data": "mock_data"}

    def response_callback(request: httpx.Request):
        parsed_json_request = json.loads(request.content.decode())
        assert parsed_json_request.get("method") == action
        assert parsed_json_request.get("params") == payload.model_dump(mode='json')
        request_id = parsed_json_request.get("id")
        assert request_id is not None
        mock_response_data = {"jsonrpc": "2.0", "id": request_id, "result": expected_result_content}
        return httpx.Response(200, json=mock_response_data)

    httpx_mock.add_callback(response_callback, url=target_url, method="POST")
    client = A2AClient()
    api_result = await client.post(url=target_url, action=action, payload=payload)

    assert api_result == expected_result_content # Client should return the "result" field directly

@pytest.mark.asyncio
async def test_a2a_client_post_with_token(httpx_mock):
    target_url = "http://supplier.example.com/a2a_token"
    action = "TestActionWithToken"
    payload = DummyPayload(message="Secure Hello", value=456)
    token = "test-secret-token"
    expected_result_content = {"status": "authenticated_success"}

    def response_callback(request: httpx.Request):
        assert request.headers.get("Authorization") == f"Bearer {token}"
        parsed_json_request = json.loads(request.content.decode())
        assert parsed_json_request.get("method") == action
        request_id = parsed_json_request.get("id")
        assert request_id is not None
        mock_response_data = {"jsonrpc": "2.0", "id": request_id, "result": expected_result_content}
        return httpx.Response(200, json=mock_response_data)

    httpx_mock.add_callback(response_callback, url=target_url, method="POST")
    client = A2AClient(token=token)
    api_result = await client.post(url=target_url, action=action, payload=payload)

    assert api_result == expected_result_content

@pytest.mark.asyncio
async def test_a2a_client_post_http_error(httpx_mock):
    target_url = "http://supplier.example.com/a2a_error"
    action = "ActionCausesError"
    payload = DummyPayload(message="Error trigger", value=789)
    # Simulate a non-200 HTTP error that is NOT a JSON-RPC error response
    httpx_mock.add_response(url=target_url, method="POST", status_code=500, text="Internal Server Error")
    client = A2AClient()
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        await client.post(url=target_url, action=action, payload=payload)
    assert excinfo.value.response.status_code == 500

@pytest.mark.asyncio
async def test_a2a_client_post_json_rpc_error(httpx_mock):
    target_url = "http://supplier.example.com/a2a_jsonrpc_error"
    action = "ActionJsonRpcError"
    payload = DummyPayload(message="RPC Error", value=101)
    expected_error_content = {"code": -32000, "message": "Server error", "data": "details"}
    request_id_holder = {"id": None} # To capture the request ID for assertion

    def response_callback(request: httpx.Request):
        parsed_json_request = json.loads(request.content.decode())
        request_id = parsed_json_request.get("id")
        assert request_id is not None
        request_id_holder["id"] = request_id # Capture for later assertion
        mock_response_data = {"jsonrpc": "2.0", "id": request_id, "error": expected_error_content}
        return httpx.Response(200, json=mock_response_data) 

    httpx_mock.add_callback(response_callback, url=target_url, method="POST")
    client = A2AClient()
    api_response_envelope = await client.post(url=target_url, action=action, payload=payload)

    assert "error" in api_response_envelope
    assert api_response_envelope["error"] == expected_error_content
    assert api_response_envelope.get("id") == request_id_holder["id"]
    assert api_response_envelope.get("jsonrpc") == "2.0"

@pytest.mark.asyncio
async def test_a2a_client_post_mismatched_id(httpx_mock, caplog):
    target_url = "http://supplier.example.com/a2a_mismatched_id"
    action = "ActionMismatchedId"
    payload = DummyPayload(message="ID Test", value=112)
    expected_result_content = {"status": "id_mismatch_test_ok"}
    
    # Store actual sent ID and server's mismatched ID
    sent_request_id_holder = {"id": None}
    mismatched_response_id = str(uuid4())

    def response_callback(request: httpx.Request):
        parsed_json_request = json.loads(request.content.decode())
        sent_request_id_holder["id"] = parsed_json_request.get("id") # Capture actual client sent ID
        assert sent_request_id_holder["id"] is not None
        
        mock_response_data = {"jsonrpc": "2.0", "id": mismatched_response_id, "result": expected_result_content}
        return httpx.Response(200, json=mock_response_data)

    httpx_mock.add_callback(response_callback, url=target_url, method="POST")
    client = A2AClient()
    with caplog.at_level("WARNING"):
        api_result = await client.post(url=target_url, action=action, payload=payload)
    
    assert api_result == expected_result_content # Client should still return result despite ID mismatch warning
    assert "Mismatched ID in JSON-RPC response" in caplog.text
    assert sent_request_id_holder["id"] in caplog.text # Check if original sent ID is in log
    assert mismatched_response_id in caplog.text # Check if mismatched response ID is in log

@pytest.mark.asyncio
async def test_a2a_client_post_invalid_jsonrpc_version(httpx_mock):
    target_url = "http://supplier.example.com/a2a_bad_version"
    action = "ActionBadVersion"
    payload = DummyPayload(message="Version Test", value=113)

    def response_callback(request: httpx.Request):
        parsed_json_request = json.loads(request.content.decode())
        request_id = parsed_json_request.get("id")
        assert request_id is not None
        mock_response_data = {"jsonrpc": "1.0", "id": request_id, "result": {"status": "version_test_fail"}}
        return httpx.Response(200, json=mock_response_data)

    httpx_mock.add_callback(response_callback, url=target_url, method="POST")
    client = A2AClient()
    with pytest.raises(ValueError, match="Invalid JSON-RPC version in response"):
        await client.post(url=target_url, action=action, payload=payload)

@pytest.mark.asyncio
async def test_a2a_client_missing_result_or_error(httpx_mock):
    target_url = "http://supplier.example.com/a2a_missing_fields"
    action = "ActionMissingFields"
    payload = DummyPayload(message="Missing Test", value=114)

    def response_callback(request: httpx.Request):
        parsed_json_request = json.loads(request.content.decode())
        request_id = parsed_json_request.get("id")
        assert request_id is not None
        # Response is missing 'result' and 'error'
        mock_response_data = {"jsonrpc": "2.0", "id": request_id}
        return httpx.Response(200, json=mock_response_data)

    httpx_mock.add_callback(response_callback, url=target_url, method="POST")
    client = A2AClient()
    with pytest.raises(ValueError, match="Invalid JSON-RPC response: missing 'result' or 'error' field"):
        await client.post(url=target_url, action=action, payload=payload) 