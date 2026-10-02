/**
 * NPH Command Center - Core Type Definitions
 * 
 * Defines the data structures for the infrastructure command center.
 * These types represent real infrastructure entities, not mock data.
 */

// ============================================================================
// System Status
// ============================================================================

export type SystemHealthState = 'HEALTHY' | 'DEGRADED' | 'ATTENTION_REQUIRED' | 'OFFLINE' | 'UNKNOWN';

export interface SystemStatus {
  state: SystemHealthState;
  healthyCount: number;
  totalCount: number;
  degradedCount: number;
  unavailableCount: number;
  lastChecked: string;
  uptime?: string;
}

// ============================================================================
// Infrastructure Types
// ============================================================================

export type ServiceStatus = 'healthy' | 'degraded' | 'down' | 'unknown';

export interface Service {
  id: string;
  name: string;
  category: ServiceCategory;
  status: ServiceStatus;
  url?: string;
  host: string;
  description?: string;
  lastCheck: string;
  healthEndpoint?: string;
  version?: string;
  error?: string;
  uptime?: string;
  tags?: string[];
}

export type ServiceCategory = 
  | 'reverse-proxy' 
  | 'orchestration' 
  | 'storage' 
  | 'media-automation'
  | 'media-server'
  | 'download-client'
  | 'indexer'
  | 'monitoring'
  | 'dns'
  | 'security'
  | 'ai-gateway'
  | 'database'
  | 'cache'
  | 'utility'
  | 'other';

export interface ServiceCategoryInfo {
  id: ServiceCategory;
  label: string;
  icon: string;
  description: string;
}

export const SERVICE_CATEGORIES: Record<ServiceCategory, ServiceCategoryInfo> = {
  'reverse-proxy': { id: 'reverse-proxy', label: 'Reverse Proxy', icon: '🌐', description: 'Traefik, Nginx, Caddy' },
  'orchestration': { id: 'orchestration', label: 'Orchestration', icon: '⚙️', description: 'Dokploy, Portainer, Kubernetes' },
  'storage': { id: 'storage', label: 'Storage', icon: '💾', description: 'MinIO, SeaweedFS, NAS' },
  'media-automation': { id: 'media-automation', label: 'Media Automation', icon: '🎬', description: 'Sonarr, Radarr, Lidarr, Readarr' },
  'media-server': { id: 'media-server', label: 'Media Server', icon: '📺', description: 'Jellyfin, Plex, Emby' },
  'download-client': { id: 'download-client', label: 'Download Client', icon: '⬇️', description: 'qBittorrent, Transmission, SABnzbd' },
  'indexer': { id: 'indexer', label: 'Indexer', icon: '🔍', description: 'Prowlarr, Jackett' },
  'monitoring': { id: 'monitoring', label: 'Monitoring', icon: '📊', description: 'Beszel, Uptime Kuma, Prometheus' },
  'dns': { id: 'dns', label: 'DNS', icon: '🔗', description: 'Technitium, Pi-hole, AdGuard' },
  'security': { id: 'security', label: 'Security', icon: '🔐', description: 'Vaultwarden, Authelia, CrowdSec' },
  'ai-gateway': { id: 'ai-gateway', label: 'AI Gateway', icon: '🤖', description: 'FreeLLMAPI, LiteLLM, OpenClaw' },
  'database': { id: 'database', label: 'Database', icon: '🗄️', description: 'PostgreSQL, MongoDB, Redis, Valkey' },
  'cache': { id: 'cache', label: 'Cache', icon: '⚡', description: 'Redis, Valkey, Memcached' },
  'utility': { id: 'utility', label: 'Utility', icon: '🔧', description: 'BookStack, NetAlertX, Unpackerr' },
  'other': { id: 'other', label: 'Other', icon: '📦', description: 'Miscellaneous services' },
};

// ============================================================================
// Host Types
// ============================================================================

export type HostStatus = 'online' | 'offline' | 'degraded' | 'unknown';

export interface Host {
  id: string;
  name: string;
  displayName: string;
  ip?: string;
  tailnetIp?: string;
  status: HostStatus;
  cpu?: HostMetric;
  memory?: HostMetric;
  storage?: HostStorage[];
  uptime?: string;
  os?: string;
  kernel?: string;
  services: string[]; // Service IDs running on this host
  lastCheck: string;
  tags?: string[];
}

export interface HostMetric {
  used: number;
  total: number;
  unit: 'percent' | 'bytes' | 'cores';
}

