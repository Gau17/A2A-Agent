import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncConnection, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel # For SQLModel.metadata.create_all
from sqlalchemy import text # Import text for raw SQL
from sqlalchemy.exc import DBAPIError # For catching specific DB errors
import datetime
from typing import AsyncGenerator, List
import uuid # Import uuid
import logging # For logging warnings

from buyer_concierge.adapters.db_repository import SQLModelRepository
from buyer_concierge.models import SubmitRFQ as PydanticSubmitRFQ, BomItem as PydanticBomItem, Currency as PydanticAppCurrency
from buyer_concierge.models import Quote as PydanticQuote, QuotedItem as PydanticQuotedItem
from shared.models_db import RFQTable, QuoteTable, RFQStatus, PydanticCurrency as DBPydanticCurrency
from shared.settings import settings

logger = logging.getLogger(__name__) # Setup logger for the fixture

# Use a separate test database engine if possible, or ensure tables are managed
# For now, we use the same DB defined in docker-compose but manage tables.

# Pytest fixture to create tables ONCE per session using a DEDICATED engine/connection
@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables_fixture(): 
    ddl_engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with ddl_engine.connect() as connection:
        try:
            logger.info("Attempting to drop all tables and types...")
            await connection.run_sync(SQLModel.metadata.drop_all)
            await connection.commit() # Commit after successful drop_all
            logger.info("Successfully dropped all tables and types.")
        except DBAPIError as e:
            await connection.rollback() # Rollback the failed transaction from drop_all
            if "DependentObjectsStillExistError" in str(e) and "rfqstatus" in str(e):
                logger.warning(
                    f"'drop_all' failed to drop rfqstatus enum due to dependencies. Attempting manual drop. Error: {e}"
                )
                try:
                    logger.info("Manually dropping type rfqstatus CASCADE...")
                    await connection.execute(text("DROP TYPE IF EXISTS rfqstatus CASCADE;"))
                    await connection.commit() # Commit the manual drop
                    logger.info("Successfully dropped type rfqstatus CASCADE.")
                except Exception as manual_drop_e:
                    await connection.rollback()
                    logger.error(f"Failed to manually drop rfqstatus enum: {manual_drop_e}")
                    # Decide if this should be a fatal error for the test session
                    # For now, we'll let create_all try, but this is risky.
            else:
                logger.error(f"Unexpected DBAPIError during drop_all: {e}")
                raise # Re-raise if it's not the known enum issue or other DBAPIError
        except Exception as e:
            await connection.rollback()
            logger.error(f"Non-DBAPIError during drop_all: {e}")
            raise # Re-raise other errors

        logger.info("Attempting to create all tables...")
        await connection.run_sync(SQLModel.metadata.create_all)
        await connection.commit()
        logger.info("Successfully created all tables.")
        
    await ddl_engine.dispose()
    yield
    # Optional teardown: 
    # async with ddl_engine.connect() as connection:
    #     await connection.run_sync(SQLModel.metadata.drop_all)
    #     await connection.commit()
    # await ddl_engine.dispose()

# Pytest fixture for an AsyncEngine (FUNCTION-SCOPED: new engine per test)
@pytest_asyncio.fixture(scope="function") # Changed to function scope
async def engine() -> AsyncGenerator[AsyncEngine, None]: # Now an async generator
    test_engine = create_async_engine(settings.DATABASE_URL, echo=True)
    yield test_engine
    await test_engine.dispose() # Dispose of the engine after each test

