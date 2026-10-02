/**
 * NPH Command Center - Service Inventory Component
 * 
 * Displays a list of services with status, category, and health info.
 */

import { Link } from 'react-router-dom';
import { Service } from '../../types/infrastructure';
import { ServiceCard } from './ServiceCard';
import './ServiceInventory.css';

interface ServiceInventoryProps {
  services: Service[];
  maxItems?: number;
}

export function ServiceInventory({ services, maxItems = 8 }: ServiceInventoryProps) {
  const displayServices = services.slice(0, maxItems);

  if (!services.length) {
    return (
      <div className="service-inventory empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M9 9h6v6H9z" />
          </svg>
          <span>No services discovered</span>
          <p>Services will appear here when configured</p>
        </div>
      </div>
    );
  }

  // Group by category
  const servicesByCategory = displayServices.reduce((acc, service) => {
    if (!acc[service.category]) acc[service.category] = [];
    acc[service.category].push(service);
    return acc;
  }, {} as Record<string, Service[]>);

  const categoryOrder = [
    'reverse-proxy', 'orchestration', 'ai-gateway', 'database', 'cache',
    'storage', 'media-automation', 'media-server', 'download-client', 'indexer',
    'monitoring', 'dns', 'security', 'utility', 'development', 'other'
  ];

  return (
    <div className="service-inventory">
      <div className="service-list" role="list" aria-label="Services">
        {categoryOrder
          .filter(cat => servicesByCategory[cat] && servicesByCategory[cat].length > 0)
          .map(category => (
            <div key={category} className="service-category">
              <div className="category-header">
                <span className="category-icon">{getCategoryIcon(category)}</span>
                <span className="category-label">{getCategoryLabel(category)}</span>
                <span className="category-count">{servicesByCategory[category].length}</span>
              </div>
              <div className="category-services">
                {servicesByCategory[category].map(service => (
                  <ServiceCard key={service.id} service={service} compact />
                ))}
              </div>
            </div>
          ))}
      </div>
      
      {services.length > maxItems && (
        <div className="inventory-footer">
          <Link to="/services" className="view-all-link">
            View all {services.length} services
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </Link>
        </div>
      )}
    </div>
  );
}

function getCategoryIcon(category: string): string {
  const icons: Record<string, string> = {
    'reverse-proxy': '🔀',
    'orchestration': '⚙️',
    'storage': '💾',
    'media-automation': '🎬',
    'media-server': '📺',
    'download-client': '⬇️',
    'indexer': '🔍',
    'monitoring': '📊',
    'dns': '🌐',
    'security': '🔐',
    'ai-gateway': '🤖',
    'database': '🗄️',
    'cache': '⚡',
    'utility': '🔧',
    'development': '💻',
    'other': '📦',
  };
  return icons[category] || '📦';
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
