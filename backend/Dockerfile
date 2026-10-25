# Backend Dockerfile for OpenNotebookLM
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    espeak-ng \
    ffmpeg \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade \
        pip==26.2.1 \
        setuptools==84.0.0 \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && find /usr/local/lib/python3.11/site-packages/rapidocr/models \
        -type f -name '*.onnx' -delete

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/models /app/uploads /app/logs

# Create a non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Start the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
