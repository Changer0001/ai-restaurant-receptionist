"""
Application Configuration

Manages all configuration from environment variables and .env file.
Uses Pydantic Settings for validation and type safety.
"""

from typing import List

from pydantic_settings import BaseSettings


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
    DATABASE_URL: str = "postgresql://restaurantai:restaurantai@localhost:5432/restaurantai"
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
    KOKORO_LANGUAGE: str = "en"

    # ========================================================================
    # TWILIO
    # ========================================================================
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WEBHOOK_SECRET: str = ""
    TWILIO_DEFAULT_TRANSFER_TIMEOUT: int = 30

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
        """Get allowed hosts for TrustedHost middleware."""
        return [self.PUBLIC_DOMAIN, "localhost", "127.0.0.1"]

    @property
    def WEBHOOK_URL_VOICE(self) -> str:
        """Get the full Twilio voice webhook URL."""
        return f"{self.PUBLIC_BASE_URL}{self.WEBHOOK_BASE_PATH}/twilio/voice"

    @property
    def WEBHOOK_URL_STATUS(self) -> str:
        """Get the full Twilio status webhook URL."""
        return f"{self.PUBLIC_BASE_URL}{self.WEBHOOK_BASE_PATH}/twilio/status"

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global settings instance
settings = Settings()
