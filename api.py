import logging
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()


def setup_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


logger = logging.getLogger(__name__)


def apply_env() -> None:
    try:
        required_vars = ["SEED_PHRASE", "FRAGMENT_COOKIES"]
        missing_vars = []

        for var in required_vars:
            value = os.getenv(var)
            if not value:
                missing_vars.append(var)
            else:
                value = value.strip("\"'")
                os.environ[var] = value

        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

        logger.info("Environment variables loaded successfully")
        ton_server = os.getenv("TON_LITE_SERVER", "mainnet_config").strip("\"'")
        logger.info(f"TON_LITE_SERVER: {ton_server}")

    except Exception as e:
        logger.error(f"Failed to apply environment variables: {e}")
        raise


def main() -> None:
    try:
        setup_logging()
        apply_env()
        logger.info("Starting Fragment Buyer API server...")

        host = os.getenv("HOST", "127.0.0.1")
        port = int(os.getenv("PORT", "8000"))

        logger.info("Server will start on %s:%s" % (host, port))

        uvicorn.run("app.main:app", host=host, port=port)
    except Exception as e:
        logger.error("Failed to start server: %s" % e)
        raise e


if __name__ == "__main__":
    main()
