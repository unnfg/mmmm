import secrets
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AnyUrl, BeforeValidator, HttpUrl, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


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
    secret_key: str = secrets.token_urlsafe(32)  # fallback for dev env

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

    first_superuser: str | None = None
    first_superuser_password: str | None = None

    @property
    def sqlalchemy_database_uri(self) -> URL:
        """
        Construct the SQLAlchemy database URI using URL.create() instead of f-string
        to safely handle special characters in credentials (e.g. @, /, :).

        Bad (f-string): postgresql://user:p@ss/word:123@db:5432/mydb
                                          ^^ The parser mistakenly thinks this is the end of the password.

        Good (URL.create): postgresql://user:p%40ss%2Fword%3A123@db:5432/mydb
                                             ^^ percent-encoded, parse correct!
        """
        return URL.create(
            "postgresql",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @model_validator(mode="after")
    def validate_prod_secrets(self) -> Settings:
        """Fail-fast on production environment if missing secret key."""
        if self.environment == "prod":
            if self.secret_key == secrets.token_urlsafe(32):
                raise ValueError("SECRET_KEY can't empty in production environment")
        return self

    def require_superuser_credentials(self) -> tuple[str, str]:
        if not self.first_superuser or not self.first_superuser_password:
            raise RuntimeError(
                "FIRST_SUPERUSER and FIRST_SUPERUSER_PASSWORD is required when bootstrap"
            )
        return self.first_superuser, self.first_superuser_password

    # Redis
    redis_url: str = "redis://redis:6379"

    # Gemini
    gemini_api_key: str = ""

    # Zalo
    zalo_app_id: str = ""
    zalo_app_secret: str = ""
    zalo_oa_token: str = ""

    # Sentry
    sentry_dsn: HttpUrl | None = None


settings = Settings()  # type: ignore
