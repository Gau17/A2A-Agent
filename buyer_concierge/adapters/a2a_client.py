import httpx
from pydantic import BaseModel
from uuid import uuid4
from typing import Dict, Any, Optional
import json # Import json for JSONDecodeError

# Import settings to potentially get auth details or supplier URLs
from shared.settings import settings 
# It's good practice to use a logger
from shared.logging import get_logger

logger = get_logger(__name__)

class A2AClient:
    """
    A client for making A2A (Agent-to-Agent) JSON-RPC calls.
    """

    def __init__(self, base_url: str | None = None, token: str | None = None):
        """
        Initializes the A2A client.

        Args:
            base_url: The base URL of the target agent. Can be overridden per call.
            token: An authentication token to be used for requests.
        """
        self.base_url = base_url
        self.token = token # Placeholder for now, will be integrated with auth mechanism

    def _auth_hdr(self) -> Dict[str, str]:
        """
        Constructs the authorization header.
        Placeholder implementation.
        """
        logger.debug(f"A2AClient._auth_hdr called. self.token is: '{self.token}'")
        if self.token:
            # In a real scenario, this would be a JWT from an OAuth flow
            # or a pre-shared key depending on the auth strategy with the supplier.
            logger.debug(f"A2AClient._auth_hdr: Using token to create Bearer header: '{self.token}'")
            return {"Authorization": f"Bearer {self.token}"}
        # For the MVP, if no token, send no auth header or a test token.
        # The playbook mentions `verify_token` which implies Bearer tokens.
        # For now, let's assume a test token might be passed or configured.
        # If we use a fixed test token for the MVP:
        # return {"Authorization": "Bearer test-token-from-client"}
        logger.debug("A2AClient._auth_hdr: No token found, returning empty auth header.")
        return {} # No auth header if no token provided


    async def post(self, url: str, action: str, payload: BaseModel) -> Dict[str, Any]:
        """
        Sends a POST request to an A2A-compliant agent using JSON-RPC 2.0.

        Args:
            url: The full URL of the target agent's A2A entrypoint.
            action: The JSON-RPC method name (e.g., "SubmitRFQ").
            payload: The Pydantic model representing the request parameters.

        Returns:
            A dictionary containing the "result" field from the JSON-RPC response.
        
        Raises:
            ValueError: If the response is not valid JSON-RPC 2.0 or if IDs mismatch.
            httpx.HTTPStatusError: If the request returns an unsuccessful HTTP status code 
                                   (and it's not a JSON-RPC error response).
            httpx.RequestError: For other request-related issues (e.g., network error).
        """
        request_id = str(uuid4())
        
        envelope = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": action,
            "params": payload.model_dump(mode='json')
        }
        request_body = envelope # Use the JSON-RPC envelope

        headers = self._auth_hdr()
        headers["Content-Type"] = "application/json"
        
        target_url = url

        logger.info(f"Sending JSON-RPC request ID {request_id} to {target_url}, method: {action}")
        logger.debug(f"Request body: {request_body}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(target_url, json=request_body, headers=headers)
                
                response_data: Optional[Dict[str, Any]] = None

                if not response.is_success:
                    # Non-2xx response. Try to parse as JSON. If it's a JSON-RPC error, that's fine.
                    # If not JSON or not a JSON-RPC error, raise HTTPStatusError.
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" not in content_type.lower():
                        logger.error(f"HTTP error {response.status_code} from {target_url} (Content-Type: {content_type}): {response.text}")
                        response.raise_for_status() # Re-raise for non-JSON error content
                    
                    # Only attempt to parse as JSON if Content-Type suggests it might be JSON
                    try:
                        potential_error_data = response.json()
                        if potential_error_data.get("jsonrpc") == "2.0" and "error" in potential_error_data:
                            response_data = potential_error_data # It's a JSON-RPC error, proceed to common handling
                            logger.warning(f"Received JSON-RPC error with HTTP status {response.status_code} from {target_url}")
                        else:
                            # It was JSON, but not a JSON-RPC error. Raise for the HTTP status.
                            logger.error(f"HTTP error {response.status_code} from {target_url} (JSON, but not JSON-RPC error): {response.text}")
                            response.raise_for_status()
                    except json.JSONDecodeError: # Should be less likely now if content_type check is robust
                        # This might still happen if Content-Type is json but body is malformed
                        logger.error(f"HTTP error {response.status_code} from {target_url} (JSONDecodeError despite Content-Type {content_type}): {response.text}")
                        response.raise_for_status()
                else:
                    # is_success (2xx). Expect JSON.
                    response_data = response.json() 
                
                # At this point, response_data should be populated if no HTTPStatusError was raised
                if response_data is None: # Should not happen if logic above is correct
                    raise ValueError("Internal error: response_data not populated after HTTP processing")

                logger.info(f"Received response for JSON-RPC ID {request_id} from {target_url}")
                logger.debug(f"Response data: {response_data}")

                if response_data.get("jsonrpc") != "2.0":
                    raise ValueError("Invalid JSON-RPC version in response")
                
                if "id" in response_data and response_data["id"] != request_id:
                    logger.warning(f"Mismatched ID in JSON-RPC response. Expected {request_id}, got {response_data.get('id')}")

                if "error" in response_data:
                    return response_data # Return full envelope for JSON-RPC error
                
                if "result" in response_data:
                    return response_data["result"]
                else:
                    raise ValueError("Invalid JSON-RPC response: missing 'result' or 'error' field")

            except httpx.HTTPStatusError as e:
                # Logged by specific raise_for_status() calls or if client.post itself raises for non-2xx redirect etc.
                logger.error(f"HTTPStatusError during A2A call to {e.request.url if e.request else target_url}: {e.response.status_code}")
                raise
            except json.JSONDecodeError as e: # From response.json() on a 2xx that wasn't JSON
                logger.error(f"Failed to decode JSON from 2xx response from {target_url}: {e}")
                raise ValueError(f"Successful response from {target_url} was not valid JSON: {e}") from e
            except httpx.RequestError as e: # Network errors, timeouts, etc.
                logger.error(f"RequestError during A2A call to {target_url}: {e}")
                raise
            except ValueError as e: # Our own ValueErrors or other parsing issues
                logger.error(f"ValueError during A2A call processing for {target_url}: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error during A2A call to {target_url}: {e}", exc_info=True)
                raise 