FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install app package with Redis support
RUN pip install "nadb[redis]" gunicorn

# Copy application code
COPY . .

# Create a directory for data
RUN mkdir -p ./nadb_data && chmod 777 ./nadb_data

# Expose port
EXPOSE 5001

# Set production environment
ENV FLASK_ENV=production

# Run with Gunicorn for production
# Workers: 2*CPU+1 is a good starting point for CPU-bound apps
# Threads: 2-4 per worker for IO-bound apps
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "3", "--threads", "3", "--timeout", "120", "todo_app_redis:app"] 