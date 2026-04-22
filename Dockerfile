FROM python:3.11-slim

WORKDIR /app

# Cài system deps
RUN apt-get update && apt-get install -y \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject trước để cache layer
COPY pyproject.toml .

# Cài dependencies
RUN pip install --no-cache-dir -e .

# Copy source
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Data dirs
RUN mkdir -p /data/backups /secrets

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
