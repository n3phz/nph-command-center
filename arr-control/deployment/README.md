# Deployment documentation for arr-control

## Overview

arr-control is a media automation control plane that observes, correlates, and explains events across your ARR stack.

## Components

### Backend
- FastAPI application running on port 8000
- SQLite database for persistence
- REST API with Swagger/OpenAPI docs at `/docs`

### Frontend
- React application running on port 3000
- Serves static files via `serve`
- Communicates with backend via REST API

## Deployment Options

### Option 1: Docker Compose (Recommended)

```bash
cd deployment
docker-compose up -d
```

### Option 2: Manual Build

1. Build backend:
```bash
cd backend
pip install -r requirements.txt
uvicorn backend.main:application --host 0.0.0.0 --port 8000
```

2. Build frontend:
```bash
cd frontend
npm install
npm run build
npx serve -s dist -l 3000
```

### Option 3: Production Kubernetes

See `deployment/kubernetes/` for Kubernetes manifests (when implemented).

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:////tmp/arr-control.db` | Database connection string |
| `SONARR_URL` | `http://localhost:8989` | Sonarr API URL |
| `SONARR_API_KEY` | | Sonarr API key |
| `RADARR_URL` | `http://localhost:7878` | Radarr API URL |
| `RADARR_API_KEY` | | Radarr API key |
| `QBITTORRENT_URL` | `http://localhost:8080` | qBittorrent API URL |
| `QBITTORRENT_USERNAME` | `admin` | qBittorrent username |
| `QBITTORRENT_PASSWORD` | `adminadmin` | qBittorrent password |
| `PROWLARR_URL` | `http://localhost:9696` | Prowlarr API URL |
| `PROWLARR_API_KEY` | | Prowlarr API key |
| `POLL_INTERVAL_SECONDS` | `30` | Polling interval |
| `DEBUG` | `false` | Enable debug mode |

### Webhook Configuration

To enable real-time event ingestion, configure webhooks in Sonarr/Radarr:

**Sonarr:**
- Settings → Connect → Add Connection
- Select Webhook
- Name: arr-control
- URL: `http://arr-control-backend:8000/api/webhook/sonarr`
- Events: Grab, Download, Import, Rename

**Radarr:**
- Settings → Connect → Add Connection
- Select Webhook
- Name: arr-control
- URL: `http://arr-control-backend:8000/api/webhook/radarr`
- Events: Grab, Download, Import, Rename

## API Endpoints

### Health
- `GET /api/health` - Basic health check
- `GET /api/ready` - Readiness check

### Items
- `GET /api/items` - List media items
- `GET /api/items/{id}` - Get item details
- `GET /api/items/{id}/timeline` - Get timeline
- `GET /api/items/{id}/explain` - Get explanation
- `GET /api/items/orphans` - Get unmatched torrents

### Services
- `GET /api/services` - List service statuses
- `GET /api/services/{service}` - Get service status
- `POST /api/services/poll` - Force poll

### Events
- `GET /api/events` - List events

### Webhooks
- `POST /api/webhook/sonarr` - Receive Sonarr webhooks
- `POST /api/webhook/radarr` - Receive Radarr webhooks
- `POST /api/webhook/prowlarr` - Receive Prowlarr webhooks

### Backfill
- `POST /api/backfill` - Start historical backfill
- `GET /api/backfill/status` - Get backfill status
- `POST /api/backfill/cancel` - Cancel backfill

### Activity
- `GET /api/activity` - List activity events
- `GET /api/activity/stats` - Get activity statistics
- `GET /api/activity/failures` - Get failures
- `GET /api/activity/stalled` - Get stalled downloads

## Monitoring

### Health Endpoints
- Backend: `http://localhost:8000/api/health`
- Frontend: `http://localhost:3000`

### Swagger Documentation
- `http://localhost:8000/docs`

### Metrics
Metrics are not yet exposed. Plan to add Prometheus metrics endpoint in future phase.

## Logs

### Backend Logs
```bash
docker logs arr-control-backend
```

### Frontend Logs
```bash
docker logs arr-control-frontend
```

## Troubleshooting

### Service Unhealthy
Check connectivity to Sonarr/Radarr/qBittorrent/Prowlarr:
```bash
curl -H "X-Api-Key: $SONARR_API_KEY" http://sonarr:8989/api/v3/system/status
```

### Missing Events
Run backfill to import historical events:
```bash
curl -X POST http://localhost:8000/api/backfill -d '{"days": 30}'
```

### Stuck Downloads
Check qBittorrent directly:
```bash
curl -u admin:adminadmin http://qbittorrent:8080/api/v2/torrents/info
```

## Security Considerations

1. **Network Isolation**: The application should run in an isolated network. Do not expose ports to the public internet.

2. **API Keys**: Store API keys in environment variables or secret management systems. Never commit them to version control.

3. **TLS**: For production deployments, use a reverse proxy (nginx, Traefik) with TLS termination.

4. **Authentication**: Add authentication middleware for production use.

5. **Rate Limiting**: Implement rate limiting for webhook endpoints to prevent abuse.

## Future Improvements

- [ ] Add Prometheus metrics
- [ ] Add authentication/authorization
- [ ] Support PostgreSQL
- [ ] Add real-time updates via WebSocket
- [ ] Support multiple Prowlarr instances
- [ ] Add Guardarr integration (Phase 3)
- [ ] Add Lidarr/Readarr integration
- [ ] Add Bazarr integration
- [ ] Add Overseerr/Jellyseerr integration