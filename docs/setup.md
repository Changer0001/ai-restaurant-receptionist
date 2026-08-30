# Setup Guide

## Prerequisites

- **Docker & Docker Compose** (latest version)
- **NVIDIA GPU** (RTX 3090 or 4090 recommended)
- **NVIDIA Container Toolkit** (for GPU access in containers)
- **Git**
- **Twilio Account** (free tier acceptable for testing)

## System Requirements

### Minimum (5 concurrent calls)

- GPU: NVIDIA RTX 3090 (24GB VRAM)
- CPU: 8 cores
- RAM: 64GB
- Storage: 500GB SSD
- Network: Stable internet connection

### Recommended (10+ concurrent calls)

- GPU: NVIDIA RTX 4090 (24GB VRAM)
- CPU: 16 cores
- RAM: 128GB
- Storage: 1TB NVMe SSD
- Network: 100Mbps upload/download

## Quick Start (Local Development)

### 1. Clone Repository

```bash
git clone https://github.com/changer0001/ai-restaurant-receptionist.git
cd ai-restaurant-receptionist
```

### 2. Verify NVIDIA Setup

```bash
# Check NVIDIA driver
nvidia-smi

# Should output GPU info
# Example output:
# NVIDIA-SMI 535.0
# CUDA Version: 12.2
```

### 3. Install NVIDIA Container Toolkit

```bash
# Ubuntu/Debian
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### 4. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit with your settings
nano .env

# Required settings:
# - TWILIO_ACCOUNT_SID
# - TWILIO_AUTH_TOKEN
# - PUBLIC_BASE_URL (your public IP or domain)
# - JWT_SECRET (generate: openssl rand -hex 32)
```

### 5. Start Services

```bash
# Start all containers
docker compose up -d

# Watch startup progress
docker compose logs -f

# Wait for services to be ready (~2-5 minutes for model downloads)
# Look for:
# - "api | Application startup complete"
# - "ollama | Ready"
```

### 6. Verify Services

```bash
# Check all services
docker compose ps

# Test API
curl http://localhost:8000/health

# Expected response:
# {"status":"ok"}
```

### 7. Access Services

| Service | URL | Default Login |
|---------|-----|---|
| API Docs | http://localhost/docs | N/A |
| Frontend | http://localhost | N/A |
| Prometheus | http://localhost/prometheus | N/A |
| Grafana | http://localhost/grafana | admin/admin |

## Create First Restaurant

### Via API (Recommended for MVP)

```bash
# Generate JWT token first
# (This will be implemented in Phase 2)
# For now, create via database directly

# Access postgres
docker compose exec postgres psql -U restaurantai -d restaurantai

# Then run SQL:
INSERT INTO restaurants (
  id, name, address, city, timezone, 
  transfer_number, is_active
) VALUES (
  'f47ac10b-58cc-4372-a567-0e02b2c3d479',
  'Example Italian Restaurant',
  '123 Main St',
  'New York',
  'America/New_York',
  '+12125551234',
  true
);

INSERT INTO restaurant_phone_numbers (
  id, restaurant_id, phone_number, is_active
) VALUES (
  'a47ac10b-58cc-4372-a567-0e02b2c3d480',
  'f47ac10b-58cc-4372-a567-0e02b2c3d479',
  '+12125559876',  -- Your Twilio number
  true
);

INSERT INTO restaurant_hours (
  id, restaurant_id, day_of_week, 
  opening_time, closing_time, is_closed
) VALUES
  ('b47ac10b-58cc-4372-a567-0e02b2c3d481', 'f47ac10b-58cc-4372-a567-0e02b2c3d479', 0, '11:00', '22:00', false),
  ('b47ac10b-58cc-4372-a567-0e02b2c3d482', 'f47ac10b-58cc-4372-a567-0e02b2c3d479', 1, '11:00', '22:00', false),
  ('b47ac10b-58cc-4372-a567-0e02b2c3d483', 'f47ac10b-58cc-4372-a567-0e02b2c3d479', 2, '11:00', '22:00', false),
  ('b47ac10b-58cc-4372-a567-0e02b2c3d484', 'f47ac10b-58cc-4372-a567-0e02b2c3d479', 3, '11:00', '22:00', false),
  ('b47ac10b-58cc-4372-a567-0e02b2c3d485', 'f47ac10b-58cc-4372-a567-0e02b2c3d479', 4, '11:00', '22:00', false),
  ('b47ac10b-58cc-4372-a567-0e02b2c3d486', 'f47ac10b-58cc-4372-a567-0e02b2c3d479', 5, '12:00', '23:00', false),
  ('b47ac10b-58cc-4372-a567-0e02b2c3d487', 'f47ac10b-58cc-4372-a567-0e02b2c3d479', 6, '12:00', '23:00', false);

INSERT INTO restaurant_faqs (
  id, restaurant_id, question, answer, category, is_active
) VALUES
  ('c47ac10b-58cc-4372-a567-0e02b2c3d488', 'f47ac10b-58cc-4372-a567-0e02b2c3d479',
   'Do you have outdoor seating?', 'Yes, we have a patio with seating for 20 people.', 'seating', true),
  ('c47ac10b-58cc-4372-a567-0e02b2c3d489', 'f47ac10b-58cc-4372-a567-0e02b2c3d479',
   'What are your hours?', 'We are open Monday to Friday 11am to 10pm, and Saturday to Sunday 12pm to 11pm.', 'hours', true);
```

