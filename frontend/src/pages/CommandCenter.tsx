/**
 * NPH Command Center - Main Dashboard Page
 * 
 * Primary operational overview with system status, metrics, alerts, and activity.
 * Now with live SSE updates for real-time card refreshes.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  getInfrastructureSnapshot,
} from '../services/command-center';
import type {
  SystemStatus,
  Service,
  Host,
  StorageOverview,
  AICommandCenter,
  Project,
  Alert,
  QuickAction,
  MediaItem,
} from '../types/infrastructure';
import {
  SystemStatusCard,
  MetricGrid,
  AttentionRequired,
  ServiceInventory,
  QuickActionsPanel,
  AICommandCenterPanel,
  LivePipelineList,
} from '../components';
import { useEventStream } from '../hooks/useEventStream';
import './CommandCenter.css';

export function CommandCenter() {
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [services, setServices] = useState<Service[]>([]);
  const [hosts, setHosts] = useState<Host[]>([]);
  const [storage, setStorage] = useState<StorageOverview | null>(null);
  const [ai, setAI] = useState<AICommandCenter | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [quickActions, setQuickActions] = useState<QuickAction[]>([]);
  const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  // Live SSE connection for real-time updates
  const [liveConnection, setLiveConnection] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('connecting');
  const [liveEventCount, setLiveEventCount] = useState(0);
  const [liveError, setLiveError] = useState<Error | null>(null);
  void liveEventCount;
  void liveError;

  const handleLiveEvent = useCallback((event: any) => {
    setLiveEventCount(prev => prev + 1);
    
    // Handle different event types for live card updates
    const data = event.data;
    const eventType = event.event;
    
    // Update services on service status change
    if (eventType === 'service_status_change') {
      setServices(prev => prev.map(s => 
        s.id === data.service ? { ...s, status: data.status, lastCheck: data.timestamp } : s
      ));
      setSystemStatus(prev => {
        if (!prev) return prev;
        // Recalculate counts based on updated services
        return prev; // Will be recalculated on next poll
      });
    }
    
    // Update media items
    if (data.item_id) {
      setMediaItems(prev => {
        const existing = prev.find(m => m.id === data.item_id || m.correlation_key === data.item_id);
        if (existing) {
          return prev.map(m => 
            (m.id === data.item_id || m.correlation_key === data.item_id) 
              ? { ...m, ...data, last_event_at: data.timestamp || new Date().toISOString() }
              : m
          );
        } else if (eventType === 'item_created') {
          return [...prev, { 
            id: data.item_id,
            correlation_key: data.item_id,
            title: data.title,
            media_type: data.media_type,
            current_state: data.current_state || data.state,
            progress: data.progress,
            current_service: data.current_service,
            season: data.season,
            episode: data.episode,
            event_count: 1,
            last_event_at: data.timestamp || new Date().toISOString(),
          } as MediaItem];
        }
        return prev;
      });
    }
  }, []);

  const handleLiveOpen = useCallback(() => {
    setLiveConnection('connected');
    setLiveError(null);
  }, []);

  const handleLiveError = useCallback((err: Error) => {
    setLiveConnection('error');
    setLiveError(err);
  }, []);

  const handleLiveClose = useCallback(() => {
    setLiveConnection('disconnected');
  }, []);

  const { isConnected: sseConnected } = useEventStream('/api/events/stream', {
    onEvent: handleLiveEvent,
    onOpen: handleLiveOpen,
    onError: handleLiveError,
    onClose: handleLiveClose,
    reconnectInterval: 5000,
  });

  // Sync connection status
  useEffect(() => {
    if (sseConnected && liveConnection !== 'connected') {
      setLiveConnection('connected');
    } else if (!sseConnected && liveConnection === 'connected') {
      setLiveConnection('disconnected');
    }
  }, [sseConnected, liveConnection]);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      const snapshot = await getInfrastructureSnapshot();
      
      setSystemStatus(snapshot.systemStatus);
      setServices(snapshot.services);
      setHosts(snapshot.hosts);
      setStorage(snapshot.storage);
      setAI(snapshot.ai);
      setProjects(snapshot.projects);
      setAlerts(snapshot.alerts);
      setQuickActions(snapshot.quickActions);
      
      // Convert pipeline items to media items for live updates
      if (snapshot.mediaItems) {
        setMediaItems(snapshot.mediaItems);
      }
      
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data');
      setLiveConnection('error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 60000);
    return () => clearInterval(interval);
  }, [loadData]);

  const handleRefresh = () => {
    loadData();
  };

  // Compute metric cards from real data
  const metricCards = useMemo(() => {
    if (!systemStatus || !storage) return [];
    
    const servicesHealthy = systemStatus.healthyCount === systemStatus.totalCount ? 'normal' as const
      : systemStatus.healthyCount > systemStatus.totalCount * 0.7 ? 'watch' as const
      : 'warning' as const;
    const hostsOnline = hosts.filter(h => h.status === 'online').length === hosts.length ? 'normal' as const : 'watch' as const;
    const storageStatus = storage.overallThreshold === 'critical' ? 'critical' as const
      : storage.overallThreshold === 'warning' ? 'warning' as const
      : storage.overallThreshold === 'watch' ? 'watch' as const
      : 'normal' as const;
    
    return [
      {
        id: 'services-healthy',
        label: 'Services Healthy',
        value: `${systemStatus.healthyCount} / ${systemStatus.totalCount}`,
        status: servicesHealthy,
        description: `${systemStatus.degradedCount} degraded, ${systemStatus.unavailableCount} unavailable`,
        lastUpdated: systemStatus.lastChecked,
        source: 'Health Checks',
        liveKey: 'services-healthy',
        liveEnabled: true,
      },
      {
        id: 'hosts-online',
        label: 'Hosts Online',
        value: `${hosts.filter(h => h.status === 'online').length} / ${hosts.length}`,
        status: hostsOnline,
        description: `${hosts.filter(h => h.status === 'offline').length} offline`,
        lastUpdated: new Date().toISOString(),
        source: 'Host Discovery',
        liveKey: 'hosts-online',
        liveEnabled: true,
      },
      {
        id: 'storage-usage',
        label: 'Storage Used',
        value: `${formatBytes(storage.used)} / ${formatBytes(storage.total)}`,
        unit: `${storage.usagePercent.toFixed(1)}%`,
        status: storageStatus,
        description: `${storage.locations.length} locations`,
        lastUpdated: new Date().toISOString(),
        source: 'Storage API',
        liveKey: 'storage-usage',
        liveEnabled: true,
      },
      {
        id: 'active-projects',
        label: 'Active Projects',
        value: projects.filter(p => p.status === 'ACTIVE').length,
        status: 'normal' as const,
        description: `${projects.filter(p => p.status === 'DEVELOPMENT').length} in development`,
        lastUpdated: new Date().toISOString(),
        source: 'Project Registry',
        liveKey: 'active-projects',
        liveEnabled: true,
      },
    ];
  }, [systemStatus, hosts, storage, projects]);

  // AI metrics
  const aiMetrics = useMemo(() => {
    if (!ai) return [];
    
    const gatewayStatus = ai.gatewayStatus === 'healthy' ? 'normal' as const
      : ai.gatewayStatus === 'degraded' ? 'watch' as const
      : 'critical' as const;
    const modelStatus = ai.currentRoute ? 'normal' as const : 'warning' as const;
    const fallbackStatus = ai.fallbackChain.length > 0 ? 'normal' as const : 'watch' as const;
    
    return [
      {
        id: 'ai-gateway',
        label: 'AI Gateway',
        value: ai.gatewayStatus === 'healthy' ? 'Healthy' : ai.gatewayStatus,
        status: gatewayStatus,
        description: `${ai.providers.length} providers configured`,
        lastUpdated: ai.lastUpdated,
        source: 'AI Gateway',
        liveKey: 'ai-gateway',
        liveEnabled: true,
      },
      {
        id: 'ai-model',
        label: 'Default Model',
        value: ai.currentRoute?.model || 'Not configured',
        status: modelStatus,
        description: `Via ${ai.currentRoute?.provider || 'unknown'}`,
        lastUpdated: ai.lastUpdated,
        source: 'AI Gateway',
        liveKey: 'ai-model',
        liveEnabled: true,
      },
      {
        id: 'ai-fallback',
        label: 'Fallback Chain',
        value: `${ai.fallbackChain.length} providers`,
        status: fallbackStatus,
        description: ai.fallbackChain.map(f => f.provider).join(' → '),
        lastUpdated: ai.lastUpdated,
        source: 'AI Gateway',
        liveKey: 'ai-fallback',
        liveEnabled: true,
      },
    ];
  }, [ai]);

  if (loading) {
    return (
      <div className="command-center loading">
        <div className="loading-skeleton">
          <div className="skeleton-card skeleton-system-status" />
          <div className="skeleton-grid">
            <div className="skeleton-card" />
            <div className="skeleton-card" />
            <div className="skeleton-card" />
            <div className="skeleton-card" />
          </div>
          <div className="skeleton-card skeleton-attention" />
          <div className="skeleton-card skeleton-activity" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="command-center error">
        <div className="error-state">
          <h2>Failed to Load Dashboard</h2>
          <p>{error}</p>
          <button onClick={handleRefresh} className="btn-primary">
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Convert media items to pipeline rows for live pipeline list
  const pipelineRows = useMemo(() => {
    return mediaItems
      .filter(item => item.current_state !== 'available' && item.current_state !== 'unknown')
      .map(item => ({
        id: item.correlation_key || item.id,
        title: item.title,
        state: item.current_state,
        progress: item.progress,
        current_service: item.current_service,
        last_event_at: item.last_event_at,
        season: item.season,
        episode: item.episode,
        media_type: item.media_type,
      }));
  }, [mediaItems]);

  return (
    <div className="command-center">
      {/* Live connection status banner */}
      <div className={`live-banner ${liveConnection}`}>
        <span className="live-banner-dot" />
        <span className="live-banner-text">
          {liveConnection === 'connected' 
            ? `LIVE — ${liveEventCount} events received` 
            : liveConnection === 'connecting' 
              ? 'Connecting to live stream...' 
              : liveConnection === 'error' 
                ? `Connection error: ${liveError?.message || 'Unknown error'}`
                : 'Live stream disconnected'}
        </span>
        {liveConnection !== 'connected' && (
          <button className="live-reconnect-btn" onClick={() => window.location.reload()}>
            Reconnect
          </button>
        )}
      </div>

      <section className="section system-status-section" aria-labelledby="system-status-title">
        <SystemStatusCard 
          status={systemStatus}
          lastUpdated={lastUpdated}
          onRefresh={handleRefresh}
        />
      </section>

      <section className="section metrics-section" aria-labelledby="metrics-title">
        <h2 id="metrics-title" className="section-title">Key Metrics</h2>
        <MetricGrid cards={metricCards} />
        
        {aiMetrics.length > 0 && (
          <>
            <h3 className="subsection-title">AI Infrastructure</h3>
            <MetricGrid cards={aiMetrics} />
          </>
        )}
      </section>

      <section className="section attention-section" aria-labelledby="attention-title">
        <AttentionRequired alerts={alerts} />
      </section>

      <div className="main-grid">
        <section className="section services-section" aria-labelledby="services-title">
          <div className="section-header">
            <h2 id="services-title" className="section-title">Service Inventory</h2>
            <Link to="/services" className="section-link">View All</Link>
          </div>
          <ServiceInventory 
            services={services}
            maxItems={8}
          />
        </section>

        <section className="section activity-section" aria-labelledby="activity-title">
          <div className="section-header">
            <h2 id="activity-title" className="section-title">Active Pipeline (Live)</h2>
            <Link to="/activity" className="section-link">View All</Link>
          </div>
          <LivePipelineList 
            initialItems={pipelineRows}
            onItemSelect={(_id) => { /* navigate to item detail */ }}
          />
        </section>
      </div>

      <div className="bottom-grid">
        <section className="section ai-section" aria-labelledby="ai-title">
          <AICommandCenterPanel ai={ai} />
        </section>

        <section className="section quick-actions-section" aria-labelledby="quick-actions-title">
          <div className="section-header">
            <h2 id="quick-actions-title" className="section-title">Quick Actions</h2>
          </div>
          <QuickActionsPanel actions={quickActions} />
        </section>
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}