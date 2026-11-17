"""Entry point for uvicorn:

    uvicorn src.api.main:app --host 127.0.0.1 --port 8100
"""

from dotenv import load_dotenv

from src.logging_config import setup_logging

load_dotenv()
setup_logging()

from src.api.app import create_app  # noqa: E402

app = create_app()
