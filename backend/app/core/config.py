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
    VECTOR_DB_URL: str = "http://localhost:8011"
    VECTOR_DB_PROVIDER: str = "chromadb"
    VECTOR_DB_COLLECTION_PREFIX: str = "restaurant_"

    # ========================================================================
    # LANGUAGE MODEL (LLM)
    # ========================================================================
    # "ollama" (fully local, needs a GPU for acceptable phone-call
    # latency — see docs/roadmap.md) or "groq" (hosted; free tier
    # available, and fast enough on CPU hardware that a caller doesn't
    # hear long dead-air gaps between turns). This is the dial a
    # deployment turns to offer a client either a fully local/private
    # stack or a hosted one — the conversation engine only depends on
    # the LLMProvider interface, never a specific provider.
    LLM_PROVIDER: str = "ollama"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"
    OLLAMA_REQUEST_TIMEOUT: int = 60

    # Groq's OpenAI-compatible chat completions API. Free tier as of
    # this writing. openai/gpt-oss-120b is a much stronger
    # instruction-follower than a local 3B model can be on CPU (this
    # project's own prompts needed few-shot examples to work around
    # exactly that gap — see app/prompts/), and Groq's inference is
    # fast enough that it doesn't reintroduce the CPU-latency problem
    # local Ollama had. openai/gpt-oss-20b is a faster/cheaper
    # alternative if 120b's latency or free-tier limits become an
    # issue. (Not llama-3.3-70b-versatile/llama-3.1-8b-instant — Groq
    # decommissioned both; hit live as a 404 from every chat completion
    # call. Verify current model IDs at
    # https://console.groq.com/docs/deprecations before relying on any
    # specific one long-term — Groq's lineup changes.)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_REQUEST_TIMEOUT: int = 30

    # Model for the two classification calls each turn (is this caller
    # upset? what do they want?). Both answer with a single word from a
    # fixed list, which is not work that needs the large model — and
    # they sit directly in the caller's silence, two of the three LLM
    # round trips in a turn. The smaller model is meaningfully faster at
    # them. Set this to the same value as GROQ_MODEL if classification
    # accuracy ever looks worse than the latency is worth.
    #
    # Only the phrasing of actual answers still goes to GROQ_MODEL,
    # where quality is what the caller hears.
    GROQ_CLASSIFIER_MODEL: str = "openai/gpt-oss-20b"

    # Separate embedding model — embedding models are purpose-built and
    # much smaller than chat models; using OLLAMA_MODEL for both would
    # waste VRAM and give worse embeddings than a dedicated model.
    # Always served by Ollama regardless of LLM_PROVIDER — Groq's API
    # doesn't serve embeddings, and RAG/knowledge-base search never
    # needed the speed fix LLM_PROVIDER=groq exists for.
    EMBEDDING_MODEL: str = "nomic-embed-text"

    # ========================================================================
    # SPEECH-TO-TEXT
    # ========================================================================
    WHISPER_MODEL: str = "large-v3"
    WHISPER_DEVICE: str = "cuda"
    # Empty means "pick by device": float16 on CUDA, int8 on CPU.
    # int8 is what makes a bigger model usable on a CPU-only machine —
    # roughly 3-4x faster than float32 for a negligible accuracy cost,
    # so "small with int8" beats "base with float32" on both counts.
    # Don't run `base` on a phone line if you can avoid it: 8kHz
    # telephone audio is already the hardest case for Whisper, and on
    # real calls `base` produced "hollow options" for "halal options"
    # and "chicken show, Emma" for "chicken shawarma".
    WHISPER_COMPUTE_TYPE: str = ""

    # Beam width for decoding. faster-whisper defaults to 5; 1 is greedy.
    #
    # Measured on real calls, transcription cost barely moves with how
    # long the caller spoke (0.78s of audio took 2.95s, 5.88s took 3.5s)
    # — the encoder runs over a fixed 30-second window either way, so the
    # only parts that scale are the model and the decode. Greedy decoding
    # gives back a large slice of the decode for a small accuracy cost on
    # the short, plain utterances a phone line actually gets. Raise it
    # back toward 5 if transcripts get noticeably worse.
    WHISPER_BEAM_SIZE: int = 1

    # CPU threads for inference. 0 lets CTranslate2 choose, which is
    # usually the physical core count — set it explicitly if that guess
    # is wrong for this machine.
    WHISPER_CPU_THREADS: int = 0

    # Vocabulary hint passed to Whisper as its decoder prefix. Whisper
    # biases toward spellings it has just "seen", so listing the words a
    # caller to THIS restaurant is likely to say — dish names, the
    # restaurant's own name — measurably improves them, at no runtime
    # cost. This is the single highest-value setting for a menu full of
    # words that aren't in everyday English, and it helps most for the
    # accented speech those words usually arrive in.
    #
    # Keep it to a plausible sentence or a comma-separated list of terms;
    # Whisper treats it as preceding context, not as a command. Override
    # per deployment in .env with the restaurant's own menu vocabulary.
    # Deliberately a bare term list, NOT a fluent sentence. An earlier
    # version opened "Thanks for calling. We serve halal Syrian and
    # Mediterranean food: ..." and Whisper echoed that sentence back as
    # a transcript of what the *caller* had just said — the model
    # continues the prompt it was given, and a fluent sentence is
    # something it can plausibly continue. A comma-separated list of
    # nouns still biases the vocabulary without offering a sentence to
    # complete. Anything it does echo is caught by
    # app/voice/session.py's echo guard.
    STT_INITIAL_PROMPT: str = (
        "shawarma, beef shawarma, chicken shawarma, kebab, kabob, tikka, mixed grill, "
        "kibbeh, falafel, hummus, tahina, tabouli, fattoush, baba ghanoush, foul, "
        "manakeesh, zaatar, shish tawook, mansaf, baklava, halal, vegan, vegetarian, "
        "gluten free, takeout, delivery, catering, reservation, parking"
    )

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
    # Speaking rate. Synthesis time scales with how much audio is
    # produced, so this shortens both the wait AND the playback — a
    # measured 10-second synthesis for one long answer comes down
    # noticeably at 1.15. Past ~1.25 it starts to sound hurried, which
    # costs more in warmth than it saves in seconds.
    KOKORO_SPEED: float = 1.15
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
    # Was 0.6, which was a guess made before any real embeddings existed
    # to measure against. Calibrated against actual cosine similarities
    # from live calls (nomic-embed-text, real seeded restaurant
    # documents, real Whisper transcripts of real callers):
    #
    #   "...a lot of items in our menu?"    -> menu/dietary doc  0.627
    #   "Can you tell me ... our location?" -> location doc      0.485
    #   (same queries against the *other*, unrelated documents:
    #    0.472, 0.481, 0.432, 0.362)
    #
    # The right document ranked first every time, but a genuine,
    # unambiguous match only reached 0.485 — so 0.6 rejected correct
    # answers ("where are you located?" against a document literally
    # titled "Location & Parking" returned nothing). Short conversational
    # queries against short reference documents just don't score high in
    # absolute terms with this embedding model; what matters is the gap
    # between a real match and an unrelated one, which sits right around
    # 0.45 here. Raise this if callers start getting answers grounded in
    # loosely-related documents; lower it if real questions go unanswered.
    RAG_RELEVANCE_THRESHOLD: float = 0.45

    # The best chunk must clear this for the knowledge base to count as
    # having covered the question at all.
    #
    # RAG_RELEVANCE_THRESHOLD alone is a floor, and with a knowledge base
    # of any size *something* always clears a floor. Measured on real
    # calls, a question the documents genuinely don't cover comes back as
    # a flat cluster just above it — "what about holidays, Christmas, New
    # Year's?" returned five chunks at 0.52, 0.50, 0.50, 0.49 and 0.49
    # (mixed grill, halal, appetizers, parking, shawarma), and the model
    # was handed all five and asked to answer about holiday hours.
    #
    # A question the documents DO cover looks completely different: one
    # clear winner well above the rest ("how many cars fit in your
    # parking lot?" -> 0.63 against a tail at 0.46). So a top score that
    # never rises above the tail is the signal that nothing here actually
    # answers the question, and saying so is the honest reply.
    RAG_CONFIDENT_THRESHOLD: float = 0.55

    # Chunks more than this far below the best one are dropped even when
    # they clear the floor. They're what the tail of that flat cluster is
    # made of: real, on-topic documents about something else entirely,
    # which do nothing but give the model room to answer from the wrong
    # one.
    RAG_RELATIVE_MARGIN: float = 0.10
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
    # True: the AI collects reservation details itself (name, phone,
    # date, time, party size) and creates a real pending Reservation
    # row — for a restaurant whose staff actually checks and confirms
    # those. False: a reservation request instead just offers a human
    # handoff (see app/conversation/engine.py's _handle_identify_intent)
    # — the honest choice for a restaurant with no reservation system of
    # its own to write a collected reservation into (paper-only booking,
    # say), where an AI-created Reservation row would just be a database
    # entry nobody ever looks at.
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
    def SPEAK_PROCESSING_FILLER(self) -> bool:
        """
        Whether CallSession should speak a brief "one moment" filler
        right after transcribing the caller (see app/voice/session.py)
        before running the conversation engine.

        Only worth it for local Ollama on CPU, where a turn can take
        10-30+ seconds — without it, that's total silence, which reads
        as a dropped call. A hosted provider like Groq responds fast
        enough that the filler would just be an odd, robotic-sounding
        extra beat before an otherwise-fast reply — real human
        conversation doesn't insert "let me check that" before every
        single answer, so a fast provider skips it.
        """
        return self.LLM_PROVIDER == "ollama"

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
