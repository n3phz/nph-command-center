interface TimelineProps {
  events: Array<{
    timestamp: string;
    source: string;
    event_type: string;
    error_message?: string;
  }>;
}

export const Timeline: React.FC<TimelineProps> = ({ events }) => {
  const formatTime = (timestamp: string) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    } catch {
      return timestamp;
    }
  };

  const getEventIcon = (eventType: string) => {
    const icons: Record<string, string> = {
      wanted: 'W',
      search_started: 'S',
      release_grabbed: 'G',
      download_started: '↓',
      download_progress: '↓',
      download_completed: '✓',
      download_failed: '✗',
      import_started: 'I',
      import_completed: '✓',
      import_failed: '✗',
      available: '✓',
      stuck: '⏸',
    };
    return icons[eventType] || '•';
  };

  const getEventColor = (eventType: string) => {
    const colors: Record<string, string> = {
      wanted: '#3742fa',
      search_started: '#5f27cd',
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

  return (
    <div className="timeline">
      <h3>Timeline</h3>
      {events.length === 0 ? (
        <p style={{ color: '#666', fontSize: '0.875rem' }}>No events recorded</p>
      ) : (
        events.map((event, index) => (
          <div key={index} className="timeline-event">
            <span className="timeline-time">{formatTime(event.timestamp)}</span>
            <div
              className="timeline-icon"
              style={{ background: getEventColor(event.event_type), color: '#fff' }}
            >
              {getEventIcon(event.event_type)}
            </div>
            <div className="timeline-content">
              <div className="event-type">{event.event_type.replace(/_/g, ' ')}</div>
              <div className="event-source">{event.source}</div>
              {event.error_message && (
                <div className="error-message">{event.error_message}</div>
              )}
            </div>
          </div>
        ))
      )}
    </div>
  );
};

export default Timeline;