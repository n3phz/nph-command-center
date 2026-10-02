/**
 * NPH Command Center - AI Command Center Panel
 * 
 * Displays AI gateway status, current model route, and provider fallback chain.
 */

import { AICommandCenter, AIModelRoute, AIProvider, AIModel } from '../../types/infrastructure';
import './AICommandCenterPanel.css';

interface AICommandCenterPanelProps {
  ai: AICommandCenter | null;
}

export function AICommandCenterPanel({ ai }: AICommandCenterPanelProps) {
  if (!ai) {
    return (
      <div className="ai-panel empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z" />
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <span>AI Gateway unavailable</span>
          <p>Configure AI providers to see routing info</p>
        </div>
      </div>
    );
  }

  const currentRoute = ai.currentRoute;

  return (
    <div className="ai-panel">
      <div className="ai-header">
        <h3 className="ai-title">AI Command Center</h3>
        <div className="gateway-status">
          <span className={`status-dot ${ai.gatewayStatus}`} />
          <span className="status-label">{ai.gatewayStatus}</span>
        </div>
      </div>

      {/* Current Route */}
      {currentRoute && (
        <div className="current-route">
          <div className="route-label">Current Route</div>
          <div className="route-visual">
            <div className="route-step primary">
              <div className="step-connector">
                <div className="step-dot" />
              </div>
              <div className="step-content">
                <div className="step-label">PRIMARY</div>
                <div className="step-provider">{currentRoute.provider}</div>
                <div className="step-model">{currentRoute.model}</div>
              </div>
              <span className={`step-status ${currentRoute.status}`} />
            </div>
          </div>
        </div>
      )}

      {/* Fallback Chain */}
      {ai.fallbackChain.length > 0 && (
        <div className="fallback-chain">
          <div className="route-label">Fallback Chain</div>
          <div className="route-visual">
            {ai.fallbackChain.map((route: AIModelRoute, index: number) => (
              <div key={index} className={`route-step fallback step-${index + 1}`}>
                <div className="step-connector">
                  {index < ai.fallbackChain.length - 1 && <div className="step-line" />}
                  <div className="step-dot" />
                </div>
                <div className="step-content">
                  <div className="step-label">{index === 0 ? 'FALLBACK 1' : `FALLBACK ${index + 1}`}</div>
                  <div className="step-provider">{route.provider}</div>
                  <div className="step-model">{route.model}</div>
                </div>
                <span className={`step-status ${route.status}`} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Providers Grid */}
      {ai.providers.length > 0 && (
        <div className="providers-grid">
          <div className="route-label">Providers ({ai.providers.length})</div>
          <div className="providers-list">
            {ai.providers.map((provider: AIProvider) => (
              <div key={provider.id} className={`provider-card ${provider.status}`}>
                <div className="provider-header">
                  <span className="provider-status-dot" />
                  <div>
                    <div className="provider-name">{provider.name}</div>
                    <div className="provider-type">{provider.type}</div>
                  </div>
                  <span className={`provider-status ${provider.status}`}>{provider.status}</span>
                </div>
                {provider.models && provider.models.length > 0 && (
                  <div className="provider-models">
                    {provider.models.slice(0, 3).map((model: AIModel) => (
                      <span key={model.id} className="model-tag">{model.name}</span>
                    ))}
                    {provider.models.length > 3 && (
                      <span className="model-tag more">+{provider.models.length - 3} more</span>
                    )}
                  </div>
                )}
                <div className="provider-meta">
                  <span className="provider-endpoint">{provider.endpoint}</span>
                  <time className="provider-last-check" dateTime={provider.lastChecked}>
                    {formatRelativeTime(provider.lastChecked)}
                  </time>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="ai-footer">
        <time dateTime={ai.lastUpdated} className="last-updated">
          Updated {formatRelativeTime(ai.lastUpdated)}
        </time>
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