## Twilio Configuration

### 1. Purchase Phone Number

1. Go to Twilio Console
2. Phone Numbers → Buy a number
3. Select number (should be in restaurant's area code)
4. Verify

### 2. Configure Webhook

1. In Twilio Console, go to Phone Numbers → Manage Active Numbers
2. Select your number
3. Under "Voice & Fax" section:
   - **Webhook URL:** `https://your-domain.com/webhooks/twilio/voice`
   - **HTTP Method:** POST
   - **Fallback URL:** (leave empty for MVP)

4. Save

### 3. Test Incoming Call

```bash
# Call your Twilio number from any phone
# You should hear the AI receptionist greeting

# Check logs
docker compose logs -f api

# Should see: "Received call from +1234567890 to +1555-0000"
```

## Troubleshooting

### GPU Not Detected

```bash
# Check Docker GPU support
docker run --rm --gpus all nvidia/cuda:12.0-runtime nvidia-smi

# If fails, reinstall NVIDIA Container Toolkit
# See https://github.com/NVIDIA/nvidia-docker
```

### Ollama Model Not Downloading

```bash
# Check Ollama logs
docker compose logs ollama

# Manually pull model
docker compose exec ollama ollama pull qwen:latest

# List available models
docker compose exec ollama ollama list
```

### API Won't Start

```bash
# Check database connection
docker compose logs api

# If error is about database, wait longer for postgres to initialize
# Then manually run migrations
docker compose exec api alembic upgrade head
```

### Can't Connect to Frontend

```bash
# Check frontend is running
docker compose logs frontend

# Rebuild if needed
docker compose up -d --build frontend

# Check port 5173 is exposed
docker compose ps
```

## Development Commands

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api

# With timestamps
docker compose logs -f --timestamps
```

### Database Access

```bash
# Interactive psql
docker compose exec postgres psql -U restaurantai -d restaurantai

# Run query
docker compose exec postgres psql -U restaurantai -d restaurantai \
  -c "SELECT * FROM restaurants;"

# Dump database
docker compose exec postgres pg_dump -U restaurantai restaurantai > backup.sql
```

### Restart Services

```bash
# Single service
docker compose restart api

# All services
docker compose restart

# Full rebuild
docker compose down && docker compose up -d
```

### View Prometheus Metrics

```bash
# Raw metrics
curl http://localhost:9090/api/v1/query?query=calls_total

# Explore in Prometheus
# http://localhost/prometheus
```

### Check API Health

```bash
# Simple health check
curl http://localhost:8000/health

# Detailed readiness check
curl http://localhost:8000/ready
```

## First Call Test Script

After everything is running, test the system:

```bash
#!/bin/bash

# 1. Check API is running
echo "Testing API..."
curl -s http://localhost:8000/health | grep -q '"status":"ok"' && echo "✓ API OK" || echo "✗ API FAILED"

# 2. Check Database
echo "Testing Database..."
docker compose exec postgres psql -U restaurantai -d restaurantai -c "SELECT count(*) FROM restaurants;" && echo "✓ DB OK" || echo "✗ DB FAILED"

# 3. Check Ollama
echo "Testing Ollama..."
curl -s http://localhost:11434/api/tags | grep -q "qwen" && echo "✓ Ollama OK" || echo "✗ Ollama FAILED"

# 4. Check ChromaDB
echo "Testing ChromaDB..."
curl -s http://localhost:8001/api/version && echo "✓ ChromaDB OK" || echo "✗ ChromaDB FAILED"

# 5. Check Redis
echo "Testing Redis..."
docker compose exec redis redis-cli ping | grep -q "PONG" && echo "✓ Redis OK" || echo "✗ Redis FAILED"

echo ""
echo "All systems ready! Call your Twilio number to test."
```

## Production Deployment

See [deployment.md](deployment.md) for production setup with HTTPS, firewall, and hardening.

## Next Steps

1. **Phase 2** (Phase 2): Implement REST APIs for restaurant management
2. **Phase 3** (Phase 3): Implement RAG with ChromaDB
3. **Phase 4** (Phase 4): Integrate AI conversation system
4. **Phase 5** (Phase 5): Implement voice handling with Twilio
5. **Phase 6** (Phase 6): Implement reservation workflow

See [../README.md](../README.md) for full development roadmap.
