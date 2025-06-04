# A2A-Agent: SMB Procurement Concierge MVP

This project implements a proof-of-concept "SMB Procurement Concierge" using Google's Agent-to-Agent (A2A) protocol. 
The primary goal is to demonstrate a robust, scalable foundation for building multi-agent systems for procurement-related tasks.

## Project Overview

The system consists of two main autonomous agent services:

1.  **`BuyerConcierge`**: This service acts on behalf of a small-to-medium business (SMB) buyer. It can:
    *   Accept a Request for Quotation (RFQ) containing a Bill of Materials (BOM).
    *   Communicate with supplier agents to obtain quotes for the items in the RFQ.
    *   Store RFQ and quote data.
    *   (Future) Provide status updates and aggregated quote information.

2.  **`SupplierQuoter`**: This service acts as a mock supplier agent. It can:
    *   Receive an RFQ from the `BuyerConcierge`.
    *   Generate a quote based on a predefined mock product catalog.
    *   Return the quote to the `BuyerConcierge`.

Both services are built using Python, FastAPI, and Pydantic, and are designed to be containerized with Docker.

## Key Features & Technologies

*   **A2A Protocol**: Demonstrates basic agent-to-agent communication.
*   **FastAPI**: For building efficient and modern APIs for each agent.
*   **Pydantic**: For data validation and settings management, ensuring clear data contracts based on JSON Schemas.
*   **SQLModel**: For database interaction in the `BuyerConcierge` service, storing RFQs and Quotes in a PostgreSQL database.
*   **Docker & Docker Compose**: For containerization and easy local development setup of the multi-service application.
*   **Pytest**: For comprehensive unit and integration testing.
*   **Clean Architecture Principles**: Applied to structure services for maintainability and testability.

## Getting Started & Detailed Instructions

For detailed instructions on:

*   Project structure
*   Running the application locally using Docker Compose
*   Manual testing with cURL examples
*   Executing unit and integration tests

Please refer to the **[A2A Procurement Application README](./a2a-procurement/README.md)**.

## Development & Contributions

This project is currently in an early MVP stage. Contributions and suggestions are welcome.
(Further details on contribution guidelines, development setup beyond Docker, and CI/CD will be added as the project evolves.)

## License

This project is licensed under the [MIT License] (./LICENSE).
