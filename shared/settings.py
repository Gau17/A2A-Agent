from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "A2A Procurement MVP"
    LOG_LEVEL: str = "DEBUG"
    DB_ECHO_LOG: bool = False
    
    # Buyer Concierge Service Address (for tests or other clients on host)
    BUYER_CONCIERGE_HOST_URL: str = "http://localhost:8081"

    # Supplier Quoter Service Address (for A2AClient in Buyer Concierge)
    SUPPLIER_QUOTER_A2A_URL: str = "http://supplier_quoter:8080/a2a"

    # Token for server-to-server A2A calls if not using IAP pass-through
    # For testing, this uses the bypass token.
    A2A_INTERNAL_TOKEN: Optional[str] = "test-bypass-token"

    # For testing: the actual token string that allows bypassing token verification.
    TEST_AUTH_BYPASS_TOKEN: Optional[str] = "test-bypass-token"

    # Database settings (example, adjust as needed)
    DB_USER: str = "user"
    DB_PASSWORD: str = "password"
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_NAME: str = "a2a_procurement_db"

    # For pgvector, a DSN might be easier
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # OAuth settings (placeholders)
    OAUTH_TOKEN_URL: str = "https://example.com/oauth/token"
    OAUTH_CLIENT_ID: str = "your-client-id"
    OAUTH_CLIENT_SECRET: str = "your-client-secret"
    OAUTH_SERVICE_ACCOUNT_PUBLIC_CERT_URL: str = "https://www.googleapis.com/oauth2/v3/certs" # Example for GCP SA

    # A2A Client settings
    SUPPLIER_QUOTER_URL: str = "http://supplier_quoter:8080/a2a" # Internal Docker network URL
    SUPPLIER_AUTH_TOKEN: Optional[str] = None # This was the source of a previous bug, ensure it's not mistakenly used for outgoing token

    # Optional settings for testing/development
    TEST_AUTH_BYPASS: str = "false" # This setting's purpose should be clarified or removed if TEST_AUTH_BYPASS_TOKEN is the sole bypass mechanism

    model_config = SettingsConfigDict(env_file=".env", extra='ignore', env_file_encoding='utf-8')

settings = Settings() 