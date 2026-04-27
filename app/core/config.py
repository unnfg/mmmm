import secrets
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
        env_file=BASE_DIR / ".env",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    # App
    environment: Literal["dev", "prod"] = "dev"
    project_name: str
    debug: bool = True
    api_prefix: str = "/api"
    secret_key: str = secrets.token_urlsafe(32)

    # CORS
    BACKEND_CORS_ORIGINS: Annotated[list[AnyUrl], BeforeValidator(parse_cors)] = []

    @computed_field
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS]

    # Database
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "comuser"
    postgres_password: str = "compassword"
    postgres_db: str = "comdb"

    first_superuser: str
    first_superuser_password: str

    @property
    def sqlalchemy_database_uri(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://redis:6379"

    # Gemini
    gemini_api_key: str = ""

    # Zalo
    zalo_app_id: str = ""
    zalo_app_secret: str = ""
    zalo_oa_token: str = ""

    # Sentry
    sentry_dns: HttpUrl | None = None


settings = Settings()  # type: ignore
