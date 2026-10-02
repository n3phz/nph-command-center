/**
 * NPH Command Center - API Service Layer
 * 
 * Centralized API client for all command center data.
 * Handles caching, timeouts, parallel requests, and graceful degradation.
 */

import type {
  SystemStatus,
  Service,
  Host,
  StorageOverview,
  AICommandCenter,
  Project,
  Alert,
  ActivityEvent,
  QuickAction,
  SearchResult,
  ServiceCategory,
  HostRole,
  MediaItem,
} from '../types/infrastructure';

const API_BASE = '/api';
const CACHE_DURATION = 30000; // 30 seconds

// ============================================================================
// Cache & Request Utilities
// ============================================================================

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

const cache = new Map<string, CacheEntry<any>>();

function getCached<T>(key: string): T | null {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.timestamp < CACHE_DURATION) {
    return entry.data;
  }
  return null;
}

function setCache<T>(key: string, data: T): void {
  cache.set(key, { data, timestamp: Date.now() });
}

function clearCache(key?: string): void {
  if (key) {
    cache.delete(key);
  } else {
    cache.clear();
  }
}

async function fetchWithTimeout<T>(
  url: string,
  options: RequestInit = {},
  timeoutMs = 5000
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      throw new Error(`API error: ${response.status} ${response.statusText}`);
    }
    return response.json() as Promise<T>;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`Request timeout: ${url}`);
    }
    throw error;
  }
}

export async function fetchAllSettled<T>(
  requests: Array<() => Promise<T>>,
  defaultValues: T[]
): Promise<T[]> {
  const results = await Promise.allSettled(requests.map(r => r()));
  return results.map((result, index) => 
    result.status === 'fulfilled' ? result.value : defaultValues[index]
  );
}

// ============================================================================
// System Status
// ============================================================================

export async function getSystemStatus(): Promise<SystemStatus> {
  const cached = getCached<SystemStatus>('system-status');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<SystemStatus>(`${API_BASE}/system/status`);
    setCache('system-status', data);
    return data;
  } catch {
    return {
      overall: 'OFFLINE',
      healthyCount: 0,
      degradedCount: 0,
      unavailableCount: 0,
      totalCount: 0,
      lastChecked: new Date().toISOString(),
    };
  }
}

// ============================================================================
// Services
// ============================================================================

export async function getServices(): Promise<Service[]> {
  const cached = getCached<Service[]>('services');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<Service[]>(`${API_BASE}/services`);
    setCache('services', data);
    return data;
  } catch {
    return [];
  }
}

export async function getService(id: string): Promise<Service | null> {
  try {
    return await fetchWithTimeout<Service>(`${API_BASE}/services/${id}`);
  } catch {
    return null;
  }
}

export async function getServicesByCategory(): Promise<Record<ServiceCategory, Service[]>> {
  const services = await getServices();
  const categories = services.reduce((acc, service) => {
    if (!acc[service.category]) acc[service.category] = [];
    acc[service.category].push(service);
    return acc;
  }, {} as Record<ServiceCategory, Service[]>);
  return categories;
}

// ============================================================================
// Hosts
// ============================================================================

export async function getHosts(): Promise<Host[]> {
  const cached = getCached<Host[]>('hosts');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<Host[]>(`${API_BASE}/hosts`);
    setCache('hosts', data);
    return data;
  } catch {
    return [];
  }
}

export async function getHost(id: string): Promise<Host | null> {
  try {
    return await fetchWithTimeout<Host>(`${API_BASE}/hosts/${id}`);
  } catch {
    return null;
  }
}

export async function getHostsByRole(): Promise<Record<HostRole, Host[]>> {
  const hosts = await getHosts();
  return hosts.reduce((acc, host) => {
    if (!acc[host.role]) acc[host.role] = [];
    acc[host.role].push(host);
    return acc;
  }, {} as Record<HostRole, Host[]>);
}

// ============================================================================
// Storage
// ============================================================================

export async function getStorageOverview(): Promise<StorageOverview> {
  const cached = getCached<StorageOverview>('storage');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<StorageOverview>(`${API_BASE}/storage`);
    setCache('storage', data);
    return data;
  } catch {
    return {
      total: 0,
      used: 0,
      available: 0,
      usagePercent: 0,
      locations: [],
      overallThreshold: 'normal',
    };
  }
}

// ============================================================================
// AI Infrastructure
// ============================================================================

export async function getAICommandCenter(): Promise<AICommandCenter> {
  const cached = getCached<AICommandCenter>('ai-command-center');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<AICommandCenter>(`${API_BASE}/ai/command-center`);
    setCache('ai-command-center', data);
    return data;
  } catch {
    return {
      currentRoute: null,
      fallbackChain: [],
      providers: [],
      gatewayStatus: 'unknown',
      lastUpdated: new Date().toISOString(),
    };
  }
}

// ============================================================================
// Projects
// ============================================================================

export async function getProjects(): Promise<Project[]> {
  const cached = getCached<Project[]>('projects');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<Project[]>(`${API_BASE}/projects`);
    setCache('projects', data);
    return data;
  } catch {
    return [];
  }
}

