/**
 * NPH Command Center - Host Inventory Component
 * 
 * Displays infrastructure hosts with metrics and status.
 */

import { Host } from '../../types/infrastructure';
import { HostCard } from './HostCard';
import './HostInventory.css';

interface HostInventoryProps {
  hosts: Host[];
  maxItems?: number;
}

export function HostInventory({ hosts, maxItems = 8 }: HostInventoryProps) {
  const displayHosts = hosts.slice(0, maxItems);
  const onlineCount = hosts.filter(h => h.status === 'online').length;

  if (!hosts.length) {
    return (
      <div className="host-inventory empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M9 9h6v6H9z" />
          </svg>
          <span>No hosts discovered</span>
          <p>Hosts will appear here when configured</p>
        </div>
      </div>
    );
  }

  return (
    <div className="host-inventory">
      <div className="host-summary">
        <span className="summary-item online">{onlineCount} online</span>
        <span className="summary-item total">{hosts.length} total</span>
      </div>
      
      <div className="host-grid" role="list" aria-label="Hosts">
        {displayHosts.map(host => (
          <HostCard key={host.id} host={host} />
        ))}
      </div>
      
      {hosts.length > maxItems && (
        <div className="inventory-footer">
          <span>+{hosts.length - maxItems} more hosts</span>
        </div>
      )}
    </div>
  );
}
