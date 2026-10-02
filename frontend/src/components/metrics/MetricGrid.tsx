/**
 * NPH Command Center - Metric Grid Component
 * 
 * Responsive grid layout for metric cards.
 * Supports both standard and live metric cards.
 */

import { MetricCard } from './MetricCard';
import { LiveMetricCard } from './LiveMetricCard';
import './MetricGrid.css';

interface MetricCardData {
  id: string;
  label: string;
  value: string | number;
  unit?: string;
  status: 'normal' | 'watch' | 'warning' | 'critical' | 'unknown';
  trend?: 'up' | 'down' | 'stable';
  description?: string;
  lastUpdated?: string;
  source?: string;
  // Live update support
  liveKey?: string;
  liveEnabled?: boolean;
}

interface MetricGridProps {
  cards: MetricCardData[];
  columns?: number;
}

export function MetricGrid({ cards, columns = 4 }: MetricGridProps) {
  if (!cards.length) {
    return (
      <div className="metric-grid empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M9 9h6v6H9z" />
          </svg>
          <span>No metrics available</span>
        </div>
      </div>
    );
  }

  return (
    <div 
      className="metric-grid"
      style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
      role="list"
      aria-label="Metrics"
    >
      {cards.map(card => {
        if (card.liveEnabled && card.liveKey) {
          return <LiveMetricCard key={card.id} {...card} />;
        }
        return <MetricCard key={card.id} {...card} />;
      })}
    </div>
  );
}