FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# espeak-ng: phonemization fallback for both Kokoro (misaki's
# EspeakFallback) and Piper TTS — without it, either provider fails on
# words its primary G2P doesn't recognize.
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    ffmpeg \
    libsndfile1 \
    portaudio19-dev \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
# --proxy-headers/--forwarded-allow-ips: see docker-compose.yml's api
# service for why this is required behind Nginx (Twilio webhook
# signature validation needs request.url to report the real https://
# scheme Nginx terminated, not uvicorn's own plain-http connection to it).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
