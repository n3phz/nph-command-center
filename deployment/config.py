"""Production deployment configuration for arr-control."""
from pydantic import BaseModel
from typing import List, Optional


class DockerConfig(BaseModel):
    """Deployment configuration for arr-control."""
    
    # Application
    name: str = "arr-control"
    version: str = "0.1.0"
    description: str = "Media Automation Control Plane"
    
    # Backend
    backend_image: str = "node:20-alpine"
    backend_workdir: str = "/app"
    backend_port: int = 8000
    backend_command: str = "uvicorn backend.main:application --host 0.0.0.0 --port 8000"
    
    # Frontend
    frontend_image: str = "node:20-alpine"
    frontend_workdir: str = "/app"
    frontend_port: int = 3000
    frontend_command: str = "npx serve -s dist -l 3000"
    
    # PostgreSQL (optional, SQLite is default)
    postgres_enabled: bool = False
    postgres_image: str = "postgres:16-alpine"
    postgres_port: int = 5432
    postgres_database: str = "arr_control"
    postgres_user: str = "arr_control"
    postgres_password: str = "changeme"
    
    # Storage
    volumes: List[dict] = [
        {
            "type": "volume",
            "source": "arr-control-data",
            "target": "/data",
            "readonly": False
        }
    ]
    
    # Environment variables
    env: List[str] = [
        "DATABASE_URL=sqlite:////data/arr-control.db",
        "APP_NAME=arr-control",
        "ENVIRONMENT=production",
        "DEBUG=false"
    ]
    
    # Restart policy
    restart_policy: str = "unless-stopped"
    healthcheck: dict = {
        "test": ["CMD", "curl", "-f", "http://localhost:8000/docs"],
        "interval": "30s",
        "timeout": "10s",
        "retries": 3,
        "start_period": "10s"
    }
    
    # Networks
    networks: List[str] = ["arr-control-network"]


def generate_docker_compose(config: DockerConfig) -> str:
    """Generate docker-compose.yml content."""
    return f"""version: '3.8'

services:
  backend:
    build:
      context: ../backend
      dockerfile: Dockerfile
    image: {config.name}-backend:{config.version}
    container_name: {config.name}-backend
    ports:
      - "{config.backend_port}:{config.backend_port}"
    volumes:
      - arr-control-data:/data
    environment:
      {"\\n      ".join(config.env)}
    restart: {config.restart_policy}
    healthcheck:
      test: {config.healthcheck["test"]}
      interval: {config.healthcheck["interval"]}
      timeout: {config.healthcheck["timeout"]}
      retries: {config.healthcheck["retries"]}
      start_period: {config.healthcheck["start_period"]}
    networks:
      - {config.networks[0]}

  frontend:
    build:
      context: ../frontend
      dockerfile: Dockerfile
    image: {config.name}-frontend:{config.version}
    container_name: {config.name}-frontend
    ports:
      - "{config.frontend_port}:3000"
    depends_on:
      - backend
    restart: {config.restart_policy}
    networks:
      - {config.networks[0]}

volumes:
  arr-control-data:
    driver: local

networks:
  {config.networks[0]}:
    driver: bridge
"""


def generate_dockerfile_backend() -> str:
    """Generate backend Dockerfile."""
    return """FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "backend.main:application", "--host", "0.0.0.0", "--port", "8000"]
"""


def generate_dockerfile_frontend() -> str:
    """Generate frontend Dockerfile."""
    return """FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

FROM node:20-alpine

WORKDIR /app

# Install serve for production
RUN npm install -g serve

# Copy built assets
COPY --from=builder /app/dist ./dist

EXPOSE 3000

CMD ["serve", "-s", "dist", "-l", "3000"]
"""