/**
 * NPH Command Center - Activity Page
 * 
 * Unified recent activity feed with filtering.
 */

import { useState, useMemo, useEffect } from 'react';
import { ActivityEvent, ActivityCategory } from '../types/infrastructure';
import { getActivityFeed } from '../services/command-center';
import { ActivityFeed } from '../components/activity/ActivityFeed';
import './Activity.css';

export function Activity() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<ActivityCategory | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const loadActivity = async () => {
    try {
      setLoading(true);
      const data = await getActivityFeed(200);
      setEvents(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load activity');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadActivity();
  }, []);

  const filteredEvents = useMemo(() => {
    return events.filter(event => {
      if (categoryFilter !== 'all' && event.category !== categoryFilter) return false;
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!event.title.toLowerCase().includes(query) &&
            !event.message.toLowerCase().includes(query) &&
            !event.source.toLowerCase().includes(query)) {
          return false;
        }
      }
      return true;
    });
  }, [events, categoryFilter, searchQuery]);

  const categories = useMemo(() => {
    const cats = new Set(events.map(e => e.category));
    return Array.from(cats).sort() as (ActivityCategory | 'all')[];
  }, [events]);

  if (loading) {
    return (
      <div className="activity-page loading">
        <div className="loading-skeleton">
          <div className="skeleton-header" />
          <div className="skeleton-filters" />
          <div className="skeleton-feed">
            {[...Array(10)].map((_, i) => <div key={i} className="skeleton-event" />)}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="activity-page error">
        <div className="error-state">
          <h2>Failed to Load Activity</h2>
          <p>{error}</p>
          <button onClick={loadActivity} className="btn-primary">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="activity-page">
      <header className="page-header">
        <h1>Activity</h1>
        <p className="page-subtitle">{events.length} events • {filteredEvents.length} filtered</p>
      </header>

      <div className="filters-bar">
        <div className="filter-group search-group">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            type="text"
            placeholder="Search activity..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="filter-input"
          />
        </div>

        <div className="filter-group">
          <select
            value={categoryFilter}
            onChange={e => setCategoryFilter(e.target.value as ActivityCategory | 'all')}
            className="filter-select"
          >
            <option value="all">All Categories</option>
            {categories.map(cat => (
              <option key={cat} value={cat}>{getCategoryLabel(cat)}</option>
            ))}
          </select>
        </div>
      </div>

      <ActivityFeed events={filteredEvents} maxItems={100} />
    </div>
  );
}

function getCategoryLabel(category: string): string {
  const labels: Record<string, string> = {
    'deployment': 'Deployment',
    'git': 'Git',
    'service': 'Service',
    'alert': 'Alert',
    'infrastructure': 'Infrastructure',
    'project': 'Project',
    'ai': 'AI',
    'DEPLOYMENT': 'Deployment',
    'AI': 'AI',
    'INFRA': 'Infrastructure',
    'PROJECT': 'Project',
    'SECURITY': 'Security',
    'STORAGE': 'Storage',
    'NETWORK': 'Network',
    'OTHER': 'Other',
  };
  return labels[category] || category;
}
