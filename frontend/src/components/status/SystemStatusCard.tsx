/**
 * NPH Command Center - System Status Card
 * 
 * Large, prominent system health indicator with detailed breakdown.
 */

import { useState, useEffect } from 'react';
import './SystemStatusCard.css';

interface SystemStatusCardProps {
  status: {
    overall: 'HEALTHY' | 'DEGRADED' | 'ATTENTION_REQUIRED' | 'OFFLINE' | 'UNKNOWN';
    healthyCount: number;
    degradedCount: number;
    unavailableCount: number;
    totalCount: number;
    lastChecked: string;
    uptime?: string;
  } | null;
  lastUpdated: Date;
  onRefresh: () => void;
}

const STATUS_CONFIG = {
  HEALTHY: { label: 'HEALTHY', color: 'var(--status-healthy)', bg: 'rgba(76, 175, 80, 0.1)', icon: '✓' },
  DEGRADED: { label: 'DEGRADED', color: 'var(--status-warning)', bg: 'rgba(255, 193, 7, 0.1)', icon: '⚠' },
  ATTENTION_REQUIRED: { label: 'ATTENTION REQUIRED', color: 'var(--status-warning)', bg: 'rgba(255, 193, 7, 0.1)', icon: '!' },
  OFFLINE: { label: 'OFFLINE', color: 'var(--status-critical)', bg: 'rgba(244, 67, 54, 0.1)', icon: '✕' },
  UNKNOWN: { label: 'UNKNOWN', color: 'var(--status-unknown)', bg: 'rgba(158, 158, 158, 0.1)', icon: '?' },
};

export function SystemStatusCard({ status, onRefresh }: SystemStatusCardProps) {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  if (!status) {
    return (
      <div className="system-status-card unknown">
        <div className="status-main">
          <div className="status-badge unknown">
            <span className="status-icon">?</span>
            <span className="status-label">NPH SYSTEM STATUS</span>
            <span className="status-value">UNKNOWN</span>
          </div>
        </div>
        <div className="status-details">
          <div className="detail-item">
            <span className="detail-label">Last Check</span>
            <span className="detail-value">--:--:--</span>
          </div>
        </div>
      </div>
    );
  }

  const config = STATUS_CONFIG[status.overall];

  return (
    <div className={`system-status-card ${status.overall.toLowerCase().replace('_', '-')}`}>
      <div className="status-main">
        <div className="status-badge" style={{ backgroundColor: config.bg, borderColor: config.color }}>
          <span className="status-icon" style={{ color: config.color }}>{config.icon}</span>
          <span className="status-label">NPH SYSTEM STATUS</span>
          <span className="status-value" style={{ color: config.color }}>{config.label}</span>
        </div>
        <button 
          className="refresh-btn"
          onClick={onRefresh}
          aria-label="Refresh system status"
          disabled={status.overall === 'UNKNOWN'}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M23 4v6h-6" />
            <path d="M1 20v-6h6" />
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
        </button>
      </div>

      <div className="status-details">
        <div className="detail-grid">
          <div className="detail-item healthy">
            <span className="detail-label">Healthy</span>
            <span className="detail-value" style={{ color: 'var(--status-healthy)' }}>{status.healthyCount}</span>
          </div>
          <div className="detail-item degraded">
            <span className="detail-label">Degraded</span>
            <span className="detail-value" style={{ color: 'var(--status-warning)' }}>{status.degradedCount}</span>
          </div>
          <div className="detail-item unavailable">
            <span className="detail-label">Unavailable</span>
            <span className="detail-value" style={{ color: 'var(--status-critical)' }}>{status.unavailableCount}</span>
          </div>
          <div className="detail-item total">
            <span className="detail-label">Total Services</span>
            <span className="detail-value">{status.totalCount}</span>
          </div>
        </div>

        <div className="status-meta">
          <div className="meta-item">
            <span className="meta-label">Last Checked</span>
            <time className="meta-value" dateTime={status.lastChecked}>
              {formatTime(status.lastChecked)}
            </time>
          </div>
          <div className="meta-item">
            <span className="meta-label">This Page Updated</span>
            <span className="meta-value">{time.toLocaleTimeString()}</span>
          </div>
          {status.uptime && (
            <div className="meta-item">
              <span className="meta-label">Uptime</span>
              <span className="meta-value">{status.uptime}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return date.toLocaleString();
}
