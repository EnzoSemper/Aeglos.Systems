FROM python:3.12-slim

LABEL maintainer="AEGLOS Analytics Pro"
LABEL description="Multi-Domain HUMINT/OSINT/GEOINT Intelligence Fusion Platform"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY *.py .
COPY static/ ./static/

ENV API_HOST=0.0.0.0
ENV API_PORT=8000
ENV WORKERS=4

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--log-level", "info"]