export async function getProject(id: string): Promise<Project | null> {
  try {
    return await fetchWithTimeout<Project>(`${API_BASE}/projects/${id}`);
  } catch {
    return null;
  }
}

// ============================================================================
// Alerts
// ============================================================================

export async function getAlerts(): Promise<Alert[]> {
  const cached = getCached<Alert[]>('alerts');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<Alert[]>(`${API_BASE}/alerts`);
    setCache('alerts', data);
    return data;
  } catch {
    return [];
  }
}

export async function acknowledgeAlert(id: string): Promise<void> {
  await fetchWithTimeout(`${API_BASE}/alerts/${id}/acknowledge`, { method: 'POST' });
  clearCache('alerts');
}

export async function resolveAlert(id: string): Promise<void> {
  await fetchWithTimeout(`${API_BASE}/alerts/${id}/resolve`, { method: 'POST' });
  clearCache('alerts');
}

// ============================================================================
// Activity
// ============================================================================

export async function getActivityFeed(limit = 50): Promise<ActivityEvent[]> {
  const cached = getCached<ActivityEvent[]>('activity');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<ActivityEvent[]>(`${API_BASE}/activity?limit=${limit}`);
    setCache('activity', data);
    return data;
  } catch {
    return [];
  }
}

// ============================================================================
// Quick Actions
// ============================================================================

export async function getQuickActions(): Promise<QuickAction[]> {
  const cached = getCached<QuickAction[]>('quick-actions');
  if (cached) return cached;
  
  try {
    const data = await fetchWithTimeout<QuickAction[]>(`${API_BASE}/quick-actions`);
    setCache('quick-actions', data);
    return data;
  } catch {
    return [];
  }
}

// ============================================================================
// Search
// ============================================================================

export async function searchAll(query: string): Promise<SearchResult[]> {
  if (!query.trim()) return [];
  
  try {
    const data = await fetchWithTimeout<SearchResult[]>(`${API_BASE}/search?q=${encodeURIComponent(query)}`, {}, 3000);
    return data;
  } catch {
    return [];
  }
}

// ============================================================================
// Infrastructure Snapshot
// ============================================================================

export async function getInfrastructureSnapshot(): Promise<{
  systemStatus: SystemStatus;
  services: Service[];
  hosts: Host[];
  storage: StorageOverview;
  ai: AICommandCenter;
  projects: Project[];
  alerts: Alert[];
  activity: ActivityEvent[];
  quickActions: QuickAction[];
  mediaItems: MediaItem[];
  timestamp: string;
}> {
  try {
    const [
      systemStatus,
      services,
      hosts,
      storage,
      ai,
      projects,
      alerts,
      activity,
      quickActions
    ] = await Promise.all([
      getSystemStatus(),
      getServices(),
      getHosts(),
      getStorageOverview(),
      getAICommandCenter(),
      getProjects(),
      getAlerts(),
      getActivityFeed(50),
      getQuickActions()
    ]);
    const mediaItems = await getMediaItems();
    
    return {
      systemStatus,
      services,
      hosts,
      storage,
      ai,
      projects,
      alerts,
      activity,
      quickActions,
      mediaItems,
      timestamp: new Date().toISOString()
    };
  } catch {
    return {
      systemStatus: {
        overall: 'OFFLINE',
        healthyCount: 0,
        degradedCount: 0,
        unavailableCount: 0,
        totalCount: 0,
        lastChecked: new Date().toISOString(),
      },
      services: [],
      hosts: [],
      storage: {
        total: 0,
        used: 0,
        available: 0,
        usagePercent: 0,
        locations: [],
        overallThreshold: 'normal',
      },
      ai: {
        currentRoute: null,
        fallbackChain: [],
        providers: [],
        gatewayStatus: 'unknown',
        lastUpdated: new Date().toISOString(),
      },
      projects: [],
      alerts: [],
      activity: [],
      quickActions: [],
      mediaItems: [],
      timestamp: new Date().toISOString(),
    };
  }
}

// ============================================================================
// Media Items
// ============================================================================

export async function getMediaItems(): Promise<MediaItem[]> {
  try {
    const data = await fetchWithTimeout<MediaItem[]>(`${API_BASE}/items`);
    return data;
  } catch {
    return [];
  }
}

// ============================================================================
// Cache Management
// ============================================================================

export function invalidateCache(key?: string): void {
  clearCache(key);
}

export async function getCacheInfo() {
  const keys = Array.from(cache.keys());
  const sizes: Record<string, number> = {};
  keys.forEach(key => {
    const entry = cache.get(key);
    sizes[key] = entry ? JSON.stringify(entry.data).length : 0;
  });
  return { keys, sizes };
}

// Auto-refresh helper
export function createAutoRefresh<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  onUpdate: (data: T) => void,
  onError?: (error: Error) => void
): () => void {
  let cancelled = false;
  
  const run = async () => {
    if (cancelled) return;
    try {
      const data = await fetcher();
      if (!cancelled) onUpdate(data);
    } catch (error) {
      if (!cancelled && onError) onError(error instanceof Error ? error : new Error(String(error)));
    }
    if (!cancelled) setTimeout(run, intervalMs);
  };
  
  run();
  
  return () => { cancelled = true; };
}
