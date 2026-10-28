from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = ""
    test_database_url: str = ""
    jwt_secret: str = Field(default="", repr=False)
    n8n_shared_secret: str = Field(default="", repr=False)
    demo_password: str = Field(default="", repr=False)
    cors_origins: str = "http://localhost:5173"
    jwt_ttl_minutes: int = 60
    use_presidio: bool = True
    bcrypt_rounds: int = 12
    n8n_editor_url: str = "http://localhost:5678"

    # Risk thresholds (documented in docs/POLICIES.md)
    risk_window_minutes: int = 10
    risk_denied_field_threshold: int = 3
    risk_distinct_subsets_threshold: int = 4
    risk_volume_threshold: int = 30
    risk_elevated_score: int = 2
    risk_block_score: int = 4

    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        # Accept a plain Neon URL and select the psycopg3 driver.
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+psycopg://", 1)
        return v

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def config_problems(self) -> list[str]:
        problems = []
        if not self.database_url:
            problems.append("DATABASE_URL is not set")
        if len(self.jwt_secret) < 16:
            problems.append("JWT_SECRET is missing or too short (min 16 chars)")
        if len(self.n8n_shared_secret) < 16:
            problems.append("N8N_SHARED_SECRET is missing or too short (min 16 chars)")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
