# A2A Procurement Application Details

This document provides detailed instructions for running, testing, and interacting with the A2A Procurement application services (`buyer_concierge` and `supplier_quoter`).

For a high-level overview of the entire "SMB Procurement Concierge" project, please see the [main project README.md](../../README.md).

## Project Structure

```
.github/                    # GitHub Actions workflows
a2a-procurement/            # Main application source code and tests
  buyer_concierge/          # Buyer Concierge FastAPI application
    adapters/               # Adapters for external services (A2A client, DB)
    service/                # Core service logic for RFQs
    tests/                  # Unit tests for buyer_concierge
    main.py                 # FastAPI app definition for buyer
    models.py               # Pydantic models for buyer
    Dockerfile
  supplier_quoter/          # Supplier Quoter FastAPI application
    service/                # Core service logic for quoting (mocked)
    tests/                  # Unit tests for supplier_quoter
    main.py                 # FastAPI app definition for supplier
    models.py               # Pydantic models for supplier
    catalog.py              # Mock product catalog
    Dockerfile
  shared/                   # Shared utilities (DB, logging, settings, models_db)
  libs/                     # JSON schemas and potentially generated libraries
    schemas/
      rfq-v1.json
      quote-v1.json
  infra/                    # Infrastructure setup
    docker-compose.yml      # Docker Compose configuration
    terraform/              # Terraform scripts (if any)
  scripts/                  # Utility scripts (linting, testing)
  tests/                    # Integration tests
    integration/
      test_rfq_flow.py
      conftest.py
  .env.example              # Example environment variables
  pyproject.toml            # Project metadata and dependencies (Poetry)
  pytest.ini                # Pytest configuration
  README.md                 # This file
LICENSE                     # Main project license (if moved or copied here)
# README.md (root)          # Main project overview
```

## Running the Application with Docker Compose

All services are defined in `infra/docker-compose.yml` relative to the `a2a-procurement` directory.

1.  **Navigate to the a2a-procurement directory** (if not already there):
    ```bash
    # Ensure you are in the A2A-Agent/a2a-procurement directory
    # cd a2a-procurement 
    ```

2.  **Copy Environment File (if not already done)**:
    If you haven't set up your environment variables, copy the example:
    ```bash
    cp .env.example .env 
    ```
    Review and update `.env` if necessary (though defaults should work for local Docker setup).

3.  **Start all services**:
    This command will build the images if they don't exist (or if Dockerfile/context changed) and start the containers in detached mode.
    ```bash
    docker-compose -f infra/docker-compose.yml up -d --build
    ```

4.  **View logs (optional)**:
    To view logs for all services:
    ```bash
    docker-compose -f infra/docker-compose.yml logs -f
    ```
    To view logs for a specific service (e.g., `buyer_concierge`):
    ```bash
    docker-compose -f infra/docker-compose.yml logs -f buyer_concierge
    ```

5.  **Key Services and Ports**:
    -   `buyer_concierge`: Accessible on `http://localhost:8000` (host port mapped to container port 8080)
    -   `supplier_quoter`: Accessible on `http://localhost:8081` (host port mapped to container port 8080)
    -   `postgres`: Database service, port `5432` is exposed to the host but services connect via Docker network name `postgres`.

6.  **Stop all services**:
    ```bash
    docker-compose -f infra/docker-compose.yml down
    ```
    To remove volumes (e.g., PostgreSQL data):
    ```bash
    docker-compose -f infra/docker-compose.yml down -v
    ```

## Manual Testing with cURL

Once the services are running, you can send an RFQ to the `buyer_concierge`.

**Endpoint**: `POST http://localhost:8000/a2a`

**Headers**:
-   `Content-Type: application/json`
-   `Authorization: Bearer test-token` (The application is currently set up to bypass actual token validation if `TEST_AUTH_BYPASS` is true in settings, or if this specific test token is used with the mock verifier. In a production setup, a valid JWT would be required.)

**Sample Request Payload** (`SubmitRFQ` model):

```json
{
  "bom": [
    {
      "partNumber": "PN-001",
      "qty": 2,
      "spec": "Standard Widget"
    },
    {
      "partNumber": "PN-002",
      "qty": 5,
      "spec": "Premium Gadget"
    },
    {
      "partNumber": "PN-UNKNOWN",
      "qty": 10,
      "spec": "Mystery Item"
    }
  ],
  "currency": "USD",
  "deadline": "2024-12-31"
}
```

**cURL Command Example**:

Save the JSON payload above into a file named `rfq_payload.json` (ensure this file is in your current directory when running curl, or provide the correct path).

```bash
curl -X POST http://localhost:8000/a2a \
-H "Content-Type: application/json" \
-H "Authorization: Bearer test-token" \
-d @rfq_payload.json
```

**Expected Successful Response (200 OK)**:

The response will indicate success and include the quote received from the `supplier_quoter` (which uses a mock catalog).

```json
{
  "status": "success",
  "message": "Quote received and processed successfully",
  "rfq_id": 1, # This is the database ID of the RFQ in buyer_concierge
  "client_rfq_id": null, # Will be null as not implemented yet
  "quote": {
    "rfqId": "SQ-RFQ-xxxxxxxx", # Generated by supplier_quoter
    "supplierId": "SupplierQuoter_OnlineMartInc-v1",
    "items": [
      {
        "partNumber": "PN-001",
        "quantity": 2,
        "unitPrice": 10.50,       # From supplier_quoter catalog
        "leadTimeDays": 3
      },
      {
        "partNumber": "PN-002",
        "quantity": 5,
        "unitPrice": 25.99,       # From supplier_quoter catalog
        "leadTimeDays": 7
      },
      {
        "partNumber": "PN-UNKNOWN",
        "quantity": 10,
        "unitPrice": 99.99,       # Default for unknown items
        "leadTimeDays": 14
      }
    ],
    "totalPrice": 430.45,       # Calculated by supplier_quoter
    "currency": "USD",
    "validUntil": "YYYY-MM-DD"   # e.g., 7 days from quote generation
  }
}
```
*(Note: `rfq_id`, `SQ-RFQ-xxxxxxxx`, prices, and `validUntil` date will vary with each request and catalog content.)*

## Running Tests

Tests are run within their respective Docker containers to ensure environment consistency.
All commands should be run from the `A2A-Agent/a2a-procurement` directory.

1.  **Run `buyer_concierge` unit tests**:
    ```bash
    docker-compose -f infra/docker-compose.yml exec buyer_concierge python -m pytest /app/buyer_concierge/tests
    ```

2.  **Run `supplier_quoter` unit tests**:
    ```bash
    docker-compose -f infra/docker-compose.yml exec supplier_quoter python -m pytest /app/supplier_quoter/tests
    ```

3.  **Run Integration tests (from within `buyer_concierge` container)**:
    Ensure all services are up (`docker-compose -f infra/docker-compose.yml up -d`)
    ```bash
    docker-compose -f infra/docker-compose.yml exec buyer_concierge python -m pytest /app/tests/integration
    ```

For more verbose output, add `-v` to the `pytest` commands. 
