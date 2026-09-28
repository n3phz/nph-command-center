# Media Control Plane

**Evidence-based control and observability for automated media pipelines.**

Media Control Plane (MCP) is a specialized control plane for media automation stacks built around **Sonarr**, **Radarr**, **qBittorrent**, **Prowlarr**, and **Guardarr**.

It is **not**:
- A replacement for Sonarr/Radarr
- A generic dashboard like Homarr
- A media player or streaming server

Instead, it is the **evidence-first control layer** that observes, correlates, and explains events across these systems.

## Core Concept

```
WANTED
  ↓
SEARCH / INDEXER ACTIVITY
  ↓
GRAB / DOWNLOAD / IMPORT
  ↓
MEDIA ITEM
  ↓
STATE VISUALIZATION
  ↓
WHY EXPLANATION
```

Every step in this pipeline is grounded in **actual observed data**, never speculation or inference.

## Key Features

| Feature | Description |
|---------|-------------|
| **Evidence Chain** | Full correlation from indexer query → grab → download → import → available |
| **Timeline View** | Interactive media timelines showing all events |
| **WHY Engine** | Explanations tied to concrete evidence, never assumptions |
| **Failure Analysis** | Groups real problems: stalled downloads, failed imports, unhealthy indexers |
| **Storage Visibility** | Dashboard shows media/download storage usage |
| **Historical Backfill** | Idempotent import of past events |
| **Production Deployment** | Docker Compose for clean installation |

## Current State

| Component | Status |
|-----------|--------|
| **Sonarr Integration** | ✅ Real-time webhook support |
| **Radarr Integration** | ✅ Webhook support |
| **qBittorrent Integration** | ✅ Polling-based event ingestion |
| **Prowlarr Integration** | ✅ Observes indexer activity |
| **Guardarr Integration** | ✅ Observes storage admission events |
| **Backend Tests** | 50 passed (unit/integration) |
| **Frontend Build** | Successful |
| **Docker Deployment** | Configuration provided |

## Live Validation Status

The system has been validated against a live test deployment. However, **real-time Guardarr correlation has not yet been observed** due to environment constraints. The implementation remains ready for production deployment.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/n3phz/media-control-plane.git
cd media-control-plane

# Build and run with Docker Compose
docker compose up --build
```

Environment variables are configured via `.env` with placeholders. Replace with actual values for production.

## Screenshots

*(Insert polished screenshots of Dashboard, Activity, Timeline, Media Detail, and WHY explanations)*

## Architecture

![Architecture Diagram](docs/architecture.svg)

*(Rendered Mermaid diagram showing event flow from data sources → correlation engine → UI)*

## Evidence Boundaries

Media Control Plane adheres to strict evidence-based principles:

- **Never invent causal relationships** without observable proof
- **Preserve source metadata** for all events
- **Distinguish certainty levels**: KNOWN | ESTIMATED | UNKNOWN
- **Explicitly document limitations** (e.g., Prowlarr lacks search-result visibility)

---

## Installation Guide

### Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.20+
- Access to Sonarr/Radarr/QBittorrent services

### Configuration

Create `.env` from `.env.example` and populate with your service URLs and API keys.

### Deployment

```bash
docker compose up -d
```

Health checks available at `/api/health`.

### API Documentation

Visit `/api/docs` for interactive Swagger UI.

---

*Media Control Plane is currently in active development. Features are progressively rolling out. Contributions welcome.*