/**
 * NPH Command Center - Attention Required Component
 * 
 * Displays critical alerts and issues that need attention.
 */

import { Alert } from '../../types/infrastructure';
import './AttentionRequired.css';

interface AttentionRequiredProps {
  alerts: Alert[];
  maxItems?: number;
}

export function AttentionRequired({ alerts, maxItems = 5 }: AttentionRequiredProps) {
  const activeAlerts = alerts.filter(a => a.status === 'ACTIVE');
  const sortedAlerts = [...activeAlerts].sort((a, b) => {
    const severityOrder = { CRITICAL: 0, WARNING: 1, INFO: 2 };
    return severityOrder[a.severity] - severityOrder[b.severity];
  });

  const displayAlerts = sortedAlerts.slice(0, maxItems);

  if (!displayAlerts.length) {
    return (
      <div className="attention-required empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
          <span>All systems operational</span>
          <p>No active alerts requiring attention</p>
        </div>
      </div>
    );
  }

  return (
    <div className="attention-required">
      <div className="attention-header">
        <h2 className="attention-title">Attention Required</h2>
        <span className="attention-count">{displayAlerts.length} active</span>
      </div>
      
      <div className="alert-list" role="list" aria-label="Active alerts">
        {displayAlerts.map(alert => (
          <article key={alert.id} className={`alert-item severity-${alert.severity.toLowerCase()}`} role="listitem">
            <div className="alert-severity" aria-label={`Severity: ${alert.severity}`}>
              <span className="severity-dot" />
            </div>
            
            <div className="alert-content">
              <div className="alert-header">
                <h3 className="alert-title">{alert.title}</h3>
                <time className="alert-time" dateTime={alert.timestamp}>
                  {formatRelativeTime(alert.timestamp)}
                </time>
              </div>
              
              <p className="alert-message">{alert.message}</p>
              
              <div className="alert-meta">
                <span className="alert-source">{alert.source}</span>
                <span className="alert-category">{alert.category}</span>
              </div>
            </div>
            
            {alert.actionUrl && (
              <a 
                href={alert.actionUrl} 
                className="alert-action"
                target={alert.actionUrl.startsWith('http') ? '_blank' : '_self'}
                rel={alert.actionUrl.startsWith('http') ? 'noopener noreferrer' : undefined}
              >
                {alert.actionLabel || 'View Details'}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12h14M12 5l7 7-7 7" />
                </svg>
              </a>
            )}
          </article>
        ))}
      </div>
      
      {sortedAlerts.length > maxItems && (
        <div className="attention-more">
          <span>+{sortedAlerts.length - maxItems} more alerts</span>
          <a href="/alerts" className="view-all-link">View all</a>
        </div>
      )}
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
