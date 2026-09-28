/** Activity page component. */
import { useState, useEffect } from 'react';
import { Event } from '../types';

interface Props {
  days?: number;
}

function ActivityPage({ days = 7 }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    source: '',
    eventType: '',
    stuckOnly: false,
    failedOnly: false,
    search: ''
  });
  const [page, setPage] = useState(0);

  const loadEvents = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({
        days: String(days),
        limit: '100',
        offset: String(page * 100),
        ...(filters.source && { source_service: filters.source }),
        ...(filters.eventType && { event_type: filters.eventType }),
        ...(filters.stuckOnly && { stuck_only: 'true' }),
        ...(filters.failedOnly && { failed_only: 'true' }),
        ...(filters.search && { search: filters.search }),
      });
      const response = await fetch(`/api/activity?${params}`);
      const data = await response.json();
      setEvents(data);
      
      // Load stats
      const statsRes = await fetch(`/api/activity/stats?days=${days}`);
      const statsData = await statsRes.json();
      setStats(statsData);
      
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load activity');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEvents();
  }, [days, page, filters]);

  const formatTime = (timestamp: string) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleString();
    } catch {
      return timestamp;
    }
  };

  const getEventColor = (eventType: string) => {
    const colors: Record<string, string> = {
      wanted: '#3742fa',
      release_grabbed: '#0abde3',
      download_started: '#10ac84',
      download_progress: '#00b894',
      download_completed: '#00cec9',
      download_failed: '#d63031',
      import_started: '#fdcb6e',
      import_completed: '#00b894',
      import_failed: '#e17055',
      available: '#6c5ce7',
      stuck: '#636e72',
    };
    return colors[eventType] || '#00d4ff';
  };

  if (error) {
    return (
      <div className="error">
        <h2>Error</h2>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="activity-page">
      <h1>Activity History</h1>
      
      {stats && (
        <div className="activity-stats">
          <div className="stat-card">
            <div className="stat-value">{stats.today}</div>
            <div className="stat-label">Today</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.by_source?.sonarr || 0}</div>
            <div className="stat-label">Sonarr Events</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.by_source?.radarr || 0}</div>
            <div className="stat-label">Radarr Events</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.by_source?.qbittorrent || 0}</div>
            <div className="stat-label">qBittorrent Events</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.by_source?.prowlarr || 0}</div>
            <div className="stat-label">Prowlarr Events</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#d63031' }}>{stats.failed}</div>
            <div className="stat-label">Failed</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#636e72' }}>{stats.stuck}</div>
            <div className="stat-label">Stuck</div>
          </div>
        </div>
      )}
      
      <div className="activity-filters">
        <input
          type="text"
          placeholder="Search title..."
          value={filters.search}
          onChange={(e) => setFilters({ ...filters, search: e.target.value })}
        />
        <select
          value={filters.source}
          onChange={(e) => setFilters({ ...filters, source: e.target.value })}
        >
          <option value="">All Services</option>
          <option value="sonarr">Sonarr</option>
          <option value="radarr">Radarr</option>
          <option value="qbittorrent">qBittorrent</option>
          <option value="prowlarr">Prowlarr</option>
        </select>
        <select
          value={filters.eventType}
          onChange={(e) => setFilters({ ...filters, eventType: e.target.value })}
        >
          <option value="">All Events</option>
          <option value="wanted">Wanted</option>
          <option value="release_grabbed">Grabbed</option>
          <option value="download_started">Download Started</option>
          <option value="download_progress">Downloading</option>
          <option value="download_completed">Download Completed</option>
          <option value="download_failed">Download Failed</option>
          <option value="import_started">Import Started</option>
          <option value="import_completed">Import Completed</option>
          <option value="import_failed">Import Failed</option>
          <option value="available">Available</option>
          <option value="stuck">Stuck</option>
        </select>
        <label>
          <input
            type="checkbox"
            checked={filters.stuckOnly}
            onChange={(e) => setFilters({ ...filters, stuckOnly: e.target.checked })}
          />
          Stuck Only
        </label>
        <label>
          <input
            type="checkbox"
            checked={filters.failedOnly}
            onChange={(e) => setFilters({ ...filters, failedOnly: e.target.checked })}
          />
          Failed Only
        </label>
      </div>
      
      {loading ? (
        <div className="loading">Loading...</div>
      ) : (
        <div className="activity-list">
          {events.length === 0 ? (
            <p>No events found.</p>
          ) : (
            events.map((event) => (
              <div key={event.id} className="activity-event">
                <span className="activity-time">{formatTime(event.timestamp)}</span>
                <span
                  className="activity-icon"
                  style={{ background: getEventColor(event.event_type) }}
                >
                  {event.event_type[0].toUpperCase()}
                </span>
                <div className="activity-content">
                  <div className="activity-title">{event.title}</div>
                  <div className="activity-meta">
                    <span className="activity-source">{event.source_service}</span>
                    <span className="activity-type">{event.event_type.replace(/_/g, ' ')}</span>
                    {event.season && event.episode && (
                      <span>S{event.season.toString().padStart(2, '0')}E{event.episode.toString().padStart(2, '0')}</span>
                    )}
                    {event.error_message && (
                      <span className="activity-error">{event.error_message}</span>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
      
      {events.length > 0 && (
        <div className="activity-pagination">
          <button
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            Previous
          </button>
          <span>Page {page + 1}</span>
          <button onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}

export default ActivityPage;