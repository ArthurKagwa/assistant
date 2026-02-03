FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create entrypoint script
RUN chmod +x /app/docker-entrypoint.sh || true

# Expose port
EXPOSE 8000

# Default command (will be overridden in docker-compose)
CMD ["gunicorn", "kabanda.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
