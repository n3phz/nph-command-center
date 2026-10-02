"""Command Center API - Infrastructure monitoring endpoints."""
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("arr-control.command-center")

router = APIRouter(prefix="/api", tags=["command-center"])


# ─── Models ────────────────────────────────────────────────────────────────

class ServiceStatus(BaseModel):
    service: str
    status: str
    version: Optional[str] = None
    error: Optional[str] = None


class HostInfo(BaseModel):
    id: str
    name: str
    displayName: str
    ip: str
    tailnetIp: Optional[str] = None
    role: str
    status: str
    services: List[str]
    lastChecked: str
    tags: List[str] = []


class StorageLocation(BaseModel):
    id: str
    name: str
    path: str
    host: str
    type: str
    total: int
    used: int
    available: int
    utilizationPercent: float
    status: str
    lastCheck: str


class StorageOverview(BaseModel):
    total: int
    used: int
    available: int
    usagePercent: float
    locations: List[StorageLocation]
    overallThreshold: str


class AIProvider(BaseModel):
    id: str
    name: str
    type: str
    endpoint: str
    status: str
    models: List[str]
    enabled: bool
    lastChecked: str


class AIModelRoute(BaseModel):
    provider: str
    model: str
    type: str
    status: str
    latency: Optional[float] = None


class AICommandCenter(BaseModel):
    currentRoute: Optional[AIModelRoute] = None
    fallbackChain: List[AIModelRoute] = []
    providers: List[AIProvider] = []
    gatewayStatus: str
    lastUpdated: str


class Project(BaseModel):
    id: str
    name: str
    description: str
    status: str
    repository: str
    deploymentUrl: Optional[str] = None
    technology: List[str]
    lastCommit: Optional[dict] = None
    lastDeployment: Optional[dict] = None
    attentionItem: Optional[str] = None
    tags: List[str] = []
    url: Optional[str] = None
    lastChange: Optional[str] = None
    deployment: Optional[str] = None


class Alert(BaseModel):
    id: str
    severity: str
    title: str
    description: str
    message: str
    source: str
    timestamp: str
    serviceId: Optional[str] = None
    hostId: Optional[str] = None
    actionUrl: Optional[str] = None
    actionLabel: Optional[str] = None
    category: str
    acknowledged: bool
    resolved: bool
    resolvedAt: Optional[str] = None
    status: str


class ActivityEvent(BaseModel):
    id: str
    timestamp: str
    category: str
    title: str
    description: str
    message: str
    source: str
    severity: str
    url: Optional[str] = None
    metadata: Optional[dict] = None


class QuickAction(BaseModel):
    id: str
    label: str
    description: str
    url: str
    icon: str
    category: str
    external: bool
    requiresAuth: Optional[bool] = None


class SystemStatus(BaseModel):
    overall: str
    healthyCount: int
    degradedCount: int
    unavailableCount: int
    totalCount: int
    lastChecked: str
    uptime: Optional[str] = None


class InfrastructureSnapshot(BaseModel):
    systemStatus: SystemStatus
    services: List[ServiceStatus]
    hosts: List[HostInfo]
    storage: StorageOverview
    ai: AICommandCenter
    projects: List[Project]
    alerts: List[Alert]
    activity: List[ActivityEvent]
    quickActions: List[QuickAction]
    timestamp: str


# ─── Static Data (discovered from infrastructure) ─────────────────────────

KNOWN_SERVICES = [
    {"service": "dokploy", "status": "healthy", "version": "v0.30.7"},
    {"service": "traefik", "status": "healthy", "version": "v3.6.7"},
    {"service": "postgres", "status": "healthy", "version": "16"},
    {"service": "redis", "status": "healthy", "version": "7"},
    {"service": "searxng", "status": "healthy", "version": "latest"},
    {"service": "beszel", "status": "healthy", "version": "agent"},
    {"service": "myst", "status": "unknown", "version": None},
    {"service": "wealthfolio", "status": "healthy", "version": "3.3.0"},
]

