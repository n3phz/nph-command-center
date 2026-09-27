# arr-control

**Media Automation Control Plane** — A system-level observability and correlation layer for the ARR stack.

## What This Is

This is **NOT** a replacement for Sonarr, Radarr, Prowlarr, qBittorrent, etc. It is a system-level **observability and correlation layer** that explains what your media automation stack is doing and why something failed.

## Core Product

```
RAW EVENTS → CORRELATION → MEDIA STATE → TIMELINE → EXPLANATION
```

Everything is designed around making that pipeline reliable.

## Architecture

### Backend (Python/FastAPI)
- **Adapters**: Read-only integrations with Sonarr, Radarr, qBittorrent
- **Correlation Engine**: Matches events across services using deterministic identifiers
- **State Machine**: Validates lifecycle transitions
- **Event Store**: Append-only SQLite database
- **REST API**: Clean endpoints for data access

### Frontend (React/TypeScript)
- Minimal operational dashboard
- Timeline visualization
- Service health indicators
- Failure explanations

## Data Model

### Event Structure
```python
{
    "timestamp": datetime,
    "source_service": "sonarr" | "radarr" | "qbittorrent",
    "event_type": EventType,  # WANTED, RELEASE_GRABBED, DOWNLOAD_PROGRESS, etc.
    "media_type": "movie" | "episode",
    "media_identifier": str,  # TVDB/TMDB/IMDb ID
    "title": str,
    "season": Optional[int],
    "episode": Optional[int],
    "correlation_key": str,   # Computed key for matching
    "source_payload": dict,   # Raw API response
    "normalized_metadata": dict,
    "status": EventStatus,
    "error_message": Optional[str]
}
```

### Lifecycle States
```
Wanted → Searching → Release Grabbed → Downloading → Download Completed → Importing → Imported → Available
                                                                          ↓
                                                                    Failed states
```

## Media Item Example

```json
{
    "id": "tmdb:157336",
    "title": "Dune: Part Two",
    "media_type": "movie",
    "state": "import_failed",
    "progress": null,
    "timeline": [
        {"timestamp": "19:02", "source": "radarr", "event_type": "wanted"},
        {"timestamp": "19:03", "source": "radarr", "event_type": "release_grabbed"},
        {"timestamp": "19:04", "source": "qbittorrent", "event_type": "download_started"},
        {"timestamp": "19:07", "source": "qbittorrent", "event_type": "download_progress", "progress": 74},
        {"timestamp": "19:10", "source": "qbittorrent", "event_type": "download_completed"},
        {"timestamp": "19:11", "source": "radarr", "event_type": "import_started"},
        {"timestamp": "19:12", "source": "radarr", "event_type": "import_failed", "error": "Invalid format"}
    ],
    "next_expected_state": "wanted"
}
```

## Correlation Strategy

Priority order for matching events:
1. Explicit `correlation_key`
2. Hash-based (qBittorrent torrent hash)
3. TVDB/TMDB/IMDb ID
4. Title-based fallback (normalized)

## Installation

### Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example .env
# Edit .env with your actual API keys
uvicorn backend.main:application --reload

# Frontend
cd frontend
npm install
npm run dev
```

### Docker

```bash
cp .env.example .env
# Edit .env with your actual API keys
docker-compose up -d
```

## Configuration

Copy `.env.example` to `.env` and set your values:

| Variable | Default | Description |
|----------|---------|-------------|
| `SONARR_URL` | `http://localhost:8989` | Sonarr base URL |
| `SONARR_API_KEY` | *(required)* | Sonarr API key |
| `RADARR_URL` | `http://localhost:7878` | Radarr base URL |
| `RADARR_API_KEY` | *(required)* | Radarr API key |
| `QBITTORRENT_URL` | `http://localhost:8080` | qBittorrent base URL |
| `QBITTORRENT_USERNAME` | `admin` | qBittorrent username |
| `QBITTORRENT_PASSWORD` | *(required)* | qBittorrent password |
| `POLL_INTERVAL_SECONDS` | `30` | Polling frequency |
| `DATABASE_URL` | `sqlite:////config/arr-control.db` | Database path |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check |
| `GET /api/ready` | Readiness check |
| `GET /api/items` | List all media items |
| `GET /api/items/{id}` | Get item detail |
| `GET /api/items/{id}/timeline` | Get event timeline |
| `GET /api/items/{id}/explain` | Get human-readable explanation |
| `GET /api/events` | List raw events |
| `GET /api/services` | List service statuses |
| `POST /api/services/poll` | Force immediate poll |

## Running Tests

```bash
cd backend
pytest
```

## Current Limitations

- qBittorrent title matching is heuristic-based (no direct API link to Sonarr/Radarr)
- No webhook support yet (polling only)
- No automatic retry logic for failures
- Frontend is minimal operational UI

## Future Integrations

Phase 2 candidates:
- Prowlarr (indexer health)
- Bazarr (subtitle tracking)
- Unpackerr (archive extraction)
- Jellyfin/Plex (playback verification)
- Lidarr (music)
- Readarr (books)
- Guardarr integration (existing reservation system)

## Project Principle

The dashboard itself is **NOT** the main product. The core product is the pipeline:

```
Events → Correlation → State → Timeline → Explanation
```

Everything supports making that pipeline reliable.

---

**Built with:** Python 3.11+, FastAPI, SQLAlchemy, SQLite, React, TypeScript