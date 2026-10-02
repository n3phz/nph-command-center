/**
 * NPH Command Center - Settings Page
 * 
 * Application settings and configuration.
 */

import './Settings.css';

export function Settings() {
  return (
    <div className="settings-page">
      <header className="page-header">
        <h1>Settings</h1>
        <p className="page-subtitle">Configure NPH Command Center</p>
      </header>

      <div className="settings-sections">
        <section className="settings-section">
          <h2>General</h2>
          <div className="setting-row">
            <div className="setting-info">
              <h3>Auto Refresh</h3>
              <p>Automatically refresh dashboard data</p>
            </div>
            <label className="toggle">
              <input type="checkbox" defaultChecked />
              <span className="toggle-slider" />
            </label>
          </div>
          <div className="setting-row">
            <div className="setting-info">
              <h3>Refresh Interval</h3>
              <p>How often to poll for updates</p>
            </div>
            <select className="setting-select">
              <option value="30">30 seconds</option>
              <option value="60">60 seconds</option>
              <option value="120">2 minutes</option>
              <option value="300">5 minutes</option>
            </select>
          </div>
          <div className="setting-row">
            <div className="setting-info">
              <h3>Theme</h3>
              <p>Color scheme preference</p>
            </div>
            <select className="setting-select">
              <option value="dark">Dark</option>
              <option value="system">System</option>
            </select>
          </div>
        </section>

        <section className="settings-section">
          <h2>Notifications</h2>
          <div className="setting-row">
            <div className="setting-info">
              <h3>Critical Alerts</h3>
              <p>Notify on critical system alerts</p>
            </div>
            <label className="toggle">
              <input type="checkbox" defaultChecked={true} />
              <span className="toggle-slider" />
            </label>
          </div>
          <div className="setting-row">
            <div className="setting-info">
              <h3>Warning Alerts</h3>
              <p>Notify on warning level alerts</p>
            </div>
            <label className="toggle">
              <input type="checkbox" defaultChecked={true} />
              <span className="toggle-slider" />
            </label>
          </div>
          <div className="setting-row">
            <div className="setting-info">
              <h3>Info Alerts</h3>
              <p>Notify on informational alerts</p>
            </div>
            <label className="toggle">
              <input type="checkbox" />
              <span className="toggle-slider" />
            </label>
          </div>
        </section>

        <section className="settings-section">
          <h2>Data Sources</h2>
          <p className="section-description">Configure API endpoints for infrastructure data</p>
          <div className="setting-row">
            <div className="setting-info">
              <h3>Backend API</h3>
              <p>Base URL for the command center API</p>
            </div>
            <input type="text" className="setting-input" value="/api" readOnly />
          </div>
          <div className="setting-row">
            <div className="setting-info">
              <h3>Health Check Timeout</h3>
              <p>Timeout for service health checks</p>
            </div>
            <input type="number" className="setting-input" value="5000" min="1000" max="30000" step="1000" />
          </div>
        </section>

        <section className="settings-section">
          <h2>About</h2>
          <div className="about-info">
            <div className="about-item">
              <span className="about-label">Version</span>
              <span className="about-value">1.0.0</span>
            </div>
            <div className="about-item">
              <span className="about-label">Build</span>
              <span className="about-value">Production</span>
            </div>
            <div className="about-item">
              <span className="about-label">Framework</span>
              <span className="about-value">React + TypeScript + Vite</span>
            </div>
            <div className="about-item">
              <span className="about-label">Backend</span>
              <span className="about-value">FastAPI + Python</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
