import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    return value if value is not None else default


@lru_cache
def settings():
    return {
        "database_url": _get_env(
            "DATABASE_URL",
            "postgresql://postgres:postgres@127.0.0.1:5432/laravel_api_ai",
        ),
        "jwt_secret": _get_env("JWT_SECRET", "laravel-ai-fastapi-secret"),
        "app_port": int(_get_env("APP_PORT", "8000")),
    }
