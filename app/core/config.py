from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AnyUrl, BeforeValidator, HttpUrl, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(raw_value: Any) -> list[str] | str:
    """
    Parse CORS origins from .env

    Example:
        "http://localhost:3000,http://localhost:5173"
        -> ["http://localhost:3000", "http://localhost:5173"]
    """
    if isinstance(raw_value, str) and not raw_value.startswith("["):
        return [i.strip() for i in raw_value.split(",") if i.strip()]
    elif isinstance(raw_value, list | str):
        return raw_value
    raise ValueError(f"Invalid CORS origins format: {raw_value}")


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_ignore_empty=True, extra="ignore"
    )
    API_PREFIX: str = "/api"
    PROJECT_NAME: str
    ENVIRONMENT: Literal["dev", "prod"] = "prod"

    # Sentry
    SENTRY_DSN: HttpUrl | None = None

    # CORS
    FRONTEND_HOST: str = "http://localhost:3000"
    BACKEND_CORS_ORIGINS: Annotated[list[AnyUrl], BeforeValidator(parse_cors)] = []

    @computed_field
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST.rstrip("/")
        ]


settings = Settings()  # type: ignore
