import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from './services/api';
import { ItemDetail, Explanation } from './types';
import Timeline from './components/Timeline';
import ExplanationCard from './components/ExplanationCard';

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
      setItem(itemData);
      setExplanation(explanationData);
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

      {explanation && <ExplanationCard reason={explanation.reason} evidence={explanation.evidence} />}

      <Timeline events={item.timeline} />
    </div>
  );
}

export default ItemDetailPage;