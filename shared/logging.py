import logging
import sys
from shared.settings import settings

# Configure logging
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout) # Log to stdout, suitable for containers
    ]
)

def get_logger(name: str) -> logging.Logger:
    """Returns a configured logger instance."""
    return logging.getLogger(name)

# Example usage:
# logger = get_logger(__name__)
# logger.info("This is an info message.")
# logger.error("This is an error message.") 