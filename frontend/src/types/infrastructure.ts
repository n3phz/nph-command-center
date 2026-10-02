/** Core infrastructure types for NPH Command Center */

// ============================================
// Media Items (for live pipeline updates)
// ============================================

export interface MediaItem {
  id: string;
  correlation_key: string;
  media_type: 'movie' | 'episode';
  title: string;
  season?: number;
  episode?: number;
  tvdb_id?: string;
  tmdb_id?: string;
  imdb_id?: string;
  current_state: string;
  progress?: number;
  current_service?: string;
  last_event_at?: string;
  next_expected_state?: string;
  event_count: number;
  first_seen_at?: string;
  confidence?: 'HIGH' | 'MEDIUM' | 'LOW';
  download_attempts?: any[];
  ingestion_sources?: ('webhook' | 'polling')[];
  state?: string; // For PipelineRow compatibility
  guardarr_events?: any[];
}

// ============================================
// System Status
// ============================================

export type SystemHealthStatus = 'HEALTHY' | 'DEGRADED' | 'ATTENTION_REQUIRED' | 'OFFLINE';

export interface SystemStatus {
  overall: SystemHealthStatus;
  healthyCount: number;
  degradedCount: number;
  unavailableCount: number;
  totalCount: number;
  lastChecked: string;
  uptime?: string;
}

// ============================================
// Services
// ============================================

export type ServiceStatus = 'healthy' | 'degraded' | 'down' | 'unknown' | 'discovered';

export interface Service {
  id: string;
  name: string;
  category: ServiceCategory;
  description: string;
  url: string;
  host: string;
  status: ServiceStatus;
  version?: string;
  uptime?: string;
  lastCheck: string;
  tags: string[];
}

export type ServiceCategory = 
  | 'reverse-proxy'
  | 'orchestration'
  | 'media-automation'
  | 'media-server'
  | 'download-client'
  | 'indexer'
  | 'storage'
  | 'database'
  | 'cache'
  | 'monitoring'
  | 'dns'
  | 'ai-gateway'
  | 'ai-model'
  | 'security'
  | 'utility'
  | 'development'
  | 'other';

export const SERVICE_CATEGORIES: Record<ServiceCategory, { label: string; icon: string }> = {
  'reverse-proxy': { label: 'Reverse Proxy', icon: '🔀' },
  'orchestration': { label: 'Orchestration', icon: '⚙️' },
  'media-automation': { label: 'Media Automation', icon: '🎬' },
  'media-server': { label: 'Media Server', icon: '📺' },
  'download-client': { label: 'Download Client', icon: '⬇️' },
  'indexer': { label: 'Indexer', icon: '🔍' },
  'storage': { label: 'Storage', icon: '💾' },
  'database': { label: 'Database', icon: '🗄️' },
  'cache': { label: 'Cache', icon: '⚡' },
  'monitoring': { label: 'Monitoring', icon: '📊' },
  'dns': { label: 'DNS', icon: '🌐' },
  'ai-gateway': { label: 'AI Gateway', icon: '🤖' },
  'ai-model': { label: 'AI Model', icon: '🧠' },
  'security': { label: 'Security', icon: '🔐' },
  'utility': { label: 'Utility', icon: '🔧' },
  'development': { label: 'Development', icon: '💻' },
  'other': { label: 'Other', icon: '📦' },
};

// ============================================
// Hosts
// ============================================

export interface HostMetrics {
  cpu?: {
    usage: number;
    cores: number;
    model?: string;
  };
  memory?: {
    used: number;
    total: number;
    usagePercent: number;
  };
  disk?: {
    used: number;
    total: number;
    usagePercent: number;
  };
  uptime?: number;
  loadAverage?: number[];
}

export interface Host {
  id: string;
  name: string;
  displayName?: string;
  hostname: string;
  ip: string;
  tailnetIp?: string;
  role: HostRole;
  status: 'online' | 'offline' | 'degraded' | 'discovered';
  metrics?: HostMetrics;
  services: string[];
  lastChecked: string;
  tags: string[];
  os?: string;
  uptime?: string;
}

