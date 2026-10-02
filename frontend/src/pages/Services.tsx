/**
 * NPH Command Center - Services Page
 * 
 * Full service inventory with filtering and search.
 */

import { useState, useMemo, useEffect } from 'react';
import { Service, ServiceCategory } from '../types/infrastructure';
import { getServices } from '../services/command-center';
import { ServiceCard } from '../components/services/ServiceCard';
import './Services.css';

export function Services() {
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<ServiceCategory | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Load services
  const loadServices = async () => {
    try {
      setLoading(true);
      const data = await getServices();
      setServices(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load services');
    } finally {
      setLoading(false);
    }
  };

  // Load on mount
  useEffect(() => {
    loadServices();
  }, []);

  const filteredServices = useMemo(() => {
    return services.filter(service => {
      if (categoryFilter !== 'all' && service.category !== categoryFilter) return false;
      if (statusFilter !== 'all' && service.status !== statusFilter) return false;
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!service.name.toLowerCase().includes(query) &&
            !service.host.toLowerCase().includes(query) &&
            !service.category.toLowerCase().includes(query) &&
            !(service.description?.toLowerCase().includes(query))) {
          return false;
        }
      }
      return true;
    });
  }, [services, categoryFilter, statusFilter, searchQuery]);

  const categories = useMemo(() => {
    const cats = new Set(services.map(s => s.category));
    return Array.from(cats).sort();
  }, [services]);

  const statuses = useMemo(() => {
    const stats = new Set(services.map(s => s.status));
    return Array.from(stats).sort();
  }, [services]);

  if (loading) {
    return (
      <div className="services-page loading">
        <div className="loading-skeleton">
          <div className="skeleton-header" />
          <div className="skeleton-filters" />
          <div className="skeleton-grid">
            {[...Array(8)].map((_, i) => <div key={i} className="skeleton-card" />)}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="services-page error">
        <div className="error-state">
          <h2>Failed to Load Services</h2>
          <p>{error}</p>
          <button onClick={loadServices} className="btn-primary">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="services-page">
      <header className="page-header">
        <h1>Services</h1>
        <p className="page-subtitle">{services.length} services • {filteredServices.length} filtered</p>
      </header>

      <div className="filters-bar">
        <div className="filter-group search-group">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            type="text"
            placeholder="Search services..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="filter-input"
          />
        </div>

        <div className="filter-group">
          <select
            value={categoryFilter}
            onChange={e => setCategoryFilter(e.target.value as ServiceCategory | 'all')}
            className="filter-select"
          >
            <option value="all">All Categories</option>
            {categories.map(cat => (
              <option key={cat} value={cat}>{getCategoryLabel(cat)}</option>
            ))}
          </select>
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

      <div className="services-grid" role="list" aria-label="Services">
        {filteredServices.map(service => (
          <ServiceCard key={service.id} service={service} />
        ))}
      </div>

      {filteredServices.length === 0 && !loading && (
        <div className="empty-state">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M9 9h6v6H9z" />
          </svg>
          <h3>No services match your filters</h3>
          <p>Try adjusting your search or filter criteria</p>
        </div>
      )}
    </div>
  );
}

function getCategoryLabel(category: string): string {
  const labels: Record<string, string> = {
    'reverse-proxy': 'Reverse Proxy',
    'orchestration': 'Orchestration',
    'storage': 'Storage',
    'media-automation': 'Media Automation',
    'media-server': 'Media Server',
    'download-client': 'Download Client',
    'indexer': 'Indexer',
    'monitoring': 'Monitoring',
    'dns': 'DNS',
    'security': 'Security',
    'ai-gateway': 'AI Gateway',
    'database': 'Database',
    'cache': 'Cache',
    'utility': 'Utility',
    'development': 'Development',
    'other': 'Other',
  };
  return labels[category] || category;
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    'healthy': 'Healthy',
    'degraded': 'Degraded',
    'down': 'Down',
    'unknown': 'Unknown',
    'discovered': 'Discovered',
  };
  return labels[status] || status;
}
