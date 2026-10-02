/**
 * NPH Command Center - About Page
 * 
 * Information about the application.
 */

import './About.css';

export function About() {
  return (
    <div className="about-page">
      <header className="page-header">
        <h1>About</h1>
        <p className="page-subtitle">NPH Command Center v1.0.0</p>
      </header>

      <div className="about-content">
        <section className="about-section">
          <h2>Overview</h2>
          <p>
            NPH Command Center is a premium infrastructure dashboard for the NPH ecosystem.
            It provides a unified operational view of services, hosts, storage, AI infrastructure,
            projects, and alerts across the entire NPH infrastructure.
          </p>
          <p>
            Built with a dark-first, technical aesthetic inspired by modern observability tooling
            and mission control interfaces. Designed for high information density without clutter.
          </p>
        </section>

        <section className="about-section">
          <h2>Features</h2>
          <ul className="feature-list">
            <li>
              <span className="feature-icon">🎯</span>
              <div>
                <h3>System Status</h3>
                <p>Real-time health overview with service counts, uptime, and status indicators</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">📊</span>
              <div>
                <h3>Key Metrics</h3>
                <p>Infrastructure, AI, and project metrics with status thresholds</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">⚠️</span>
              <div>
                <h3>Attention Required</h3>
                <p>Automated alert detection with severity levels and actionable links</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">⚙️</span>
              <div>
                <h3>Service Inventory</h3>
                <p>Categorized services with health checks, URLs, and direct access</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">🖥️</span>
              <div>
                <h3>Host Infrastructure</h3>
                <p>Host metrics including CPU, memory, uptime, and running services</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">💾</span>
              <div>
                <h3>Storage Overview</h3>
                <p>Utilization across all locations with threshold-based warnings</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">🤖</span>
              <div>
                <h3>AI Command Center</h3>
                <p>Model routing, provider fallback chains, and gateway status</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">📁</span>
              <div>
                <h3>Project Tracking</h3>
                <p>Repository status, deployments, technology stack, and attention items</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">📋</span>
              <div>
                <h3>Activity Feed</h3>
                <p>Unified timeline of deployments, infrastructure events, and changes</p>
              </div>
            </li>
            <li>
              <span className="feature-icon">🔍</span>
              <div>
                <h3>Command Palette</h3>
                <p>Global search (⌘K) across services, hosts, projects, alerts, and activity</p>
              </div>
            </li>
          </ul>
        </section>

        <section className="about-section">
          <h2>Technology Stack</h2>
          <div className="tech-grid">
            <div className="tech-item">
              <span className="tech-label">Frontend</span>
              <span className="tech-value">React 18, TypeScript, Vite</span>
            </div>
            <div className="tech-item">
              <span className="tech-label">Routing</span>
              <span className="tech-value">React Router v6</span>
            </div>
            <div className="tech-item">
              <span className="tech-label">Styling</span>
              <span className="tech-value">CSS Variables, CSS Grid/Flexbox</span>
            </div>
            <div className="tech-item">
              <span className="tech-label">Backend</span>
              <span className="tech-value">FastAPI, Python 3.11</span>
            </div>
            <div className="tech-item">
              <span className="tech-label">Database</span>
              <span className="tech-value">SQLite (embedded)</span>
            </div>
            <div className="tech-item">
              <span className="tech-label">Deployment</span>
              <span className="tech-value">Docker, Traefik</span>
            </div>
          </div>
        </section>

        <section className="about-section">
          <h2>Data Sources</h2>
          <p>The Command Center aggregates data from the NPH infrastructure:</p>
          <ul className="data-source-list">
            <li><strong>Service Health:</strong> Backend health check endpoints</li>
            <li><strong>Host Metrics:</strong> System monitoring agents</li>
            <li><strong>Storage:</strong> NAS and distributed storage APIs</li>
            <li><strong>AI Gateway:</strong> FreeLLMAPI / LiteLLM provider status</li>
            <li><strong>Projects:</strong> Git repository and deployment metadata</li>
            <li><strong>Alerts:</strong> Infrastructure monitoring and custom rules</li>
            <li><strong>Activity:</strong> Deployment logs, git commits, and system events</li>
          </ul>
        </section>

        <section className="about-section">
          <h2>Keyboard Shortcuts</h2>
          <div className="shortcuts-grid">
            <div className="shortcut"><kbd>⌘K</kbd><span>Open command palette</span></div>
            <div className="shortcut"><kbd>/</kbd><span>Quick search</span></div>
            <div className="shortcut"><kbd>Esc</kbd><span>Close modals/dropdowns</span></div>
            <div className="shortcut"><kbd>↑</kbd><kbd>↓</kbd><span>Navigate results</span></div>
            <div className="shortcut"><kbd>Enter</kbd><span>Select/Open</span></div>
          </div>
        </section>
      </div>

      <footer className="about-footer">
        <p>NPH Command Center — One cockpit for the NPH ecosystem.</p>
        <p className="copyright">Built with precision for infrastructure operators.</p>
      </footer>
    </div>
  );
}