export type HostRole = 
  | 'proxmox'
  | 'docker-host'
  | 'nas'
  | 'ai-compute'
  | 'media-server'
  | 'monitoring'
  | 'gateway'
  | 'dns'
  | 'development'
  | 'unknown';

// ============================================
// Storage
// ============================================

export interface StorageLocation {
  id: string;
  name: string;
  path: string;
  host: string;
  type: 'local' | 'network' | 'object' | 'distributed';
  total: number;
  used: number;
  available: number;
  usagePercent: number;
  utilizationPercent: number;
  status: StorageThreshold;
  threshold: StorageThreshold;
  lastCheck: string;
}

export type StorageThreshold = 'normal' | 'watch' | 'warning' | 'critical';

export interface StorageOverview {
  total: number;
  used: number;
  available: number;
  usagePercent: number;
  locations: StorageLocation[];
  overallThreshold: StorageThreshold;
}

// ============================================
// AI Infrastructure
// ============================================

export interface AIProvider {
  id: string;
  name: string;
  type: 'gateway' | 'direct' | 'local';
  endpoint: string;
  status: ServiceStatus;
  models: AIModel[];
  fallbackOrder?: number;
  enabled: boolean;
  lastChecked: string;
  healthDetails?: {
    latency?: number;
    rateLimitRemaining?: number;
    rateLimitReset?: string;
  };
}

export interface AIModel {
  id: string;
  name: string;
  provider: string;
  type: 'chat' | 'completion' | 'embedding' | 'image' | 'audio';
  contextWindow?: number;
  maxOutputTokens?: number;
  pricing?: {
    input: number;
    output: number;
    currency: string;
  };
  isDefault?: boolean;
  isFallback?: boolean;
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

// ============================================
// Projects
// ============================================

export type ProjectStatus = 'ACTIVE' | 'DEPLOYED' | 'DEVELOPMENT' | 'ATTENTION' | 'ARCHIVED';

export interface Project {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  repository: string;
  deploymentUrl?: string;
  technology: string[];
  lastCommit?: {
    hash: string;
    message: string;
    author: string;
    date: string;
  };
  lastDeployment?: {
    date: string;
    status: 'success' | 'failed' | 'pending';
    url?: string;
  };
  attentionItem?: string;
  tags: string[];
  url?: string;
  lastChange?: string;
  deployment?: string;
}

// ============================================
// Alerts
// ============================================

export type AlertSeverity = 'CRITICAL' | 'WARNING' | 'INFO';
export type AlertStatus = 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED';

export interface Alert {
  id: string;
  severity: AlertSeverity;
  title: string;
  description: string;
  message: string;
  source: string;
  timestamp: string;
  serviceId?: string;
  hostId?: string;
  actionUrl?: string;
  actionLabel?: string;
  category: 'INFRASTRUCTURE' | 'AI' | 'STORAGE' | 'NETWORK' | 'SERVICE' | 'DEPLOYMENT' | 'SECURITY';
  acknowledged: boolean;
  resolved: boolean;
  resolvedAt?: string;
  status: AlertStatus;
}

// ============================================
// Activity
// ============================================

export type ActivityCategory = 
  | 'deployment'
  | 'git'
  | 'service'
  | 'alert'
  | 'infrastructure'
  | 'project'
  | 'ai';

export interface ActivityEvent {
  id: string;
  timestamp: string;
  category: ActivityCategory;
  title: string;
  description: string;
  message: string;
  source: string;
  severity: AlertSeverity;
  url?: string;
  metadata?: Record<string, unknown>;
}

// ============================================
// Quick Actions
// ============================================

export interface QuickAction {
  id: string;
  label: string;
  description: string;
  url: string;
  icon: string;
  category: 'infrastructure' | 'ai' | 'media' | 'monitoring' | 'development' | 'other' | 'utility' | 'security';
  external: boolean;
  requiresAuth?: boolean;
}

// ============================================
// Search
// ============================================

export interface SearchResult {
  type: 'service' | 'host' | 'project' | 'alert' | 'activity';
  id: string;
  title: string;
  subtitle: string;
  url?: string;
  metadata?: Record<string, unknown>;
}