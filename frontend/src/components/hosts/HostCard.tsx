/**
 * NPH Command Center - Host Card Component
 * 
 * Compact host display with metrics and status.
 */

import { Host } from '../../types/infrastructure';
import './HostCard.css';

interface HostCardProps {
  host: Host;
}

export function HostCard({ host }: HostCardProps) {
  const statusConfig = {
    online: { label: 'Online', color: 'var(--status-healthy)' },
    offline: { label: 'Offline', color: 'var(--status-critical)' },
    degraded: { label: 'Degraded', color: 'var(--status-warning)' },
    discovered: { label: 'Discovered', color: 'var(--status-unknown)' },
  } as const;

  const config = statusConfig[host.status] || statusConfig.offline;
  const cpuPercent = host.metrics?.cpu ? Math.round((host.metrics.cpu.usage / host.metrics.cpu.cores) * 100) : null;
  const memPercent = host.metrics?.memory ? Math.round(host.metrics.memory.usagePercent) : null;

  return (
    <article className={`host-card ${host.status}`} role="listitem">
      <div className="host-header">
        <div className="host-identity">
          <span className="host-status-dot" style={{ backgroundColor: config.color }} />
          <div>
            <h3 className="host-name">{host.displayName || host.name}</h3>
            <span className="host-hostname">{host.hostname}</span>
          </div>
        </div>
        <span className="host-status-badge" style={{ backgroundColor: config.color }}>
          {config.label}
        </span>
      </div>

      <div className="host-details">
        <div className="host-meta-grid">
          {host.ip && (
            <div className="meta-item">
              <span className="meta-label">IP</span>
              <span className="meta-value">{host.ip}</span>
            </div>
          )}
          {host.tailnetIp && (
            <div className="meta-item">
              <span className="meta-label">Tailnet</span>
              <span className="meta-value">{host.tailnetIp}</span>
            </div>
          )}
          {host.os && (
            <div className="meta-item">
              <span className="meta-label">OS</span>
              <span className="meta-value">{host.os}</span>
            </div>
          )}
          {host.uptime && (
            <div className="meta-item">
              <span className="meta-label">Uptime</span>
              <span className="meta-value">{host.uptime}</span>
            </div>
          )}
        </div>

        {(cpuPercent !== null || memPercent !== null) && (
          <div className="host-metrics">
            {cpuPercent !== null && (
              <div className="metric-bar">
                <div className="metric-bar-label">
                  <span>CPU</span>
                  <span>{cpuPercent}%</span>
                </div>
                <div className="metric-bar-track">
                  <div 
                    className="metric-bar-fill" 
                    style={{ width: `${cpuPercent}%`, backgroundColor: getMetricColor(cpuPercent) }}
                  />
                </div>
              </div>
            )}
            {memPercent !== null && (
              <div className="metric-bar">
                <div className="metric-bar-label">
                  <span>Memory</span>
                  <span>{memPercent}%</span>
                </div>
                <div className="metric-bar-track">
                  <div 
                    className="metric-bar-fill" 
                    style={{ width: `${memPercent}%`, backgroundColor: getMetricColor(memPercent) }}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {host.services && host.services.length > 0 && (
          <div className="host-services">
            <span className="services-label">{host.services.length} services</span>
            <div className="services-tags">
              {host.services.slice(0, 4).map(svc => (
                <span key={svc} className="service-tag">{svc}</span>
              ))}
              {host.services.length > 4 && (
                <span className="service-tag more">+{host.services.length - 4}</span>
              )}
            </div>
          </div>
        )}

        <div className="host-footer">
          <time className="last-check" dateTime={host.lastChecked}>
            {formatRelativeTime(host.lastChecked)}
          </time>
          {host.tags && host.tags.length > 0 && (
            <div className="host-tags">
              {host.tags.map(tag => (
                <span key={tag} className="tag">{tag}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function getMetricColor(percent: number): string {
  if (percent >= 90) return 'var(--status-critical)';
  if (percent >= 75) return 'var(--status-warning)';
  return 'var(--status-healthy)';
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
