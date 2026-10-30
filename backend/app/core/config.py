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

    # Voice assistant LLM. Optional: the assistant reports "not configured" instead of failing the app.
    groq_api_key: str = Field(default="", repr=False)
    groq_model: str = "openai/gpt-oss-120b"  # verified to route tool calls; llama-3.3-70b-versatile returned 404 on the tested account
    groq_timeout_seconds: float = 20.0

    # Speech (Sarvam). Optional: voice controls stay disabled until the key is set.
    sarvam_api_key: str = Field(default="", repr=False)
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_speaker: str = "priya"  # female bulbul:v3 voice, matching the avatar
    sarvam_language: str = "en-IN"
    sarvam_timeout_seconds: float = 25.0

    # Live voice (LiveKit room + agent worker + Tavus avatar). All optional; each feature reports "not configured" until set.
    livekit_url: str = ""
    livekit_api_key: str = Field(default="", repr=False)
    livekit_api_secret: str = Field(default="", repr=False)
    tavus_api_key: str = Field(default="", repr=False)  # read by the agent worker; the backend only reports whether it is set
    tavus_face_id: str = ""
    tavus_pal_id: str = ""
    voice_agent_name: str = "trustlayer-voice"
    voice_agent_secret: str = Field(default="", repr=False)  # the agent worker presents this when it calls the backend

    # B1 data-protection engine (organizer's Saffron Bank dataset). Read-only access to the target databases.
    b1_pg_schema: str = "saffron_bank"  # schema inside DATABASE_URL's PostgreSQL that holds the Saffron tables
    b1_sqlite_path: str = "data/saffron_bank.db"  # the organizer's SQLite file (relative paths resolve from backend/); opened read-only
    b1_mysql_url: str = ""  # e.g. mysql://USER:PASSWORD@localhost:3306/saffron_bank ; empty = the MySQL backend reports "not configured"
    b1_sample_size: int = 200
    b1_max_rows: int = 100
    # Supplement database discovery with the ML model (docs/DB_DISCOVERY_ML.md). OFF by default: the original classifier alone decides, as before.
    # When on, the model can only add an UNCERTAIN PERSON/LOCATION suggestion to a column the original classifier left unclassified; it never confirms one.
    b1_ml_supplement: bool = False
    b1_ml_supplement_values: int = 40  # distinct text values per column the model reads (in memory only)

    # Hybrid PII detection (docs/DETECTION.md). ML is optional: with it unavailable the engine runs rules-only and says so in every result.
    detection_ml_enabled: bool = True
    detection_ml_model: str = "urchade/gliner_multi_pii-v1"  # Apache-2.0 GLiNER checkpoint fine-tuned for PII; downloaded once into the Hugging Face cache
    detection_ml_threshold: float = 0.5
    detection_ml_max_values: int = 200  # unique values per column sent to the model; beyond this ML counts are sample-based
    detection_ml_fallback: str = "rules_only"  # rules_only | fail
    upload_max_bytes: int = 5_000_000
    upload_max_rows: int = 50_000
    upload_max_columns: int = 200

    # On-demand n8n workflows. The backend calls a fixed webhook path per approved workflow; nothing the user or model supplies reaches the URL.
    n8n_webhook_base_url: str = ""  # e.g. http://127.0.0.1:5678/webhook
    n8n_trigger_secret: str = Field(default="", repr=False)
    n8n_trigger_timeout_seconds: float = 10.0

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

    @field_validator("b1_mysql_url")
    @classmethod
    def _mysql_driver(cls, v: str) -> str:
        v = v.strip()
        return v.replace("mysql://", "mysql+pymysql://", 1) if v.startswith("mysql://") else v

    @field_validator("livekit_url")
    @classmethod
    def _livekit_scheme(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith(("wss://", "ws://")):
            raise ValueError("LIVEKIT_URL must start with wss:// (or ws:// for a local server)")
        return v

    @field_validator("n8n_webhook_base_url")
    @classmethod
    def _n8n_scheme(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("N8N_WEBHOOK_BASE_URL must start with http:// or https://")
        return v

    @property
    def livekit_ready(self) -> bool:
        return bool(self.livekit_url and self.livekit_api_key and self.livekit_api_secret and len(self.voice_agent_secret) >= 16)

    @property
    def avatar_ready(self) -> bool:
        return bool(self.livekit_ready and self.tavus_api_key and self.tavus_face_id)

    @property
    def n8n_trigger_ready(self) -> bool:
        return bool(self.n8n_webhook_base_url and len(self.n8n_trigger_secret) >= 16)

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
