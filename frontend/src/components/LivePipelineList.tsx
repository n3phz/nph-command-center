/**
 * NPH Command Center - Live Pipeline List Component
 * 
 * Enhanced pipeline list with live SSE updates showing real-time state transitions.
 */

import { useState, useEffect, useMemo } from 'react';
import { useMediaItemUpdates } from '../hooks/useEventStream';
import type { PipelineRow } from './PipelineList';
import './LivePipelineList.css';

interface LivePipelineListProps {
  initialItems: PipelineRow[];
  onItemSelect: (id: string) => void;
}

export function LivePipelineList({ initialItems, onItemSelect }: LivePipelineListProps) {
  const [items, setItems] = useState<PipelineRow[]>(initialItems);
  const [liveUpdates, setLiveUpdates] = useState<Record<string, { 
    state: string; 
    progress: number; 
    current_service: string; 
    last_event_at: string;
    isLive: boolean;
    liveState: 'queued' | 'working' | 'progress' | 'success' | 'failed' | 'retrying' | 'fallback';
  }>>({});

  const formatTime = (timestamp?: string) => {
    if (!timestamp) return '';
    try {
      const date = new Date(timestamp);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;
      return date.toLocaleDateString();
    } catch {
      return timestamp;
    }
  };

  // Handle live SSE events
  const handleItemUpdate = (itemId: string, data: Record<string, any>) => {
    setItems(prev => prev.map(item => {
      if (item.id === itemId) {
        return {
          ...item,
          title: data.title || item.title,
          current_service: data.current_service || item.current_service,
          progress: data.progress !== undefined ? data.progress : item.progress,
          state: data.current_state || data.state || item.state,
          last_event_at: data.timestamp || new Date().toISOString(),
        };
      }
      return item;
    }));
  };

  const handleProgressUpdate = (itemId: string, progress: number, state: string) => {
    setLiveUpdates(prev => ({
      ...prev,
      [itemId]: {
        state: state,
        progress,
        current_service: '',
        last_event_at: new Date().toISOString(),
        isLive: true,
        liveState: progress > 0 ? 'progress' : 'working',
      }
    }));
  };

  const handleStateChange = (itemId: string, newState: string, _oldState: string | null) => {
    const isError = newState.includes('failed') || newState === 'stuck';
    const isComplete = newState === 'available' || newState === 'import_completed';
    
    setLiveUpdates(prev => ({
      ...prev,
      [itemId]: {
        state: newState,
        progress: isComplete ? 100 : (isError ? prev[itemId]?.progress || 0 : prev[itemId]?.progress || 0),
        current_service: '',
        last_event_at: new Date().toISOString(),
        isLive: true,
        liveState: isError ? 'failed' : isComplete ? 'success' : 'working',
      }
    }));

    setItems(prev => prev.map(item => {
      if (item.id === itemId) {
        return {
          ...item,
          state: newState,
          progress: isComplete ? 100 : item.progress,
          last_event_at: new Date().toISOString(),
        };
      }
      return item;
    }));
  };

  const { isConnected, eventCount, error } = useMediaItemUpdates(
    handleItemUpdate,
    handleProgressUpdate,
    handleStateChange
  );

  // Update items when initialItems change
  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  // Merge live updates with base items for display
  const displayItems = useMemo(() => {
    return items.map(item => {
      const live = liveUpdates[item.id];
      if (live && live.isLive) {
        return {
          ...item,
          state: live.state,
          progress: live.progress,
          current_service: live.current_service || item.current_service,
          last_event_at: live.last_event_at,
          _liveState: live.liveState,
        };
      }
      return item;
    });
  }, [items, liveUpdates]);

  const getStateBadgeClass = (state: string, liveState?: string) => {
    const base = state.replace(/\s+/g, '_').toLowerCase();
    if (liveState) {
      return `state-badge ${base} live-${liveState}`;
    }
    return `state-badge ${base}`;
  };

  const getLiveIndicator = (liveState?: string) => {
    if (!liveState) return null;
    
    const indicators: Record<string, { label: string; class: string }> = {
      queued: { label: 'QUEUED', class: 'live-queued' },
      working: { label: 'WORKING', class: 'live-working' },
      progress: { label: 'IN PROGRESS', class: 'live-progress' },
      success: { label: 'COMPLETED', class: 'live-success' },
      failed: { label: 'FAILED', class: 'live-failed' },
      retrying: { label: 'RETRYING', class: 'live-retrying' },
      fallback: { label: 'FALLBACK', class: 'live-fallback' },
    };
    
    const ind = indicators[liveState];
    if (!ind) return null;
    
    return <span className={`live-indicator ${ind.class}`}>{ind.label}</span>;
  };

  return (
    <div className="live-pipeline-list">
      <div className="live-pipeline-header">
        <h3>Active Pipeline</h3>
        <div className="connection-status">
          <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`} />
          <span className="status-text">{isConnected ? 'LIVE' : 'OFFLINE'}</span>
          {eventCount > 0 && <span className="event-count">{eventCount} events</span>}
          {error && <span className="error-indicator">⚠</span>}
        </div>
      </div>
      
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
          {displayItems.length === 0 ? (
            <tr>
              <td colSpan={5} className="empty-state">
                No active items
              </td>
            </tr>
          ) : (
            displayItems.map((item) => {
              const live = liveUpdates[item.id];
              const liveState = (item as any)._liveState || live?.liveState;
              
              return (
                <tr 
                  key={item.id} 
                  onClick={() => onItemSelect(item.id)} 
                  className={live?.isLive ? 'live-updating' : ''}
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    <a href={`/item/${item.id}`}>
                      {item.title}
                      {item.season && item.episode && (
                        <span className="episode-marker">
                          S{item.season.toString().padStart(2, '0')}E{item.episode.toString().padStart(2, '0')}
                        </span>
                      )}
                    </a>
                    {getLiveIndicator(liveState)}
                  </td>
                  <td>
                    <span className={getStateBadgeClass(item.state, liveState)}>
                      {item.state.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td>
                    {item.progress !== undefined ? (
                      <>
                        <div className="progress-bar">
                          <div 
                            className={`progress-fill ${liveState || ''}`} 
                            style={{ width: `${item.progress}%` }} 
                          />
                          {liveState === 'progress' && (
                            <div className="progress-pulse" />
                          )}
                        </div>
                        <span className="progress-text">{item.progress}%</span>
                      </>
                    ) : (
                      <span className="no-progress">—</span>
                    )}
                  </td>
                  <td className="current-service">
                    {item.current_service || '—'}
                    {live?.isLive && <span className="live-dot" />}
                  </td>
                  <td className="last-activity">{formatTime(item.last_event_at)}</td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

export default LivePipelineList;