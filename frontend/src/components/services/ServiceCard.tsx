/**
 * NPH Command Center - Service Card Component
 * 
 * Compact service display with status, category, and quick actions.
 */

import { Service } from '../../types/infrastructure';
import './ServiceCard.css';

interface ServiceCardProps {
  service: Service;
  compact?: boolean;
}

export function ServiceCard({ service, compact = false }: ServiceCardProps) {
  const statusConfig = {
    healthy: { label: 'Healthy', color: 'var(--status-healthy)' },
    degraded: { label: 'Degraded', color: 'var(--status-warning)' },
    down: { label: 'Down', color: 'var(--status-critical)' },
    unknown: { label: 'Unknown', color: 'var(--status-unknown)' },
    discovered: { label: 'Discovered', color: 'var(--status-unknown)' },
  } as const;

  const config = statusConfig[service.status] || statusConfig.unknown;

  if (compact) {
    return (
      <div className="service-card compact" title={service.description}>
        <div className="service-status-dot" style={{ backgroundColor: config.color }} />
        <div className="service-info">
          <div className="service-name">{service.name}</div>
          <div className="service-meta">
            <span className="service-host">{service.host}</span>
            <span className="service-status" style={{ color: config.color }}>{config.label}</span>
          </div>
        </div>
        {service.url && (
          <a href={service.url} target="_blank" rel="noopener noreferrer" className="service-link" aria-label={`Open ${service.name}`}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </a>
        )}
      </div>
    );
  }

  return (
    <article className="service-card">
      <div className="service-header">
        <div className="service-identity">
          <span className="service-status-dot" style={{ backgroundColor: config.color }} />
          <div>
            <h3 className="service-name">{service.name}</h3>
            <span className="service-category">{service.category}</span>
          </div>
        </div>
        <span className="service-status-badge" style={{ backgroundColor: config.color }}>
          {config.label}
        </span>
      </div>

      <div className="service-details">
        {service.description && (
          <p className="service-description">{service.description}</p>
        )}
        
        <div className="service-meta-grid">
          <div className="meta-item">
            <span className="meta-label">Host</span>
            <span className="meta-value">{service.host}</span>
          </div>
          {service.url && (
            <div className="meta-item">
              <span className="meta-label">URL</span>
              <a href={service.url} target="_blank" rel="noopener noreferrer" className="meta-value link">
                {new URL(service.url).hostname}
              </a>
            </div>
          )}
          {service.version && (
            <div className="meta-item">
              <span className="meta-label">Version</span>
              <span className="meta-value">{service.version}</span>
            </div>
          )}
          {service.uptime && (
            <div className="meta-item">
              <span className="meta-label">Uptime</span>
              <span className="meta-value">{service.uptime}</span>
            </div>
          )}
        </div>

        <div className="service-footer">
          <time className="last-check" dateTime={service.lastCheck}>
            Last checked: {formatRelativeTime(service.lastCheck)}
          </time>
          {service.url && (
            <a href={service.url} target="_blank" rel="noopener noreferrer" className="btn-secondary">
              Open
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
          )}
        </div>
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
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}
