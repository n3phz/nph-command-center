/**
 * NPH Command Center - Alert List Component
 * 
 * Full-page alert list with filtering and pagination.
 */

import { useState, useMemo } from 'react';
import { Alert, AlertSeverity, AlertStatus } from '../../types/infrastructure';
import './AlertList.css';

interface AlertListProps {
  alerts: Alert[];
}

export function AlertList({ alerts }: AlertListProps) {
  const [severityFilter, setSeverityFilter] = useState<AlertSeverity[]>([]);
  const [statusFilter, setStatusFilter] = useState<AlertStatus[]>([]);
  const [searchQuery, setSearchQuery] = useState('');

  const filteredAlerts = useMemo(() => {
    return alerts.filter(alert => {
      if (severityFilter.length && !severityFilter.includes(alert.severity)) return false;
      if (statusFilter.length && !statusFilter.includes(alert.status)) return false;
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!alert.title.toLowerCase().includes(query) && 
            !alert.message.toLowerCase().includes(query) &&
            !alert.source.toLowerCase().includes(query)) {
          return false;
        }
      }
      return true;
    });
  }, [alerts, severityFilter, statusFilter, searchQuery]);

  const sortedAlerts = useMemo(() => {
    return [...filteredAlerts].sort((a, b) => {
      const severityOrder = { CRITICAL: 0, WARNING: 1, INFO: 2 };
      const severityDiff = severityOrder[a.severity] - severityOrder[b.severity];
      if (severityDiff !== 0) return severityDiff;
      const statusOrder = { ACTIVE: 0, ACKNOWLEDGED: 1, RESOLVED: 2 };
      const statusDiff = statusOrder[a.status] - statusOrder[b.status];
      if (statusDiff !== 0) return statusDiff;
      return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
    });
  }, [filteredAlerts]);

  return (
    <div className="alert-list-page">
      <div className="page-header">
        <h1>Alerts</h1>
        <div className="alert-stats">
          <span className="stat critical">{alerts.filter(a => a.severity === 'CRITICAL' && a.status === 'ACTIVE').length} Critical</span>
          <span className="stat warning">{alerts.filter(a => a.severity === 'WARNING' && a.status === 'ACTIVE').length} Warning</span>
          <span className="stat info">{alerts.filter(a => a.severity === 'INFO' && a.status === 'ACTIVE').length} Info</span>
        </div>
      </div>

      <div className="alert-filters">
        <div className="filter-group">
          <input
            type="text"
            placeholder="Search alerts..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="filter-search"
          />
        </div>
        
        <div className="filter-group">
          <label>Severity</label>
          <div className="filter-chips">
            {(['CRITICAL', 'WARNING', 'INFO'] as AlertSeverity[]).map(sev => (
              <button
                key={sev}
                className={`filter-chip ${severityFilter.includes(sev) ? 'active' : ''} severity-${sev.toLowerCase()}`}
                onClick={() => setSeverityFilter(prev => 
                  prev.includes(sev) ? prev.filter(s => s !== sev) : [...prev, sev]
                )}
              >
                {sev}
              </button>
            ))}
          </div>
        </div>

        <div className="filter-group">
          <label>Status</label>
          <div className="filter-chips">
            {(['ACTIVE', 'ACKNOWLEDGED', 'RESOLVED'] as AlertStatus[]).map(stat => (
              <button
                key={stat}
                className={`filter-chip ${statusFilter.includes(stat) ? 'active' : ''} status-${stat.toLowerCase()}`}
                onClick={() => setStatusFilter(prev => 
                  prev.includes(stat) ? prev.filter(s => s !== stat) : [...prev, stat]
                )}
              >
                {stat}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="alert-list">
        {sortedAlerts.length === 0 ? (
          <div className="empty-state">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
            <h3>No alerts found</h3>
            <p>{alerts.length === 0 ? 'No alerts in the system' : 'Try adjusting your filters'}</p>
          </div>
        ) : (
          sortedAlerts.map(alert => (
            <article key={alert.id} className={`alert-row severity-${alert.severity.toLowerCase()} status-${alert.status.toLowerCase()}`}>
              <div className="alert-severity">
                <span className="severity-dot" />
                <span className="severity-label">{alert.severity}</span>
              </div>
              <div className="alert-content">
                <div className="alert-header">
                  <h3 className="alert-title">{alert.title}</h3>
                  <div className="alert-badges">
                    <span className={`status-badge ${alert.status.toLowerCase()}`}>{alert.status}</span>
                    <span className="category-badge">{alert.category}</span>
                  </div>
                </div>
                <p className="alert-message">{alert.message}</p>
                <div className="alert-meta">
                  <span className="alert-source">{alert.source}</span>
                  <time className="alert-time" dateTime={alert.timestamp}>
                    {formatRelativeTime(alert.timestamp)}
                  </time>
                </div>
              </div>
              <div className="alert-actions">
                {alert.actionUrl && (
                  <a href={alert.actionUrl} target="_blank" rel="noopener noreferrer" className="btn-secondary">
                    {alert.actionLabel || 'View'}
                  </a>
                )}
                {alert.status === 'ACTIVE' && (
                  <button className="btn-secondary" onClick={() => acknowledgeAlert(alert.id)}>
                    Acknowledge
                  </button>
                )}
                {alert.status === 'ACKNOWLEDGED' && (
                  <button className="btn-primary" onClick={() => resolveAlert(alert.id)}>
                    Resolve
                  </button>
                )}
              </div>
            </article>
          ))
        )}
      </div>
    </div>
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

function acknowledgeAlert(id: string) {
  console.log('Acknowledge alert:', id);
}

function resolveAlert(id: string) {
  console.log('Resolve alert:', id);
}