export interface HostStorage {
  mount: string;
  used: number;
  total: number;
  filesystem?: string;
}

// ============================================================================
// Storage Types
// ============================================================================

export interface StorageOverview {
  total: number;
  used: number;
  available: number;
  utilizationPercent: number;
  locations: StorageLocation[];
  warningThreshold: number;
  criticalThreshold: number;
}

export interface StorageLocation {
  id: string;
  name: string;
  path: string;
  host: string;
  type: 'local' | 'network' | 'object' | 'distributed';
  total: number;
  used: number;
  available: number;
  utilizationPercent: number;
  status: 'normal' | 'watch' | 'warning' | 'critical';
  lastCheck: string;
}

// ============================================================================
// AI Infrastructure Types
// ============================================================================

export interface AIProvider {
  id: string;
  name: string;
  type: 'primary' | 'fallback' | 'local' | 'remote';
  status: ServiceStatus;
  endpoint?: string;
  model?: string;
  models?: string[];
  available?: boolean;
  lastCheck: string;
  error?: string;
  config?: Record<string, unknown>;
}

export interface AIModelRoute {
  provider: string;
  model: string;
  type: 'primary' | 'fallback' | 'local';
  status: ServiceStatus;
  latency?: number;
}

export interface AICommandCenter {
  currentRoute: AIModelRoute | null;
  fallbackChain: AIModelRoute[];
  providers: AIProvider[];
  gatewayStatus: ServiceStatus;
  lastUpdated: string;
}

// ============================================================================
// Project Types
// ============================================================================

export type ProjectStatus = 'ACTIVE' | 'DEPLOYED' | 'DEVELOPMENT' | 'ATTENTION' | 'ARCHIVED' | 'UNKNOWN';

export interface Project {
  id: string;
  name: string;
  status: ProjectStatus;
  repository?: string;
  deployment?: string;
  lastChange?: string;
  technology?: string[];
  url?: string;
  description?: string;
  nextAttentionItem?: string;
  tags?: string[];
}

// ============================================================================
// Alert Types
// ============================================================================

export type AlertSeverity = 'CRITICAL' | 'WARNING' | 'INFO';

export interface Alert {
  id: string;
  severity: AlertSeverity;
  title: string;
  message: string;
  source: string;
  timestamp: string;
  serviceId?: string;
  hostId?: string;
  actionUrl?: string;
  actionLabel?: string;
  acknowledged: boolean;
  resolved: boolean;
  resolvedAt?: string;
}

// ============================================================================
// Activity Types
// ============================================================================

export type ActivityCategory = 'DEPLOYMENT' | 'AI' | 'INFRA' | 'PROJECT' | 'SECURITY' | 'STORAGE' | 'NETWORK' | 'OTHER';

export interface ActivityEvent {
  id: string;
  timestamp: string;
  category: ActivityCategory;
  title: string;
  message: string;
  source: string;
  severity: 'success' | 'warning' | 'error' | 'info';
  url?: string;
  metadata?: Record<string, unknown>;
}

// ============================================================================
// Quick Action Types
// ============================================================================

export interface QuickAction {
  id: string;
  label: string;
  description: string;
  url: string;
  icon: string;
  category: 'infrastructure' | 'ai' | 'media' | 'monitoring' | 'utility';
  external: boolean;
}

// ============================================================================
// Search Types
// ============================================================================

export interface SearchResult {
  id: string;
  type: 'service' | 'host' | 'project' | 'alert' | 'activity';
  title: string;
  subtitle: string;
  url?: string;
  metadata?: Record<string, unknown>;
}

// ============================================================================
// API Response Types
// ============================================================================

export interface HealthCheckResponse {
  service: string;
  status: ServiceStatus;
  version?: string;
  error?: string;
  details?: Record<string, unknown>;
  latency?: number;
}

export interface InfrastructureSnapshot {
  systemStatus: SystemStatus;
  services: Service[];
  hosts: Host[];
  storage: StorageOverview;
  ai: AICommandCenter;
  projects: Project[];
  alerts: Alert[];
  activity: ActivityEvent[];
  quickActions: QuickAction[];
  timestamp: string;
}

// ============================================================================
// Utility Types
// ============================================================================

export interface TimeRange {
  from: string;
  to: string;
}

export interface Pagination {
  page: number;
  limit: number;
  total: number;
}

export type SortDirection = 'asc' | 'desc';

export interface SortConfig {
  key: string;
  direction: SortDirection;
}