"""
Application Configuration

Manages all configuration from environment variables and .env file.
Uses Pydantic Settings for validation and type safety.
"""

from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings from environment variables.

    Load order:
    1. .env file in the project root
    2. Environment variables
    3. Default values
    """

    # ========================================================================
    # APPLICATION
    # ========================================================================
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ========================================================================
    # SECURITY
    # ========================================================================
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ========================================================================
    # DATABASE
    # ========================================================================
    # Must use the asyncpg driver scheme — SQLAlchemy's create_async_engine
    # requires an async-capable DBAPI, and plain "postgresql://" resolves to
    # the sync psycopg2 driver, which raises at engine-creation time.
    DATABASE_URL: str = "postgresql+asyncpg://restaurantai:restaurantai@localhost:5432/restaurantai"
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # ========================================================================
    # CACHE
    # ========================================================================
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_DEFAULT_TTL: int = 3600

    # ========================================================================
    # VECTOR DATABASE
    # ========================================================================
    VECTOR_DB_URL: str = "http://localhost:8001"
    VECTOR_DB_PROVIDER: str = "chromadb"
    VECTOR_DB_COLLECTION_PREFIX: str = "restaurant_"

    # ========================================================================
    # LANGUAGE MODEL (LLM)
    # ========================================================================
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"
    OLLAMA_REQUEST_TIMEOUT: int = 60

    # Separate embedding model — embedding models are purpose-built and
    # much smaller than chat models; using OLLAMA_MODEL for both would
    # waste VRAM and give worse embeddings than a dedicated model.
    EMBEDDING_MODEL: str = "nomic-embed-text"

    # ========================================================================
    # SPEECH-TO-TEXT
    # ========================================================================
    WHISPER_MODEL: str = "large-v3"
    WHISPER_DEVICE: str = "cuda"

    # ========================================================================
    # TEXT-TO-SPEECH
    # ========================================================================
    TTS_PROVIDER: str = "kokoro"
    KOKORO_DEVICE: str = "cuda"
    # Kokoro's own single-letter language codes (not ISO 639-1) — 'a' is
    # American English, 'b' British English, 'j' Japanese, 'z' Chinese,
    # etc. per hexgrad/Kokoro-82M's KPipeline. "en" is not a valid value.
    KOKORO_LANG_CODE: str = "a"
    # A specific named voice, not just a language — Kokoro has no
    # "default voice per language," every synthesis call must name one.
    # af_heart is Kokoro's commonly-documented American English voice.
    KOKORO_VOICE: str = "af_heart"
    PIPER_VOICE_MODEL_PATH: str = "/models/piper/en_US-lessac-medium.onnx"

    # ========================================================================
    # TWILIO
    # ========================================================================
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WEBHOOK_SECRET: str = ""
    TWILIO_DEFAULT_TRANSFER_TIMEOUT: int = 30
    # Declared (not just documented in .env.example) because pydantic-settings
    # rejects any .env key with no matching field by default — a real .env
    # copied from .env.example (which has always documented this setting)
    # would otherwise crash the app at startup with a ValidationError before
    # a single request could be served. Not read anywhere yet: SMS is
    # currently always sent via TelephonyProvider/Twilio (see
    # app/services/notification_service.py) — this exists for when a second
    # SMS-capable provider is ever added.
    SMS_PROVIDER: str = "twilio"

    # ========================================================================
    # SMTP / EMAIL
    # ========================================================================
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@restaurant.local"
    SMTP_FROM_NAME: str = "AI Receptionist"

    # ========================================================================
    # NOTIFICATIONS (Phase 6 worker — app/worker.py)
    # ========================================================================
    # How often the standalone notification worker polls for due,
    # unsent Notification rows.
    NOTIFICATION_POLL_INTERVAL_SECONDS: int = 15
    # A notification stops being retried once it has failed this many
    # times — left unsent with error_message set, for a human to notice,
    # rather than retried forever.
    NOTIFICATION_MAX_ATTEMPTS: int = 5
    # Backoff between retries is base * 2^(attempt_count-1), capped at
    # NOTIFICATION_BACKOFF_MAX_SECONDS.
    NOTIFICATION_BACKOFF_BASE_SECONDS: int = 60
    NOTIFICATION_BACKOFF_MAX_SECONDS: int = 3600

    # ========================================================================
    # PUBLIC URL
    # ========================================================================
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    PUBLIC_DOMAIN: str = "localhost"
    WEBHOOK_BASE_PATH: str = "/webhooks"

    # ========================================================================
    # API
    # ========================================================================
    API_V1_PREFIX: str = "/api"
    API_TITLE: str = "AI Restaurant Receptionist"
    API_DESCRIPTION: str = "Voice AI for restaurant phone management"
    API_VERSION: str = "0.1.0"

    # ========================================================================
    # CORS
    # ========================================================================
    CORS_ORIGINS: List[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["*"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]

    # ========================================================================
    # RATE LIMITING
    # ========================================================================
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_CALLS_PER_MINUTE: int = 100
    RATE_LIMIT_WEBHOOK_PER_HOUR: int = 10000

    # ========================================================================
    # AI CONVERSATION
    # ========================================================================
    MAX_CONTEXT_TOKENS: int = 2048
    CONVERSATION_TEMPERATURE: float = 0.7
    SYSTEM_PROMPT_FILE: str = "receptionist_system.txt"

    # ========================================================================
    # RAG
    # ========================================================================
    RAG_CHUNK_SIZE: int = 500
    RAG_CHUNK_OVERLAP: int = 50
    RAG_RETRIEVAL_TOP_K: int = 5
    RAG_RELEVANCE_THRESHOLD: float = 0.6
    # Knowledge documents are restaurant reference text (menus, policies,
    # FAQs) — 2MB is generous headroom over that while still bounding
    # worst-case chunking/embedding work per upload.
    MAX_KNOWLEDGE_UPLOAD_BYTES: int = 2_000_000

    # ========================================================================
    # CALL RECORDING
    # ========================================================================
    CALL_RECORDING_ENABLED: bool = True
    CALL_RECORDING_PROVIDER: str = "local"
    LOCAL_STORAGE_PATH: str = "/data/recordings"

    # Retention policies (days)
    TRANSCRIPT_RETENTION_DAYS: int = 90
    RECORDING_RETENTION_DAYS: int = 30
    AUDIT_LOG_RETENTION_DAYS: int = 365

    # ========================================================================
    # MONITORING
    # ========================================================================
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090
    STRUCTURED_LOGGING: bool = True

    # ========================================================================
    # FEATURE FLAGS
    # ========================================================================
    FEATURE_CALL_RECORDING: bool = True
    FEATURE_CALL_TRANSFER: bool = True
    FEATURE_RESERVATION_COLLECTION: bool = True
    FEATURE_SMS_NOTIFICATIONS: bool = True
    FEATURE_EMAIL_NOTIFICATIONS: bool = True
    FEATURE_RAG: bool = True
    FEATURE_AI_CLASSIFICATION: bool = True

    # ========================================================================
    # TESTING
    # ========================================================================
    MOCK_TWILIO: bool = False
    DATABASE_RESET_ON_STARTUP: bool = False
    DATABASE_SEED_TEST_DATA: bool = False

    # ========================================================================
    # COMPUTED PROPERTIES
    # ========================================================================

    @property
    def IS_PRODUCTION(self) -> bool:
        """Check if running in production."""
        return self.ENVIRONMENT.lower() == "production"

    @property
    def IS_DEVELOPMENT(self) -> bool:
        """Check if running in development."""
        return self.ENVIRONMENT.lower() == "development"

    @property
    def ALLOWED_HOSTS(self) -> List[str]:
        """Get allowed hosts for TrustedHost middleware.

        "testserver" is Starlette TestClient's fixed Host header — added
        outside production only, so the test suite can exercise the real
        middleware stack without weakening the production allow-list.
        """
        hosts = [self.PUBLIC_DOMAIN, "localhost", "127.0.0.1"]
        if not self.IS_PRODUCTION:
            hosts.append("testserver")
        return hosts

    @property
    def WEBHOOK_URL_VOICE(self) -> str:
        """Get the full Twilio voice webhook URL."""
        return f"{self.PUBLIC_BASE_URL}{self.WEBHOOK_BASE_PATH}/twilio/voice"

    @property
    def WEBHOOK_URL_STATUS(self) -> str:
        """Get the full Twilio status webhook URL."""
        return f"{self.PUBLIC_BASE_URL}{self.WEBHOOK_BASE_PATH}/twilio/status"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


# Global settings instance
settings = Settings()
