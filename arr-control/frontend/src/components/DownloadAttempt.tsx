import { DownloadAttempt as DownloadAttemptType } from '../types';

interface Props {
  attempt: DownloadAttemptType;
}

export const DownloadAttempt: React.FC<Props> = ({ attempt }) => {
  const crossSeedLabel = attempt.is_cross_seed ? (
    <span
      style={{
        marginLeft: '0.5rem',
        padding: '0.125rem 0.375rem',
        borderRadius: '0.25rem',
        fontSize: '0.7rem',
        fontWeight: 'bold',
        background: '#e17055',
        color: '#fff',
      }}
    >
      CROSS-SEED
    </span>
  ) : null;

  const stateColors: Record<string, string> = {
    download_started: '#10ac84',
    download_progress: '#00b894',
    download_completed: '#00cec9',
    download_failed: '#d63031',
    stuck: '#636e72',
  };

  const stateColor = stateColors[attempt.state] || '#00d4ff';

  return (
    <div
      style={{
        border: '1px solid #333',
        borderRadius: '0.5rem',
        padding: '1rem',
        marginBottom: '0.75rem',
        background: '#1e1e1e',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <span
          style={{
            padding: '0.125rem 0.5rem',
            borderRadius: '0.25rem',
            fontSize: '0.75rem',
            fontWeight: 'bold',
            background: stateColor,
            color: '#fff',
            textTransform: 'uppercase',
          }}
        >
          {attempt.state.replace(/_/g, ' ')}
        </span>
        {crossSeedLabel}
        <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: '#888' }}>
          Hash: {attempt.hash.substring(0, 16)}...
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '0.75rem', fontSize: '0.875rem' }}>
        <div>
          <div style={{ color: '#888', fontSize: '0.75rem' }}>Category</div>
          <div>{attempt.category || '—'}</div>
        </div>
        <div>
          <div style={{ color: '#888', fontSize: '0.75rem' }}>Tags</div>
          <div>{attempt.tags || '—'}</div>
        </div>
        <div>
          <div style={{ color: '#888', fontSize: '0.75rem' }}>Progress</div>
          <div>{attempt.progress}%</div>
        </div>
        <div>
          <div style={{ color: '#888', fontSize: '0.75rem' }}>Events</div>
          <div>{attempt.event_count}</div>
        </div>
        <div>
          <div style={{ color: '#888', fontSize: '0.75rem' }}>First Event</div>
          <div>{new Date(attempt.first_event).toLocaleString()}</div>
        </div>
        <div>
          <div style={{ color: '#888', fontSize: '0.75rem' }}>Last Event</div>
          <div>{new Date(attempt.last_event).toLocaleString()}</div>
        </div>
      </div>
    </div>
  );
};

export default DownloadAttempt;