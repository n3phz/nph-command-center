/**
 * NPH Command Center - Storage Page
 * 
 * Full storage overview with utilization across all locations.
 */

import { useState, useEffect } from 'react';
import { StorageOverview } from '../types/infrastructure';
import { getStorageOverview } from '../services/command-center';
import { StorageOverviewComponent } from '../components/storage/StorageOverview';
import './Storage.css';

export function Storage() {
  const [storage, setStorage] = useState<StorageOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStorage = async () => {
    try {
      setLoading(true);
      const data = await getStorageOverview();
      setStorage(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load storage');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStorage();
  }, []);

  if (loading) {
    return (
      <div className="storage-page loading">
        <div className="loading-skeleton">
          <div className="skeleton-header" />
          <div className="skeleton-summary" />
          <div className="skeleton-grid">
            {[...Array(4)].map((_, i) => <div key={i} className="skeleton-card" />)}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="storage-page error">
        <div className="error-state">
          <h2>Failed to Load Storage</h2>
          <p>{error}</p>
          <button onClick={loadStorage} className="btn-primary">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="storage-page">
      <header className="page-header">
        <h1>Storage</h1>
        <p className="page-subtitle">
          {storage?.locations.length || 0} locations • 
          {storage ? `${storage.usagePercent.toFixed(1)}% used` : 'N/A'}
        </p>
      </header>

      <StorageOverviewComponent storage={storage} />
    </div>
  );
}
