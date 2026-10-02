/**
 * NPH Command Center - Hosts Page
 * 
 * Full host inventory with metrics and status.
 */

import { useState, useMemo, useEffect } from 'react';
import { Host } from '../types/infrastructure';
import { getHosts } from '../services/command-center';
import { HostInventory } from '../components/hosts/HostInventory';
import './Hosts.css';

export function Hosts() {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const loadHosts = async () => {
    try {
      setLoading(true);
      const data = await getHosts();
      setHosts(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load hosts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHosts();
  }, []);

  const filteredHosts = useMemo(() => {
    return hosts.filter(host => {
      if (statusFilter !== 'all' && host.status !== statusFilter) return false;
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!host.name.toLowerCase().includes(query) &&
            !host.hostname.toLowerCase().includes(query) &&
            !host.ip?.toLowerCase().includes(query) &&
            !(host.os?.toLowerCase().includes(query))) {
          return false;
        }
      }
      return true;
    });
  }, [hosts, statusFilter, searchQuery]);

  const statuses = useMemo(() => {
    const stats = new Set(hosts.map(h => h.status));
    return Array.from(stats).sort();
  }, [hosts]);

  const onlineCount = hosts.filter(h => h.status === 'online').length;

  if (loading) {
    return (
      <div className="hosts-page loading">
        <div className="loading-skeleton">
          <div className="skeleton-header" />
          <div className="skeleton-filters" />
          <div className="skeleton-grid">
            {[...Array(6)].map((_, i) => <div key={i} className="skeleton-card" />)}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="hosts-page error">
        <div className="error-state">
          <h2>Failed to Load Hosts</h2>
          <p>{error}</p>
          <button onClick={loadHosts} className="btn-primary">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="hosts-page">
      <header className="page-header">
        <h1>Hosts</h1>
        <p className="page-subtitle">{hosts.length} hosts • {onlineCount} online</p>
      </header>

      <div className="filters-bar">
        <div className="filter-group search-group">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            type="text"
            placeholder="Search hosts..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="filter-input"
          />
        </div>

        <div className="filter-group">
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="filter-select"
          >
            <option value="all">All Statuses</option>
            {statuses.map(status => (
              <option key={status} value={status}>{getStatusLabel(status)}</option>
            ))}
          </select>
        </div>
      </div>

      <HostInventory hosts={filteredHosts} maxItems={100} />
    </div>
  );
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    'online': 'Online',
    'offline': 'Offline',
    'degraded': 'Degraded',
    'unknown': 'Unknown',
    'discovered': 'Discovered',
  };
  return labels[status] || status;
}
