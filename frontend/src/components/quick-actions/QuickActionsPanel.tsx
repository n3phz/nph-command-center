/**
 * NPH Command Center - Quick Actions Panel
 * 
 * Grid of quick action buttons for common tasks.
 */

import { QuickAction } from '../../types/infrastructure';
import './QuickActionsPanel.css';

interface QuickActionsPanelProps {
  actions: QuickAction[];
  columns?: number;
}

export function QuickActionsPanel({ actions, columns = 4 }: QuickActionsPanelProps) {
  if (!actions.length) {
    return (
      <div className="quick-actions-panel empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 5v14M5 12h14" />
          </svg>
          <span>No quick actions configured</span>
        </div>
      </div>
    );
  }

  return (
    <div 
      className="quick-actions-panel"
      style={{ gridTemplateColumns: `repeat(${Math.min(columns, actions.length)}, 1fr)` }}
      role="list"
      aria-label="Quick actions"
    >
      {actions.map(action => (
        <a
          key={action.id}
          href={action.url}
          target={action.external ? '_blank' : '_self'}
          rel={action.external ? 'noopener noreferrer' : undefined}
          className="quick-action-card"
          role="listitem"
        >
          <span className="quick-action-icon" aria-hidden="true">{action.icon}</span>
          <div className="quick-action-content">
            <span className="quick-action-label">{action.label}</span>
            <span className="quick-action-description">{action.description}</span>
          </div>
          {action.external && (
            <svg className="external-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          )}
        </a>
      ))}
    </div>
  );
}
