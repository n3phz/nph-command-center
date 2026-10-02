/**
 * NPH Command Center - Command Palette
 * 
 * Global search interface with keyboard navigation.
 * Activated via ⌘K or / key.
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { searchAll } from '../../services/command-center';
import type { SearchResult } from '../../types/infrastructure';
import './CommandPalette.css';

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [groupedResults, setGroupedResults] = useState<Record<string, SearchResult[]>>({});
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Focus input on open
  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
      setQuery('');
      setResults([]);
      setGroupedResults({});
      setSelectedIndex(0);
      setError(null);
    }
  }, [open]);

  // Handle search with debounce
  useEffect(() => {
    if (!open) return;
    
    const timeoutId = setTimeout(async () => {
      if (!query.trim()) {
        setResults([]);
        setGroupedResults({});
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const data = await searchAll(query);
        setResults(data);
        
        // Group results by type
        const grouped = data.reduce((acc, result) => {
          if (!acc[result.type]) acc[result.type] = [];
          acc[result.type].push(result);
          return acc;
        }, {} as Record<string, SearchResult[]>);
        
        setGroupedResults(grouped);
        setSelectedIndex(0);
      } catch (err) {
        setError('Search failed');
      } finally {
        setLoading(false);
      }
    }, 150);

    return () => clearTimeout(timeoutId);
  }, [query, open]);

  // Keyboard navigation
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      const totalResults = results.length;
      
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setSelectedIndex(prev => Math.min(prev + 1, totalResults - 1));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setSelectedIndex(prev => Math.max(prev - 1, 0));
          break;
        case 'Enter':
          e.preventDefault();
          if (results[selectedIndex]) {
            handleSelect(results[selectedIndex]);
          }
          break;
        case 'Escape':
          onClose();
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, results, selectedIndex, onClose]);

  // Scroll selected item into view
  useEffect(() => {
    if (!open || !listRef.current) return;
    
    const selectedElement = listRef.current.querySelector('[data-selected="true"]');
    if (selectedElement) {
      selectedElement.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex, open]);

  const handleSelect = useCallback((result: SearchResult) => {
    if (result.url) {
      window.location.href = result.url;
    }
    onClose();
  }, [onClose]);

  const getTypeIcon = (type: string) => {
    const icons: Record<string, string> = {
      service: '⚙️',
      host: '🖥️',
      project: '📁',
      alert: '⚠️',
      activity: '📋',
    };
    return icons[type] || '📦';
  };

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      service: 'Services',
      host: 'Hosts',
      project: 'Projects',
      alert: 'Alerts',
      activity: 'Activity',
    };
    return labels[type] || type;
  };

  if (!open) return null;

  const flatResults = useMemo(() => 
    Object.entries(groupedResults).flatMap(([type, items]) => 
      items.map(item => ({ ...item, _group: type }))
    ), [groupedResults]
  );

  return (
    <div className="command-palette-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="command-palette" onClick={e => e.stopPropagation()} role="search">
        <div className="command-palette-header">
          <div className="command-palette-input-wrapper">
            <svg className="command-palette-search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              className="command-palette-input"
              placeholder="Search services, hosts, projects, alerts..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              aria-label="Search"
              aria-expanded={results.length > 0}
              aria-controls="command-palette-results"
            />
            <kbd className="command-palette-shortcut">⌘K</kbd>
          </div>
          {loading && (
            <div className="command-palette-loading" aria-live="polite">
              <span className="spinner" />
              <span>Searching...</span>
            </div>
          )}
        </div>

        <div 
          id="command-palette-results"
          className="command-palette-results"
          ref={listRef}
          role="listbox"
          aria-label="Search results"
        >
          {error && (
            <div className="command-palette-error" role="alert">
              {error}
            </div>
          )}

          {query.trim() && !loading && !error && flatResults.length === 0 && (
            <div className="command-palette-empty">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="11" cy="11" r="8" />
                <path d="M21 21l-4.35-4.35" />
              </svg>
              <span>No results for "{query}"</span>
            </div>
          )}

          {flatResults.map((result, index) => (
            <div
              key={`${result._group}-${result.id}`}
              className={`command-palette-item ${index === selectedIndex ? 'selected' : ''}`}
              data-selected={index === selectedIndex}
              role="option"
              aria-selected={index === selectedIndex}
              onClick={() => handleSelect(result)}
              onMouseEnter={() => setSelectedIndex(index)}
            >
              <span className="command-palette-item-icon">{getTypeIcon(result.type)}</span>
              <div className="command-palette-item-content">
                <div className="command-palette-item-title">{result.title}</div>
                <div className="command-palette-item-subtitle">{result.subtitle}</div>
              </div>
              <span className="command-palette-item-type">{getTypeLabel(result.type)}</span>
              {result.metadata && Object.keys(result.metadata).length > 0 && (
                <div className="command-palette-item-meta">
                  {Object.entries(result.metadata).slice(0, 2).map(([k, v]) => (
                    <span key={k} className="meta-tag">{k}: {v != null ? String(v) : ''}</span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {!query.trim() && !loading && (
            <div className="command-palette-hints">
              <h4>Quick Actions</h4>
              <div className="hint-grid">
                <span className="hint"><kbd>⌘K</kbd> Open command palette</span>
                <span className="hint"><kbd>/</kbd> Quick search</span>
                <span className="hint"><kbd>Esc</kbd> Close</span>
              </div>
              <h4>Navigate</h4>
              <div className="hint-grid">
                <span className="hint"><kbd>↑</kbd><kbd>↓</kbd> Select result</span>
                <span className="hint"><kbd>Enter</kbd> Open</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
