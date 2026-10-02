/**
 * NPH Command Center - Activity Feed Component
 * 
 * Displays recent activity events in a timeline format.
 */

import { ActivityEvent } from '../../types/infrastructure';
import { ActivityEventComponent } from './ActivityEvent';
import './ActivityFeed.css';

interface ActivityFeedProps {
  events: ActivityEvent[];
  maxItems?: number;
}

export function ActivityFeed({ events, maxItems = 10 }: ActivityFeedProps) {
  const displayEvents = events.slice(0, maxItems);

  if (!displayEvents.length) {
    return (
      <div className="activity-feed empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="4" width="18" height="18" rx="2" />
            <path d="M16 2v4M16 18v4M4 16H2a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h2" />
          </svg>
          <span>No recent activity</span>
          <p>Activity will appear here as events occur</p>
        </div>
      </div>
    );
  }

  return (
    <div className="activity-feed">
      <div className="activity-list" role="list" aria-label="Recent activity">
        {displayEvents.map((event, index) => (
          <ActivityEventComponent key={event.id} event={event} isLast={index === displayEvents.length - 1} />
        ))}
      </div>
    </div>
  );
}
