import { useState, useRef, useEffect } from 'react';
import './TopBar.css';

interface TopBarProps {
  onMenuClick: () => void;
  onSearchClick: () => void;
  quickActions: any[];
}

export function TopBar({ onMenuClick, onSearchClick, quickActions }: TopBarProps) {
  const quickActionsRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (quickActionsRef.current && !quickActionsRef.current.contains(e.target as Node)) {
        setQuickActionsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // We'll manage quickActionsOpen state
  const [quickActionsOpen, setQuickActionsOpen] = useState(false);

  return (
    <header className="top-bar" role="banner">
      <div className="top-bar-left">
        <button 
          className="top-bar-menu-btn"
          onClick={onMenuClick}
          aria-label="Toggle navigation menu"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12h18M3 6h18M3 18h18" />
          </svg>
        </button>

        <div className="top-bar-search">
          <button
            className="search-trigger"
            onClick={onSearchClick}
            aria-label="Open command palette"
            title="Search (⌘K)"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" />
            </svg>
            <span className="search-placeholder">Search services, hosts, projects...</span>
            <kbd className="search-shortcut">⌘K</kbd>
          </button>
        </div>
      </div>

      <div className="top-bar-center">
        <div className="system-status-badge" id="system-status">
          <span className="status-dot" data-status="unknown" />
          <span className="status-label">NPH SYSTEM STATUS</span>
          <span className="status-value">UNKNOWN</span>
        </div>
      </div>

      <div className="top-bar-right">
        <div className="quick-actions-dropdown" ref={quickActionsRef}>
          <button
            className="quick-actions-trigger"
            onClick={() => setQuickActionsOpen(!quickActionsOpen)}
            aria-expanded={quickActionsOpen}
            aria-haspopup="true"
            aria-label="Quick actions"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12h14" />
            </svg>
            <span>Quick Actions</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>

          {quickActionsOpen && (
            <div className="quick-actions-menu" role="menu">
              <div className="quick-actions-header">
                <span>Quick Actions</span>
                <kbd>⌘K</kbd>
              </div>
              <div className="quick-actions-grid">
                {quickActions.map(action => (
                  <a
                    key={action.id}
                    href={action.url}
                    target={action.external ? '_blank' : '_self'}
                    rel={action.external ? 'noopener noreferrer' : undefined}
                    className="quick-action-item"
                    role="menuitem"
                  >
                    <span className="quick-action-icon">{action.icon}</span>
                    <div className="quick-action-info">
                      <span className="quick-action-label">{action.label}</span>
                      <span className="quick-action-desc">{action.description}</span>
                    </div>
                    {action.external && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2 2V8a2 2 0 0 1 2-2h6" />
                        <polyline points="15 3 21 3 21 9" />
                        <line x1="10" y1="14" x2="21" y2="3" />
                      </svg>
                    )}
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="top-bar-time">
          <span id="current-time" className="time-display">--:--:--</span>
          <span className="time-zone">GMT+1</span>
        </div>
      </div>
    </header>
  );
}