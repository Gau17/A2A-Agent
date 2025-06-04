FROM python:3.11-slim

WORKDIR /app

# Copy pyproject.toml for reference, but we'll install deps explicitly for this service image
COPY pyproject.toml . 

# Install runtime dependencies for BuyerConcierge + testing tools
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    "pydantic>=2.7" \
    pgvector \
    sqlmodel \
    authlib \
    langchain \
    asyncpg \
    opentelemetry-api \
    jsonschema \
    pydantic-settings \
    httpx \
    pytest \
    pytest-asyncio \
    pytest-httpx

# Copy application and shared code
COPY ./buyer_concierge /app/buyer_concierge
COPY ./shared /app/shared
COPY ./libs /app/libs
COPY ./supplier_quoter /app/supplier_quoter

# Copy the tests for the buyer_concierge service
COPY ./buyer_concierge/tests /app/buyer_concierge/tests

# Copy integration tests into the image
COPY ./tests/integration /app/tests/integration

ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["uvicorn", "buyer_concierge.main:app", "--host", "0.0.0.0", "--port", "8080"] 