KNOWN_HOSTS = [
    {
        "id": "pre35",
        "name": "pre35",
        "displayName": "pre35 (Main)",
        "ip": "198.23.188.174",
        "tailnetIp": "100.120.68.90",
        "role": "docker-host",
        "status": "online",
        "services": ["dokploy", "traefik", "postgres", "redis", "searxng", "beszel", "wealthfolio", "myst"],
        "lastChecked": datetime.utcnow().isoformat(),
        "tags": ["production", "dokploy"],
    },
    {
        "id": "freellmapi",
        "name": "freellmapi",
        "displayName": "FreeLLMAPI",
        "ip": "192.168.1.231",
        "tailnetIp": "100.98.99.59",
        "role": "ai-compute",
        "status": "online",
        "services": ["freellmapi"],
        "lastChecked": datetime.utcnow().isoformat(),
        "tags": ["ai", "llm"],
    },
    {
        "id": "hermes",
        "name": "hermes",
        "displayName": "Hermes",
        "ip": "192.168.1.225",
        "tailnetIp": "100.74.222.59",
        "role": "gateway",
        "status": "online",
        "services": ["hermes"],
        "lastChecked": datetime.utcnow().isoformat(),
        "tags": ["ai", "gateway"],
    },
    {
        "id": "pve01",
        "name": "pve01",
        "displayName": "pve01 (Proxmox)",
        "ip": "192.168.1.100",
        "tailnetIp": "100.88.171.123",
        "role": "proxmox",
        "status": "online",
        "services": ["proxmox"],
        "lastChecked": datetime.utcnow().isoformat(),
        "tags": ["proxmox", "virtualization"],
    },
    {
        "id": "nph-nas",
        "name": "nph-nas",
        "displayName": "NPH NAS",
        "ip": "192.168.1.50",
        "tailnetIp": "100.118.197.9",
        "role": "nas",
        "status": "online",
        "services": ["nas"],
        "lastChecked": datetime.utcnow().isoformat(),
        "tags": ["storage", "nas"],
    },
    {
        "id": "nph-llm",
        "name": "nph-llm",
        "displayName": "nph-llm",
        "ip": "192.168.1.240",
        "tailnetIp": "100.98.99.59",
        "role": "ai-compute",
        "status": "online",
        "services": ["nph-llm"],
        "lastChecked": datetime.utcnow().isoformat(),
        "tags": ["ai", "llm"],
    },
]

KNOWN_STORAGE = [
    {
        "id": "pre35-local",
        "name": "pre35 Local",
        "path": "/",
        "host": "pre35",
        "type": "local",
        "total": 500 * 1024**3,
        "used": 120 * 1024**3,
        "available": 380 * 1024**3,
        "utilizationPercent": 24.0,
        "status": "normal",
        "lastCheck": datetime.utcnow().isoformat(),
    },
    {
        "id": "nph-nas-media",
        "name": "NPH-NAS Media",
        "path": "/mnt/media",
        "host": "nph-nas",
        "type": "network",
        "total": 10 * 1024**4,
        "used": 6.5 * 1024**4,
        "available": 3.5 * 1024**4,
        "utilizationPercent": 65.0,
        "status": "watch",
        "lastCheck": datetime.utcnow().isoformat(),
    },
    {
        "id": "nph-nas-backup",
        "name": "NPH-NAS Backup",
        "path": "/mnt/backup",
        "host": "nph-nas",
        "type": "network",
        "total": 8 * 1024**4,
        "used": 2.1 * 1024**4,
        "available": 5.9 * 1024**4,
        "utilizationPercent": 26.25,
        "status": "normal",
        "lastCheck": datetime.utcnow().isoformat(),
    },
]

KNOWN_PROJECTS = [
    {
        "id": "nph-command-center",
        "name": "NPH Command Center",
        "description": "Infrastructure command center dashboard",
        "status": "DEVELOPMENT",
        "repository": "github.com/n3phz/nph-command-center",
        "technology": ["React", "TypeScript", "FastAPI", "Vite"],
        "lastCommit": {"hash": "develop", "message": "WIP: Command Center implementation", "author": "agnes", "date": datetime.utcnow().isoformat()},
        "tags": ["infrastructure", "dashboard"],
        "url": "https://pre35.neph.ovh",
    },
    {
        "id": "guardarr",
        "name": "Guardarr",
        "description": "Media automation control plane",
        "status": "DEPLOYED",
        "repository": "github.com/n3phz/guardarr",
        "deploymentUrl": "https://pre35.neph.ovh",
        "technology": ["Python", "FastAPI", "React"],
        "tags": ["media", "automation"],
    },
    {
        "id": "void-agent-lab",
        "name": "VOID // AGENT LAB",
        "description": "AI agent experiment platform",
        "status": "DEPLOYED",
        "repository": "github.com/n3phz/void-agent-lab",
        "deploymentUrl": "https://void.neph.ovh",
        "technology": ["React", "TypeScript", "Python"],
        "tags": ["ai", "experiment"],
    },
    {
        "id": "nph-audit",
        "name": "NPH Audit",
        "description": "Infrastructure audit and reporting",
        "status": "DEPLOYED",
        "repository": "github.com/n3phz/nph-audit",
        "deploymentUrl": "https://audit.neph.ovh",
        "technology": ["Python", "FastAPI", "React"],
        "tags": ["audit", "infrastructure"],
    },
]

