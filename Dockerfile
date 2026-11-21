# ==============================================================================
# KeloStats - Root Dockerfile (Optimized for Railway & Cloud Deployments)
# ==============================================================================

FROM python:3.12-slim

# Prevent Python from writing .pyc files & enable unbuffered standard I/O
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

# Install essential system dependencies (curl for healthchecks, build tools for C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements first to leverage Docker layer caching
COPY backend/requirements.txt /app/backend/requirements.txt

# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy clean backend code
COPY backend/ /app/backend/

# Switch working directory to backend root where main.py resides
WORKDIR /app/backend

# Expose default port
EXPOSE 8000

# Container healthcheck testing /health endpoint using dynamic $PORT
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Launch FastAPI ASGI server (dynamically binds to Railway's $PORT or defaults to 8000)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
