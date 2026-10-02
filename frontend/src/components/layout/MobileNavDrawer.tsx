/**
 * NPH Command Center - Mobile Navigation Drawer
 * 
 * Slide-out navigation for mobile/tablet views.
 */

import { NavLink, useLocation } from 'react-router-dom';
import './MobileNavDrawer.css';

interface NavItem {
  label: string;
  path: string;
  icon: string;
  disabled?: boolean;
}

interface NavSection {
  id: string;
  label: string;
  items: NavItem[];
}

interface MobileNavDrawerProps {
  open: boolean;
  onClose: () => void;
}

const SECTIONS: NavSection[] = [
  {
    id: 'overview',
    label: 'OVERVIEW',
    items: [
      { label: 'Command Center', path: '/', icon: '🎯' },
      { label: 'Activity', path: '/activity', icon: '📋' },
      { label: 'Alerts', path: '/alerts', icon: '⚠️' },
    ],
  },
  {
    id: 'infrastructure',
    label: 'INFRASTRUCTURE',
    items: [
      { label: 'Services', path: '/services', icon: '⚙️' },
      { label: 'Hosts', path: '/hosts', icon: '🖥️' },
      { label: 'Storage', path: '/storage', icon: '💾' },
      { label: 'Network', path: '/network', icon: '🌐' },
    ],
  },
  {
    id: 'ai',
    label: 'AI',
    items: [
      { label: 'AI Gateway', path: '/ai', icon: '🤖' },
      { label: 'Models', path: '/ai/models', icon: '🧠' },
      { label: 'Providers', path: '/ai/providers', icon: '🔌' },
      { label: 'Usage', path: '/ai/usage', icon: '📊' },
    ],
  },
  {
    id: 'projects',
    label: 'PROJECTS',
    items: [
      { label: 'Projects', path: '/projects', icon: '📁' },
      { label: 'Deployments', path: '/deployments', icon: '🚀' },
      { label: 'Roadmap', path: '/roadmap', icon: '🗺️' },
    ],
  },
  {
    id: 'system',
    label: 'SYSTEM',
    items: [
      { label: 'Settings', path: '/settings', icon: '⚙️' },
      { label: 'About', path: '/about', icon: 'ℹ️' },
    ],
  },
];

export function MobileNavDrawer({ open, onClose }: MobileNavDrawerProps) {
  const location = useLocation();

  if (!open) return null;

  return (
    <>
      <div className="mobile-nav-overlay" onClick={onClose} aria-hidden="true" />
      <aside className="mobile-nav-drawer" role="navigation" aria-label="Mobile navigation">
        <div className="mobile-nav-header">
          <div className="mobile-nav-brand">
            <span className="brand-icon">🎯</span>
            <span className="brand-text">NPH Command Center</span>
          </div>
          <button 
            className="mobile-nav-close"
            onClick={onClose}
            aria-label="Close navigation"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <nav className="mobile-nav-content">
          {SECTIONS.map(section => (
            <div key={section.id} className="mobile-nav-section">
              <div className="mobile-nav-section-header">{section.label}</div>
              <ul className="mobile-nav-items" role="list">
                {section.items.map(item => (
                  <li key={item.path} className="mobile-nav-item">
                    <NavLink
                      to={item.path}
                      className={({ isActive }) => 
                        `mobile-nav-link ${isActive ? 'active' : ''} ${item.disabled ? 'disabled' : ''}`
                      }
                      onClick={onClose}
                      aria-current={location.pathname === item.path ? 'page' : undefined}
                    >
                      <span className="mobile-nav-icon" aria-hidden="true">{item.icon}</span>
                      <span className="mobile-nav-label">{item.label}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="mobile-nav-footer">
          <div className="mobile-nav-status">
            <span className="status-indicator" data-status="healthy" />
            <span className="status-text">All Systems Operational</span>
          </div>
          <div className="mobile-nav-version">v1.0.0</div>
        </div>
      </aside>
    </>
  );
}
