/**
 * NPH Command Center - Metric Card Component
 * 
 * Compact metric display with status indicator, trend, and metadata.
 */

import './MetricCard.css';

interface MetricCardProps {
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

export function MetricCard({
  label,
  value,
  unit,
  status,
  trend,
  description,
  lastUpdated,
  source,
  onClick,
}: Omit<MetricCardProps, 'id'>) {
  const statusColor = STATUS_COLORS[status];
  const statusLabel = STATUS_LABELS[status];

  return (
    <article 
      className={`metric-card ${onClick ? 'clickable' : ''} status-${status}`}
      onClick={onClick}
      role={onClick ? 'button' : 'article'}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); }} : undefined}
      aria-label={`${label}: ${value}${unit ? ' ' + unit : ''}, status ${statusLabel}`}
    >
      <div className="metric-header">
        <div className="metric-label">{label}</div>
        <div className="metric-status-indicator" style={{ backgroundColor: statusColor }} 
             title={`${statusLabel} (${status})`} />
      </div>
      
      <div className="metric-value-wrapper">
        <div className="metric-value">{value}</div>
        {unit && <div className="metric-unit">{unit}</div>}
      </div>
      
      {trend && (
        <div className="metric-trend trend-{trend}" aria-label={`Trend: ${trend}`}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            {trend === 'up' && <path d="M18 15l-6-6-6 6" />}
            {trend === 'down' && <path d="M6 9l6 6 6-6" />}
            {trend === 'stable' && <path d="M5 12h14" />}
          </svg>
        </div>
      )}
      
      {description && (
        <div className="metric-description" title={description}>
          {description}
        </div>
      )}
      
      <div className="metric-meta">
        {lastUpdated && (
          <time className="metric-last-updated" dateTime={lastUpdated}>
            Updated {formatRelativeTime(lastUpdated)}
          </time>
        )}
        {source && (
          <span className="metric-source">{source}</span>
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
