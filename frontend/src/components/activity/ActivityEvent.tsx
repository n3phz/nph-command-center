/**
 * NPH Command Center - Activity Event Component
 * 
 * Individual activity event display.
 */

import { ActivityEvent } from '../../types/infrastructure';
import './ActivityEvent.css';

interface ActivityEventProps {
  event: ActivityEvent;
  isLast?: boolean;
}

const CATEGORY_ICONS: Record<string, string> = {
  deployment: '🚀',
  git: '📝',
  service: '⚙️',
  alert: '⚠️',
  infrastructure: '🖥️',
  project: '📁',
  ai: '🤖',
  DEPLOYMENT: '🚀',
  AI: '🤖',
  INFRA: '🖥️',
  PROJECT: '📁',
  SECURITY: '🔐',
  STORAGE: '💾',
  NETWORK: '🌐',
  OTHER: '📦',
};

const SEVERITY_COLORS: Record<string, string> = {
  success: 'var(--status-healthy)',
  warning: 'var(--status-warning)',
  error: 'var(--status-critical)',
  info: 'var(--accent-primary)',
  CRITICAL: 'var(--status-critical)',
  WARNING: 'var(--status-warning)',
  INFO: 'var(--accent-primary)',
};

export function ActivityEventComponent({ event, isLast }: ActivityEventProps) {
  const icon = CATEGORY_ICONS[event.category] || '📦';
  const severityColor = SEVERITY_COLORS[event.severity] || SEVERITY_COLORS.info;

  return (
    <article className={`activity-event severity-${event.severity.toLowerCase()}`} style={{ '--severity-color': severityColor } as React.CSSProperties}>
      <div className="activity-timeline">
        <div className="activity-dot" style={{ backgroundColor: severityColor }} />
        {!isLast && <div className="activity-line" />}
      </div>
      
      <div className="activity-content">
        <div className="activity-header">
          <span className="activity-icon" aria-hidden="true">{icon}</span>
          <div className="activity-info">
            <div className="activity-title-row">
              <h4 className="activity-title">{event.title}</h4>
              <span className="activity-category">{event.category}</span>
            </div>
            <div className="activity-source-row">
              <span className="activity-source">{event.source}</span>
              <time className="activity-time" dateTime={event.timestamp}>
                {formatRelativeTime(event.timestamp)}
              </time>
            </div>
          </div>
        </div>
        
        <p className="activity-message">{event.description || event.message}</p>
        
        {event.url && (
          <a href={event.url} target="_blank" rel="noopener noreferrer" className="activity-link">
            View details
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </a>
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
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}
