import pytest
import pytest_asyncio
import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker
from shared.settings import settings
from typing import AsyncGenerator

# Changed scope to "function"
@pytest_asyncio.fixture(scope="function")
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    # When running tests inside buyer_concierge container, target localhost:8080 (internal port)
    # BUYER_HOST and BUYER_PORT from settings are more for host-based tests.
    # For in-container, the app is at localhost:8080 (container's own port)
    async with httpx.AsyncClient(base_url="http://localhost:8080") as client:
        yield client

# Fixture for the database engine, scoped to session for efficiency if DB doesn't change
# but function scope might be safer if tests alter DB schema or global state related to engine.
# For now, let's keep db_session creating its own engine to ensure full isolation.

@pytest_asyncio.fixture(scope="function") 
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    # Use settings.DATABASE_URL directly which is configured for in-container access
    db_engine = create_async_engine(settings.DATABASE_URL, echo=settings.DB_ECHO_LOG)
    yield db_engine
    await db_engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    # The original db_session fixture created its own engine and disposed of it.
    # This version will use a shared engine per test function.
    # Connection-level transaction for test isolation
    async with engine.connect() as connection:
        await connection.begin()
        async_session = AsyncSession(bind=connection, expire_on_commit=False)
        yield async_session
        await connection.rollback() # Rollback the transaction
        await async_session.close() # Close the session
        # The connection is automatically closed when exiting the `async with engine.connect()` block. 