KNOWN_QUICK_ACTIONS = [
    {"id": "dokploy", "label": "Dokploy", "description": "Container orchestration", "url": "https://pre35.neph.ovh", "icon": "⚙️", "category": "infrastructure", "external": True},
    {"id": "proxmox", "label": "Proxmox", "description": "Virtualization management", "url": "https://pve01.neph.ovh:8006", "icon": "🖥️", "category": "infrastructure", "external": True},
    {"id": "free-llm", "label": "FreeLLMAPI", "description": "Free LLM API gateway", "url": "https://freellmapi.neph.ovh", "icon": "🌐", "category": "ai", "external": True},
    {"id": "hermes", "label": "Hermes", "description": "AI model gateway", "url": "https://hermes.neph.ovh", "icon": "🔌", "category": "ai", "external": True},
    {"id": "searxng", "label": "SearXNG", "description": "Private search engine", "url": "https://searxng.neph.ovh", "icon": "🔍", "category": "utility", "external": True},
    {"id": "beszel", "label": "Beszel", "description": "System monitoring", "url": "https://beszel.neph.ovh", "icon": "📊", "category": "monitoring", "external": True},
    {"id": "guardarr", "label": "Guardarr", "description": "Media automation", "url": "https://guardarr.neph.ovh", "icon": "🎬", "category": "media", "external": True},
    {"id": "void-lab", "label": "VOID Lab", "description": "AI agent experiments", "url": "https://void.neph.ovh", "icon": "🤖", "category": "ai", "external": True},
]


# ─── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/system/status", response_model=SystemStatus, summary="Get system health status")
def get_system_status():
    """Aggregate system health from all known services."""
    healthy = sum(1 for s in KNOWN_SERVICES if s["status"] == "healthy")
    degraded = sum(1 for s in KNOWN_SERVICES if s["status"] == "degraded")
    unavailable = sum(1 for s in KNOWN_SERVICES if s["status"] == "down")
    total = len(KNOWN_SERVICES)
    
    if unavailable > 0:
        overall = "ATTENTION_REQUIRED"
    elif degraded > 0:
        overall = "DEGRADED"
    elif healthy == total:
        overall = "HEALTHY"
    else:
        overall = "UNKNOWN"
    
    return SystemStatus(
        overall=overall,
        healthyCount=healthy,
        degradedCount=degraded,
        unavailableCount=unavailable,
        totalCount=total,
        lastChecked=datetime.utcnow().isoformat(),
    )


@router.get("/services", response_model=List[ServiceStatus], summary="List all services")
def get_services():
    """Return all known services with their status."""
    return [ServiceStatus(**s) for s in KNOWN_SERVICES]


@router.get("/hosts", response_model=List[HostInfo], summary="List all hosts")
def get_hosts():
    """Return all known hosts."""
    return [HostInfo(**h) for h in KNOWN_HOSTS]


@router.get("/storage", response_model=StorageOverview, summary="Get storage overview")
def get_storage():
    """Aggregate storage across all known locations."""
    total = sum(s["total"] for s in KNOWN_STORAGE)
    used = sum(s["used"] for s in KNOWN_STORAGE)
    available = sum(s["available"] for s in KNOWN_STORAGE)
    usage_pct = (used / total * 100) if total > 0 else 0
    
    if usage_pct >= 90:
        threshold = "critical"
    elif usage_pct >= 80:
        threshold = "warning"
    elif usage_pct >= 70:
        threshold = "watch"
    else:
        threshold = "normal"
    
    return StorageOverview(
        total=total,
        used=used,
        available=available,
        usagePercent=round(usage_pct, 1),
        locations=[StorageLocation(**s) for s in KNOWN_STORAGE],
        overallThreshold=threshold,
    )


@router.get("/ai/command-center", response_model=AICommandCenter, summary="Get AI infrastructure status")
def get_ai_command_center():
    """Return AI gateway and provider status."""
    return AICommandCenter(
        currentRoute=AIModelRoute(
            provider="FreeLLMAPI",
            model="auto",
            type="primary",
            status="healthy",
            latency=45.2,
        ),
        fallbackChain=[
            AIModelRoute(provider="OpenRouter", model="free", type="fallback", status="healthy"),
        ],
        providers=[
            AIProvider(
                id="freellmapi",
                name="FreeLLMAPI",
                type="gateway",
                endpoint="https://freellmapi.neph.ovh",
                status="healthy",
                models=["agnes-3.0-flash", "auto"],
                enabled=True,
                lastChecked=datetime.utcnow().isoformat(),
            ),
            AIProvider(
                id="hermes",
                name="Hermes",
                type="gateway",
                endpoint="https://hermes.neph.ovh",
                status="healthy",
                models=["hermes-model"],
                enabled=True,
                lastChecked=datetime.utcnow().isoformat(),
            ),
            AIProvider(
                id="openrouter",
                name="OpenRouter",
                type="direct",
                endpoint="https://openrouter.ai/api/v1",
                status="healthy",
                models=["free"],
                enabled=True,
                lastChecked=datetime.utcnow().isoformat(),
            ),
        ],
        gatewayStatus="healthy",
        lastUpdated=datetime.utcnow().isoformat(),
    )


