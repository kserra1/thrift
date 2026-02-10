# ============================================
# STAGE 1: Builder
# Purpose: Install Python dependencies
# ============================================
FROM python:3.9-slim as builder

# Set working directory inside the container
WORKDIR /app

# Install system dependencies needed to compile gevent and psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*


# Copy requirements first to leverage Docker cache
COPY workers/requirements.txt .

# Upgrade pip and install all Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================
# STAGE 2: Runtime
# Purpose: Minimal production image
# ============================================
FROM python:3.9-slim

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN useradd -m -u 1000 appuser

# Set working directory
WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy your application code
COPY workers/ /app/workers/
COPY scripts/ /app/scripts/

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Healthcheck for Docker/K8s
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command to run the FastAPI app
CMD ["sh", "-c", "uvicorn workers.app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
