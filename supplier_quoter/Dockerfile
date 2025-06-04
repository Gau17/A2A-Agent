FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml . 

# Install runtime dependencies for SupplierQuoter + testing tools
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    pydantic \
    pydantic-settings \
    httpx \
    # Add other specific runtime deps for supplier_quoter if any, e.g., from shared modules if used directly
    # For now, assuming it mainly relies on FastAPI/Pydantic for its own logic
    pytest \
    pytest-asyncio

# Copy application and shared code (if supplier uses them directly)
COPY ./supplier_quoter /app/supplier_quoter
COPY ./shared /app/shared
COPY ./libs /app/libs

# Copy the tests for the supplier_quoter service
COPY ./supplier_quoter/tests /app/supplier_quoter/tests

ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["uvicorn", "supplier_quoter.main:app", "--host", "0.0.0.0", "--port", "8080"] 