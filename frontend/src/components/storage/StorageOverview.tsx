/**
 * NPH Command Center - Storage Overview Component
 * 
 * Displays storage utilization across all locations.
 */

import { StorageOverview, StorageLocation } from '../../types/infrastructure';
import './StorageOverview.css';

interface StorageOverviewProps {
  storage: StorageOverview | null;
}

export function StorageOverviewComponent({ storage }: StorageOverviewProps) {
  if (!storage || storage.total === 0) {
    return (
      <div className="storage-overview empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
            <line x1="12" y1="22.08" x2="12" y2="12" />
          </svg>
          <span>Storage data unavailable</span>
          <p>Configure storage monitoring to see utilization</p>
        </div>
      </div>
    );
  }

  const thresholdColor = {
    normal: 'var(--status-healthy)',
    watch: 'var(--status-warning)',
    warning: 'var(--status-warning)',
    critical: 'var(--status-critical)',
  };

  const overallColor = thresholdColor[storage.overallThreshold] || thresholdColor.normal;

  return (
    <div className="storage-overview">
      {/* Overall Usage */}
      <div className="storage-summary" style={{ '--threshold-color': overallColor } as React.CSSProperties}>
        <div className="usage-circle">
          <svg className="usage-svg" viewBox="0 0 100 100">
            <circle 
              className="usage-bg" 
              cx="50" cy="50" r="45" 
              stroke="var(--border-primary)" 
              strokeWidth="8" 
              fill="none" 
            />
            <circle 
              className="usage-progress" 
              cx="50" cy="50" r="45" 
              stroke="var(--threshold-color)" 
              strokeWidth="8" 
              fill="none" 
              strokeDasharray={282.74}
              strokeDashoffset={282.74 * (1 - storage.usagePercent / 100)}
              strokeLinecap="round"
              style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%' }}
            />
          </svg>
          <div className="usage-text">
            <span className="usage-percent">{storage.usagePercent.toFixed(1)}%</span>
            <span className="usage-label">Used</span>
          </div>
        </div>
        
        <div className="usage-stats">
          <div className="stat">
            <span className="stat-value">{formatBytes(storage.used)}</span>
            <span className="stat-label">Used</span>
          </div>
          <div className="stat">
            <span className="stat-value">{formatBytes(storage.available)}</span>
            <span className="stat-label">Available</span>
          </div>
          <div className="stat">
            <span className="stat-value">{formatBytes(storage.total)}</span>
            <span className="stat-label">Total</span>
          </div>
        </div>
      </div>

      {/* Storage Locations */}
      {storage.locations.length > 0 && (
        <div className="storage-locations">
          <h4 className="locations-title">Storage Locations ({storage.locations.length})</h4>
          <div className="locations-grid">
            {storage.locations.map(location => (
              <StorageLocationCard key={location.id} location={location} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StorageLocationCard({ location }: { location: StorageLocation }) {
  const thresholdColor = {
    normal: 'var(--status-healthy)',
    watch: 'var(--status-warning)',
    warning: 'var(--status-warning)',
    critical: 'var(--status-critical)',
  };

  const color = thresholdColor[location.status] || thresholdColor.normal;

  return (
    <article className="location-card" style={{ '--location-color': color } as React.CSSProperties}>
      <div className="location-header">
        <div className="location-info">
          <h4 className="location-name">{location.name}</h4>
          <div className="location-meta">
            <span className="location-host">{location.host}</span>
            <span className="location-type">{location.type}</span>
          </div>
        </div>
        <span className="location-status" style={{ backgroundColor: color }}>
          {location.status}
        </span>
      </div>

      <div className="location-usage">
        <div className="usage-bar">
          <div 
            className="usage-bar-fill" 
            style={{ width: `${location.utilizationPercent}%`, backgroundColor: color }}
          />
        </div>
        <div className="usage-details">
          <span>{formatBytes(location.used)} / {formatBytes(location.total)}</span>
          <span>{location.utilizationPercent.toFixed(1)}%</span>
        </div>
      </div>

      <div className="location-footer">
        <span className="location-path">{location.path}</span>
        <time className="location-last-check" dateTime={location.lastCheck}>
          {formatRelativeTime(location.lastCheck)}
        </time>
      </div>
    </article>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}
