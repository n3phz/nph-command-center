/**
 * NPH Command Center - Live Metric Card Component
 * 
 * Enhanced metric display with live SSE updates showing real-time status changes.
 */

import { useState, useEffect } from 'react';
import { useEventStream } from '../../hooks/useEventStream';
import './MetricCard.css';

interface LiveMetricCardProps {
  id: string;
  label: string;
  value: string | number;
  unit?: string;
  status: 'normal' | 'watch' | 'warning' | 'critical' | 'unknown';
  trend?: 'up' | 'down' | 'stable';
  description?: string;
  lastUpdated?: string;
  source?: string;
  onClick?: () => void;
  // Live update configuration
  liveKey?: string; // Key to match SSE events
  liveEnabled?: boolean;
}

const STATUS_COLORS = {
  normal: 'var(--status-healthy)',
  watch: 'var(--status-warning)',
  warning: 'var(--status-warning)',
  critical: 'var(--status-critical)',
  unknown: 'var(--status-unknown)',
};

const STATUS_LABELS = {
  normal: 'Normal',
  watch: 'Watch',
  warning: 'Warning',
  critical: 'Critical',
  unknown: 'Unknown',
};

const LIVE_STATE_CONFIG = {
  queued: { label: 'QUEUED', color: 'var(--status-unknown)', pulse: true },
  working: { label: 'WORKING', color: 'var(--accent-primary)', pulse: true },
  progress: { label: 'IN PROGRESS', color: 'var(--accent-primary)', pulse: true },
  success: { label: 'UPDATED', color: 'var(--status-healthy)', pulse: false },
  failed: { label: 'ERROR', color: 'var(--status-critical)', pulse: false },
  retrying: { label: 'RETRYING', color: 'var(--status-warning)', pulse: true },
  fallback: { label: 'FALLBACK', color: '#9c27b0', pulse: true },
} as const;

export function LiveMetricCard({
  label,
  value,
  unit,
  status,
  trend,
  description,
  lastUpdated,
  source,
  onClick,
  liveKey,
  liveEnabled = true,
}: Omit<LiveMetricCardProps, 'id'>) {
  const statusColor = STATUS_COLORS[status];
  const statusLabel = STATUS_LABELS[status];

  const [liveState, setLiveState] = useState<keyof typeof LIVE_STATE_CONFIG | null>(null);
  const [liveValue, setLiveValue] = useState<string | number | null>(null);
  const [liveProgress, setLiveProgress] = useState<number | null>(null);
  const [liveTimestamp, setLiveTimestamp] = useState<string | null>(null);

  const handleEvent = (event: any) => {
    if (!liveKey) return;
    
    const eventData = event.data;
    if (eventData.item_id === liveKey || eventData.metric_id === liveKey) {
      // Update live state based on event type
      switch (event.event) {
        case 'progress_update':
        case 'download_progress':
        case 'download_started':
          setLiveState('progress');
          if (eventData.progress !== undefined) {
            setLiveValue(eventData.progress);
            setLiveProgress(eventData.progress);
          }
          break;
        case 'item_state_change':
        case 'download_completed':
        case 'import_completed':
        case 'available':
          setLiveState('success');
          setLiveValue(eventData.new_state || 'Completed');
          break;
        case 'download_failed':
        case 'import_failed':
        case 'stuck':
          setLiveState('failed');
          setLiveValue('Failed');
          break;
        case 'item_update':
        case 'item_created':
          setLiveState('working');
          if (eventData.progress !== undefined) {
            setLiveValue(eventData.progress);
            setLiveProgress(eventData.progress);
          }
          break;
        default:
          setLiveState('working');
      }
      setLiveTimestamp(eventData.timestamp || new Date().toISOString());
    }
  };

  const { isConnected, eventCount } = useEventStream('/api/events/stream', {
    enabled: liveEnabled && !!liveKey,
    onEvent: handleEvent,
  });

  // Clear live state after a delay
  useEffect(() => {
    if (liveState === 'success' || liveState === 'failed') {
      const timer = setTimeout(() => {
        setLiveState(null);
        setLiveValue(null);
        setLiveProgress(null);
        setLiveTimestamp(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [liveState]);

  const displayValue = liveValue !== null ? liveValue : value;
  const displayProgress = liveProgress !== null ? liveProgress : undefined;
  const isLive = liveState !== null;

  return (
    <article 
      className={`metric-card ${onClick ? 'clickable' : ''} status-${status} ${isLive ? `live-${liveState}` : ''}`}
      onClick={onClick}
      role={onClick ? 'button' : 'article'}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); }} : undefined}
      aria-label={`${label}: ${displayValue}${unit ? ' ' + unit : ''}, status ${statusLabel}${isLive ? `, live: ${LIVE_STATE_CONFIG[liveState!].label}` : ''}`}
    >
      <div className="metric-header">
        <div className="metric-label">{label}</div>
        <div className="metric-status-indicator" style={{ backgroundColor: statusColor }} 
             title={`${statusLabel} (${status})`} />
        {isConnected && (
          <span className="live-connection-dot" title="SSE Connected" />
        )}
      </div>
      
      <div className="metric-value-wrapper">
        <div className="metric-value">{displayValue}</div>
        {unit && <div className="metric-unit">{unit}</div>}
      </div>
      
      {displayProgress !== undefined && (
        <div className="metric-live-progress">
          <div className="progress-bar">
            <div 
              className={`progress-fill ${isLive ? `live-${liveState}` : ''}`} 
              style={{ width: `${displayProgress}%` }} 
            />
            {isLive && liveState === 'progress' && <div className="progress-pulse" />}
          </div>
          <span className="progress-text">{displayProgress}%</span>
        </div>
      )}
      
      {trend && (
        <div className="metric-trend trend-{trend}" aria-label={`Trend: ${trend}`}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            {trend === 'up' && <path d="M18 15l-6-6-6 6" />}
            {trend === 'down' && <path d="M6 9l6 6 6-6" />}
            {trend === 'stable' && <path d="M5 12h14" />}
          </svg>
        </div>
      )}
      
      {isLive && (
        <div className={`metric-live-state live-${liveState}`}>
          <span className="live-state-label">{LIVE_STATE_CONFIG[liveState].label}</span>
          {LIVE_STATE_CONFIG[liveState].pulse && <span className="live-pulse-dot" />}
        </div>
      )}
      
      {description && (
        <div className="metric-description" title={description}>
          {description}
        </div>
      )}
      
      <div className="metric-meta">
        {liveTimestamp && (
          <time className="metric-last-updated live" dateTime={liveTimestamp}>
            Live: {formatRelativeTime(liveTimestamp)}
          </time>
        )}
        {lastUpdated && !liveTimestamp && (
          <time className="metric-last-updated" dateTime={lastUpdated}>
            Updated {formatRelativeTime(lastUpdated)}
          </time>
        )}
        {source && (
          <span className="metric-source">{source}</span>
        )}
        {liveEnabled && liveKey && eventCount > 0 && (
          <span className="metric-event-count" title={`${eventCount} live events received`}>
            📡 {eventCount}
          </span>
        )}
      </div>
    </article>
  );
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return date.toLocaleDateString();
}