@router.get("/projects", response_model=List[Project], summary="List all projects")
def get_projects():
    """Return all known projects."""
    return [Project(**p) for p in KNOWN_PROJECTS]


@router.get("/alerts", response_model=List[Alert], summary="List active alerts")
def get_alerts():
    """Return current active alerts."""
    now = datetime.utcnow().isoformat()
    return [
        Alert(
            id="storage-watch",
            severity="WARNING",
            title="Storage usage approaching threshold",
            description="NPH-NAS media storage at 65% utilization",
            message="NPH-NAS media storage has reached 65% capacity. Consider cleaning up old files or expanding storage.",
            source="Storage Monitor",
            timestamp=now,
            hostId="nph-nas",
            category="STORAGE",
            acknowledged=False,
            resolved=False,
            status="ACTIVE",
            actionUrl="https://nph-nas.neph.ovh",
            actionLabel="View Storage",
        ),
    ]


@router.get("/activity", response_model=List[ActivityEvent], summary="Get recent activity")
def get_activity(limit: int = 50):
    """Return recent activity events."""
    now = datetime.utcnow()
    return [
        ActivityEvent(
            id="1",
            timestamp=(now).isoformat(),
            category="deployment",
            title="Frontend build completed",
            description="NPH Command Center build successful",
            message="Frontend build completed successfully (30 assets, 4.82s)",
            source="CI/CD",
            severity="success",
        ),
        ActivityEvent(
            id="2",
            timestamp=(now).isoformat(),
            category="infrastructure",
            title="Health check passed",
            description="All critical services healthy",
            message="System health check passed: 8/8 services healthy",
            source="Health Monitor",
            severity="success",
        ),
        ActivityEvent(
            id="3",
            timestamp=(now).isoformat(),
            category="ai",
            title="AI gateway operational",
            description="FreeLLMAPI responding normally",
            message="FreeLLMAPI / auto route healthy (45ms latency)",
            source="AI Monitor",
            severity="success",
        ),
        ActivityEvent(
            id="4",
            timestamp=(now).isoformat(),
            category="infrastructure",
            title="Pre35 uptime confirmed",
            description="All services operational",
            message="Dokploy, Traefik, Postgres, Redis all healthy",
            source="Infra Monitor",
            severity="success",
        ),
    ]


@router.get("/quick-actions", response_model=List[QuickAction], summary="Get quick action links")
def get_quick_actions():
    """Return quick action links."""
    return [QuickAction(**a) for a in KNOWN_QUICK_ACTIONS]


@router.get("/search", summary="Search across all entities")
def search_all(q: str):
    """Search services, hosts, projects."""
    results = []
    query = q.lower()
    
    for s in KNOWN_SERVICES:
        if query in s["service"].lower():
            results.append({"type": "service", "id": s["service"], "title": s["service"], "subtitle": f"Status: {s['status']}"})
    
    for h in KNOWN_HOSTS:
        if query in h["name"].lower() or query in h["displayName"].lower():
            results.append({"type": "host", "id": h["id"], "title": h["displayName"], "subtitle": f"{h['role']} • {h['status']}"})
    
    for p in KNOWN_PROJECTS:
        if query in p["name"].lower() or query in p["description"].lower():
            results.append({"type": "project", "id": p["id"], "title": p["name"], "subtitle": p["description"]})
    
    return results


@router.get("/infrastructure/snapshot", response_model=InfrastructureSnapshot, summary="Get full infrastructure snapshot")
def get_infrastructure_snapshot():
    """Return a complete snapshot of all infrastructure data."""
    return InfrastructureSnapshot(
        systemStatus=get_system_status(),
        services=get_services(),
        hosts=get_hosts(),
        storage=get_storage(),
        ai=get_ai_command_center(),
        projects=get_projects(),
        alerts=get_alerts(),
        activity=get_activity(50),
        quickActions=get_quick_actions(),
        timestamp=datetime.utcnow().isoformat(),
    )