# Pytest fixture for an AsyncSession per test function, using the function-scoped engine
@pytest_asyncio.fixture(scope="function") # Explicitly function scope
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]: 
    async with engine.connect() as connection: 
        async with connection.begin() as transaction: 
            AsyncSessionLocal = sessionmaker(
                bind=connection, 
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with AsyncSessionLocal() as session:
                try:
                    yield session
                finally:
                    await transaction.rollback()

@pytest.fixture
def sample_rfq_payload() -> PydanticSubmitRFQ:
    return PydanticSubmitRFQ(
        bom=[
            PydanticBomItem(partNumber="PN-TEST-001", qty=10, spec="Test Part 1"),
            PydanticBomItem(partNumber="PN-TEST-002", qty=5, spec="Test Part 2")
        ],
        currency=PydanticAppCurrency.USD,
        deadline=datetime.date.today() + datetime.timedelta(days=30)
    )

@pytest.fixture
def sample_quote_payload() -> PydanticQuote:
    return PydanticQuote(
        rfqId="client-rfq-123", # This ID is from the client's perspective of RFQ
        supplierId="SUPPLIER_TEST_01",
        items=[
            PydanticQuotedItem(partNumber="PN-TEST-001", quantity=10, unitPrice=5.50, leadTimeDays=7),
            PydanticQuotedItem(partNumber="PN-TEST-002", quantity=5, unitPrice=12.75, leadTimeDays=10)
        ],
        totalPrice= (10 * 5.50) + (5 * 12.75),
        currency=PydanticAppCurrency.EUR, # Test with a different currency for quote
        validUntil=datetime.date.today() + datetime.timedelta(days=15)
    )

@pytest.mark.asyncio
async def test_add_rfq_successful(db_session: AsyncSession, sample_rfq_payload: PydanticSubmitRFQ):
    repository = SQLModelRepository(session=db_session)
    client_id = "client-rfq-test-add"
    
    db_rfq = await repository.add_rfq(rfq_data=sample_rfq_payload, client_rfq_id=client_id)
    
    assert db_rfq is not None
    assert db_rfq.id is not None # This requires the object to be refreshed after commit if ID is auto-gen
    assert db_rfq.client_rfq_id == client_id
    # Ensure bom_items are actually dicts as stored by jsonable_encoder
    assert isinstance(db_rfq.bom_items, list)
    assert all(isinstance(item, dict) for item in db_rfq.bom_items)
    assert db_rfq.bom_items[0]["partNumber"] == sample_rfq_payload.bom[0].partNumber
    assert db_rfq.currency == DBPydanticCurrency.USD 
    assert db_rfq.deadline == sample_rfq_payload.deadline
    assert db_rfq.status == RFQStatus.PENDING

    # Verify it's in the DB by fetching within the same session/transaction for this test
    # The repository.add_rfq committed its work within the transaction.
    # The fixture will rollback this transaction entirely later.
    fetched_rfq = await db_session.get(RFQTable, db_rfq.id)
    assert fetched_rfq is not None
    assert fetched_rfq.client_rfq_id == client_id

@pytest.mark.asyncio
async def test_get_rfq_by_id(db_session: AsyncSession, sample_rfq_payload: PydanticSubmitRFQ):
    repository = SQLModelRepository(session=db_session)
    added_rfq = await repository.add_rfq(rfq_data=sample_rfq_payload, client_rfq_id="get-by-id-test")
    assert added_rfq.id is not None

    fetched_rfq = await repository.get_rfq_by_id(added_rfq.id)
    assert fetched_rfq is not None
    assert fetched_rfq.id == added_rfq.id
    assert fetched_rfq.client_rfq_id == "get-by-id-test"
    # Check bom_items are dicts (how they are stored)
    assert isinstance(fetched_rfq.bom_items[0], dict)
    assert fetched_rfq.bom_items[0]["partNumber"] == sample_rfq_payload.bom[0].partNumber

@pytest.mark.asyncio
async def test_get_rfq_by_id_not_found(db_session: AsyncSession):
    repository = SQLModelRepository(session=db_session)
    fetched_rfq = await repository.get_rfq_by_id(99999)
    assert fetched_rfq is None

@pytest.mark.asyncio
async def test_get_rfq_by_client_id(db_session: AsyncSession, sample_rfq_payload: PydanticSubmitRFQ):
    repository = SQLModelRepository(session=db_session)
    client_id = "client-specific-id-test"
    added_rfq = await repository.add_rfq(rfq_data=sample_rfq_payload, client_rfq_id=client_id)
    assert added_rfq is not None

    fetched_rfq = await repository.get_rfq_by_client_id(client_id)
    assert fetched_rfq is not None
    assert fetched_rfq.client_rfq_id == client_id

@pytest.mark.asyncio
async def test_get_rfq_by_client_id_not_found(db_session: AsyncSession):
    repository = SQLModelRepository(session=db_session)
    fetched_rfq = await repository.get_rfq_by_client_id("non-existent-client-id")
    assert fetched_rfq is None

@pytest.mark.asyncio
async def test_update_rfq_status(db_session: AsyncSession, sample_rfq_payload: PydanticSubmitRFQ):
    repository = SQLModelRepository(session=db_session)
    test_client_id = uuid.uuid4().hex
    added_rfq = await repository.add_rfq(rfq_data=sample_rfq_payload, client_rfq_id=test_client_id)
    assert added_rfq.id is not None
    assert added_rfq.client_rfq_id == test_client_id
    
    updated_rfq = await repository.update_rfq_status(added_rfq.id, RFQStatus.PROCESSING)
    assert updated_rfq is not None
    assert updated_rfq.status == RFQStatus.PROCESSING

    fetched_rfq = await db_session.get(RFQTable, added_rfq.id)
    assert fetched_rfq is not None
    assert fetched_rfq.status == RFQStatus.PROCESSING

@pytest.mark.asyncio
async def test_update_rfq_status_not_found(db_session: AsyncSession):
    repository = SQLModelRepository(session=db_session)
    updated_rfq = await repository.update_rfq_status(88888, RFQStatus.COMPLETED)
    assert updated_rfq is None

@pytest.mark.asyncio
async def test_add_quote_to_rfq_successful(db_session: AsyncSession, sample_rfq_payload: PydanticSubmitRFQ, sample_quote_payload: PydanticQuote):
    repository = SQLModelRepository(session=db_session)
    test_client_id = uuid.uuid4().hex
    added_rfq = await repository.add_rfq(rfq_data=sample_rfq_payload, client_rfq_id=test_client_id)
    assert added_rfq.id is not None
    assert added_rfq.client_rfq_id == test_client_id
    
    db_quote = await repository.add_quote_to_rfq(rfq_db_id=added_rfq.id, quote_data=sample_quote_payload)
    
    assert db_quote is not None
    assert db_quote.id is not None
    assert db_quote.rfq_table_id == added_rfq.id
    assert db_quote.supplier_id == sample_quote_payload.supplierId
    assert isinstance(db_quote.quoted_items, list)
    assert all(isinstance(item, dict) for item in db_quote.quoted_items)
    assert db_quote.quoted_items[0]["partNumber"] == sample_quote_payload.items[0].partNumber
    assert db_quote.total_price == sample_quote_payload.totalPrice
    assert db_quote.currency == DBPydanticCurrency.EUR
    assert db_quote.valid_until == sample_quote_payload.validUntil

    fetched_quote = await db_session.get(QuoteTable, db_quote.id)
    assert fetched_quote is not None
    assert fetched_quote.supplier_id == sample_quote_payload.supplierId

@pytest.mark.asyncio
async def test_get_quotes_for_rfq(db_session: AsyncSession, sample_rfq_payload: PydanticSubmitRFQ, sample_quote_payload: PydanticQuote):
    repository = SQLModelRepository(session=db_session)
    test_client_id = uuid.uuid4().hex
    added_rfq = await repository.add_rfq(rfq_data=sample_rfq_payload, client_rfq_id=test_client_id)
    assert added_rfq.id is not None
    assert added_rfq.client_rfq_id == test_client_id

    quote1_payload = sample_quote_payload
    quote2_payload = sample_quote_payload.model_copy(deep=True)
    quote2_payload.supplierId = "SUPPLIER_TEST_02"
    quote2_payload.totalPrice = 200.00

    await repository.add_quote_to_rfq(rfq_db_id=added_rfq.id, quote_data=quote1_payload)
    await repository.add_quote_to_rfq(rfq_db_id=added_rfq.id, quote_data=quote2_payload)

    quotes: List[QuoteTable] = await repository.get_quotes_for_rfq(added_rfq.id)
    assert len(quotes) == 2
    supplier_ids = {q.supplier_id for q in quotes}
    assert "SUPPLIER_TEST_01" in supplier_ids
    assert "SUPPLIER_TEST_02" in supplier_ids
    # Check quoted_items are dicts
    assert isinstance(quotes[0].quoted_items[0], dict)

@pytest.mark.asyncio
async def test_get_quotes_for_rfq_no_quotes(db_session: AsyncSession, sample_rfq_payload: PydanticSubmitRFQ):
    repository = SQLModelRepository(session=db_session)
    test_client_id = uuid.uuid4().hex
    added_rfq = await repository.add_rfq(rfq_data=sample_rfq_payload, client_rfq_id=test_client_id)
    assert added_rfq.id is not None
    assert added_rfq.client_rfq_id == test_client_id

    quotes: List[QuoteTable] = await repository.get_quotes_for_rfq(added_rfq.id)
    assert len(quotes) == 0

@pytest.mark.asyncio
async def test_get_quotes_for_rfq_rfq_not_found(db_session: AsyncSession):
    repository = SQLModelRepository(session=db_session)
    quotes: List[QuoteTable] = await repository.get_quotes_for_rfq(77777)
    assert len(quotes) == 0 