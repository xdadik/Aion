# Aion Hand — multi-stage Dockerfile
# Build:  docker build -t aion-hand .
# Run:    docker run -p 8000:8000 -p 3000:3000 -v ~/.aion-hand:/root/.aion-hand aion-hand

# ─── Stage 1: Python base ─────────────────────────────────────────────────
FROM python:3.12-slim AS python-base

# Avoid writing pyc files and buffer output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system deps needed by espeak (TTS), git (skill install), curl
RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng \
        git \
        curl \
        ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt || true && \
    pip install -r requirements-dev.txt || true && \
    pip install aiohttp pyyaml rich prompt_toolkit

# Copy the rest of the code
COPY . .

# Install Aion itself
RUN pip install -e ".[all]"

# ─── Stage 2: Node for web UI ─────────────────────────────────────────────
FROM node:20-slim AS web-builder
WORKDIR /app/aion_web
COPY aion_web/package.json aion_web/package-lock.json* ./
RUN npm ci || npm install
COPY aion_web/ ./
RUN npm run build

# ─── Stage 3: Final runtime image ─────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AION_HAND_HOME=/root/.aion-hand

# Install only runtime deps (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed Python packages from stage 1
COPY --from=python-base /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-base /usr/local/bin /usr/local/bin

# Copy app code
COPY --from=python-base /app /app

# Copy built web UI
COPY --from=web-builder /app/aion_web/.next /app/aion_web/.next
COPY --from=web-builder /app/aion_web/public /app/aion_web/public
COPY --from=web-builder /app/aion_web/package.json /app/aion_web/package.json
COPY --from=web-builder /app/aion_web/node_modules /app/aion_web/node_modules

# Create Aion home directory
RUN mkdir -p $AION_HAND_HOME

# Default command: start the Aion agent in TUI mode
# (Override with `docker run ... aion-hand chat` or `aion-tui` etc.)
EXPOSE 8000 3000

# Health check: ping the health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

CMD ["aion-hand", "chat"]
