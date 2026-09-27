interface PipelineRow {
  id: string;
  title: string;
  state: string;
  progress?: number;
  current_service?: string;
  last_event_at?: string;
  season?: number;
  episode?: number;
}

interface PipelineListProps {
  items: PipelineRow[];
  onItemSelect: (id: string) => void;
}

export const PipelineList: React.FC<PipelineListProps> = ({ items, onItemSelect }) => {
  const formatTime = (timestamp?: string) => {
    if (!timestamp) return '';
    try {
      const date = new Date(timestamp);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins} minutes ago`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours} hours ago`;
      return date.toLocaleDateString();
    } catch {
      return timestamp;
    }
  };

  return (
    <table className="pipeline-table">
      <thead>
        <tr>
          <th>Title</th>
          <th>State</th>
          <th>Progress</th>
          <th>Current Service</th>
          <th>Last Activity</th>
        </tr>
      </thead>
      <tbody>
        {items.length === 0 ? (
          <tr>
            <td colSpan={5} style={{ textAlign: 'center', color: '#666', padding: '2rem' }}>
              No active items
            </td>
          </tr>
        ) : (
          items.map((item) => (
            <tr key={item.id} onClick={() => onItemSelect(item.id)} style={{ cursor: 'pointer' }}>
              <td>
                <a href={`/item/${item.id}`}>
                  {item.title}
                  {item.season && item.episode && (
                    <span style={{ color: '#666', fontSize: '0.875rem', marginLeft: '0.5rem' }}>
                      S{item.season.toString().padStart(2, '0')}E{item.episode.toString().padStart(2, '0')}
                    </span>
                  )}
                </a>
              </td>
              <td>
                <span className={`state-badge ${item.state.replace(/\s+/g, '_').toLowerCase()}`}>
                  {item.state.replace(/_/g, ' ')}
                </span>
              </td>
              <td>
                {item.progress !== undefined ? (
                  <>
                    <div className="progress-bar">
                      <div className="fill" style={{ width: `${item.progress}%` }} />
                    </div>
                    <span style={{ fontSize: '0.75rem', color: '#888' }}>{item.progress}%</span>
                  </>
                ) : (
                  <span style={{ color: '#666' }}>—</span>
                )}
              </td>
              <td style={{ color: '#888', fontSize: '0.875rem' }}>{item.current_service || '—'}</td>
              <td style={{ color: '#666', fontSize: '0.875rem' }}>{formatTime(item.last_event_at)}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
};

export default PipelineList;