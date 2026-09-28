import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../services/api';
import { ItemDetail, Explanation } from '../types';
import Timeline from '../components/Timeline';
import ExplanationCard from '../components/ExplanationCard';
import DownloadAttempt from '../components/DownloadAttempt';

function ItemDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<ItemDetail | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id) {
      loadItem();
    }
  }, [id]);

  const loadItem = async () => {
    if (!id) return;
    try {
      setLoading(true);
      const [itemData, explanationData] = await Promise.all([
        api.getItem(id),
        api.getItemExplanation(id)
      ]);
      setItem(itemData as ItemDetail | null);
      setExplanation(explanationData as Explanation | null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load item');
    } finally {
      setLoading(false);
    }
  };

  if (error) {
    return (
      <div className="error">
        <h2>Error</h2>
        <p>{error}</p>
        <Link to="/" style={{ marginTop: '1rem', display: 'inline-block' }}>Back to Dashboard</Link>
      </div>
    );
  }

  if (loading) {
    return <div className="loading">Loading...</div>;
  }

  if (!item) {
    return (
      <div className="error">
        <h2>Item not found</h2>
        <Link to="/" style={{ marginTop: '1rem', display: 'inline-block' }}>Back to Dashboard</Link>
      </div>
    );
  }

  return (
    <div className="detail-container">
      <Link to="/" style={{ color: '#00d4ff', textDecoration: 'none' }}>← Back</Link>
      
      <div className="detail-header">
        <h2>{item.title}</h2>
        <div className="detail-meta">
          <span>{item.media_type.toUpperCase()}</span>
          {item.season && item.episode && (
            <span>S{item.season.toString().padStart(2, '0')}E{item.episode.toString().padStart(2, '0')}</span>
          )}
          {item.tmdb_id && <span>TMDB: {item.tmdb_id}</span>}
          {item.tvdb_id && <span>TVDB: {item.tvdb_id}</span>}
        </div>
      </div>

      <div className="detail-state">
        <h3>Current State</h3>
        <span className={`state-badge ${item.current_state.replace(/_/g, '_').toLowerCase()}`}>
          {item.current_state.replace(/_/g, ' ')}
        </span>
        {item.confidence && (
          <span
            style={{
              marginLeft: '1rem',
              padding: '0.125rem 0.5rem',
              borderRadius: '0.25rem',
              fontSize: '0.75rem',
              fontWeight: 'bold',
              background: item.confidence === 'HIGH' ? '#00b894' : item.confidence === 'MEDIUM' ? '#fdcb6e' : '#d63031',
              color: '#fff',
            }}
          >
            {item.confidence}
          </span>
        )}
        {item.progress !== undefined && (
          <div style={{ marginTop: '1rem' }}>
            <div className="progress-bar" style={{ height: '8px' }}>
              <div className="fill" style={{ width: `${item.progress}%` }} />
            </div>
            <span style={{ fontSize: '0.875rem', color: '#888', marginTop: '0.25rem', display: 'block' }}>
              {item.progress}%
            </span>
          </div>
        )}
        {item.current_service && (
          <p style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: '#888' }}>
            Current Service: {item.current_service}
          </p>
        )}
        {item.next_expected_state && (
          <p style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: '#888' }}>
            Next Expected: {item.next_expected_state.replace(/_/g, ' ')}
          </p>
        )}
      </div>

      {explanation && <ExplanationCard reason={explanation.reason} evidence={explanation.evidence} confidence={item.confidence} />}

      {item.download_attempts && item.download_attempts.length > 0 && (
        <div style={{ marginTop: '1.5rem' }}>
          <h3>Download Attempts</h3>
          {item.download_attempts.map((attempt, index) => (
            <DownloadAttempt key={index} attempt={attempt} />
          ))}
        </div>
      )}

      <Timeline events={item.timeline} />
    </div>
  );
}

export default ItemDetailPage;