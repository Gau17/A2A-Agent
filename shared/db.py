from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from shared.settings import settings
from shared.logging import get_logger

# Import your SQLModel table definitions here
# This ensures that SQLModel.metadata knows about them.
from shared.models_db import RFQTable, QuoteTable # noqa

logger = get_logger(__name__)

# Create an async engine instance
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.LOG_LEVEL.upper() == "DEBUG", # Log SQL queries only if log level is DEBUG
    future=True # Use the new style execution for SQLAlchemy 2.0
)

# Create a configured "AsyncSession" class
AsyncSessionFactory = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False, # Prevent SQLAlchemy from expiring objects after commit
    autoflush=False, # Disable autoflush, manage manually for more control
)

async def get_async_session() -> AsyncSession:
    """Dependency to get an async database session."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            # Removed explicit commit from here; services should commit their own units of work.
            # await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def create_db_and_tables():
    """Utility function to create all tables defined by SQLModel metadata."""
    logger.info("Initializing database and creating tables if they don't exist...")
    async with async_engine.begin() as conn:
        try:
            # The first argument to run_sync should be a callable.
            await conn.run_sync(SQLModel.metadata.create_all)
            logger.info("Database tables checked/created successfully.")
        except Exception as e:
            logger.error(f"Error creating database tables: {e}", exc_info=True)
            raise

async def close_db_connection():
    logger.info("Closing database connection pool...")
    await async_engine.dispose()
    logger.info("Database connection pool closed.")

# Example of how to initialize DB (e.g., in main.py on startup)
# async def init_db():
# await create_db_and_tables() 