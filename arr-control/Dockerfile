"""Dockerfile for arr-control."""
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy requirements first for better caching
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir .[dev]

# Copy source code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create config directory
RUN mkdir -p /config

EXPOSE 8000

CMD ["uvicorn", "backend.main:application", "--host", "0.0.0.0", "--port", "8000"]