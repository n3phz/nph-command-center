/**
 * NPH Command Center - Sidebar Navigation
 * 
 * Collapsible sidebar with navigation sections and items.
 */

import { NavLink, useLocation } from 'react-router-dom';
import './Sidebar.css';

interface NavItem {
  label: string;
  path: string;
  icon: string;
  badge?: string | number;
  disabled?: boolean;
}

interface NavSection {
  id: string;
  label: string;
  items: NavItem[];
}

interface SidebarProps {
  open: boolean;
  onToggle: () => void;
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

export function Sidebar({ open, onToggle }: SidebarProps) {
  const location = useLocation();

  return (
    <aside className={`sidebar ${open ? 'open' : 'collapsed'}`} role="navigation" aria-label="Main navigation">
      <div className="sidebar-header">
        {open && (
          <div className="sidebar-brand">
            <span className="brand-icon">🎯</span>
            <span className="brand-text">NPH Command Center</span>
          </div>
        )}
        <button 
          className="sidebar-toggle" 
          onClick={onToggle}
          aria-label={open ? 'Collapse sidebar' : 'Expand sidebar'}
          aria-expanded={open}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            {open ? (
              <path d="M15 18l-6-6 6-6" />
            ) : (
              <path d="M9 18l6-6-6-6" />
            )}
          </svg>
        </button>
      </div>

      <nav className="sidebar-nav" aria-label="Navigation sections">
        {SECTIONS.map(section => (
          <div key={section.id} className="nav-section">
            {open && (
              <div className="nav-section-header">
                <span className="nav-section-label">{section.label}</span>
              </div>
            )}
            <ul className="nav-items" role="list">
              {section.items.map(item => (
                <li key={item.path} className="nav-item">
                  <NavLink
                    to={item.path}
                    className={({ isActive }) => 
                      `nav-link ${isActive ? 'active' : ''} ${item.disabled ? 'disabled' : ''}`
                    }
                    aria-current={location.pathname === item.path ? 'page' : undefined}
                    title={open ? undefined : item.label}
                  >
                    <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                    {open && (
                      <>
                        <span className="nav-label">{item.label}</span>
                        {item.badge && (
                          <span className="nav-badge">{item.badge}</span>
                        )}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {open && (
        <div className="sidebar-footer">
          <div className="sidebar-status">
            <span className="status-indicator" data-status="healthy" />
            <span className="status-text">All Systems Operational</span>
          </div>
          <div className="sidebar-version">v1.0.0</div>
        </div>
      )}
    </aside>
  );
}
