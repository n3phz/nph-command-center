/**
 * NPH Command Center - SSE Event Stream Hook
 * 
 * Manages Server-Sent Events connection for live dashboard updates.
 * Handles reconnection, event parsing, and state management.
 */

import { useEffect, useRef, useState, useCallback } from 'react';

export interface SSEEvent {
  event: string;
  data: Record<string, any>;
  id?: string;
  retry?: number;
}

export interface UseEventStreamOptions {
  enabled?: boolean;
  onEvent?: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onOpen?: () => void;
  onClose?: () => void;
  reconnectInterval?: number;
  maxRetries?: number;
}

export interface UseEventStreamReturn {
  isConnected: boolean;
  lastEvent: SSEEvent | null;
  error: Error | null;
  connect: () => void;
  disconnect: () => void;
  eventCount: number;
}

/**
 * Hook for managing SSE connection to /api/events/stream
 */
export function useEventStream(
  endpoint: string = '/api/events/stream',
  options: UseEventStreamOptions = {}
): UseEventStreamReturn {
  const {
    enabled = true,
    onEvent,
    onError,
    onOpen,
    onClose,
    reconnectInterval = 5000,
    maxRetries = -1, // -1 = infinite
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [eventCount, setEventCount] = useState(0);

  const eventSourceRef = useRef<EventSource | null>(null);
  const retryCountRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isIntentionalDisconnectRef = useRef(false);

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      return; // Already connected
    }

    if (!enabled) {
      return;
    }

    try {
      const es = new EventSource(endpoint);
      eventSourceRef.current = es;

      es.onopen = () => {
        setIsConnected(true);
        setError(null);
        retryCountRef.current = 0;
        onOpen?.();
      };

      es.onerror = () => {
        setIsConnected(false);
        const error = new Error('SSE connection error');
        setError(error);
        onError?.(error);

        // Handle reconnection
        if (!isIntentionalDisconnectRef.current) {
          scheduleReconnect();
        }
      };

      // Handle named events
      const eventTypes = [
        'item_update',
        'item_created',
        'item_state_change',
        'progress_update',
        'download_started',
        'download_progress',
        'download_completed',
        'download_failed',
        'import_started',
        'import_completed',
        'import_failed',
        'service_status_change',
        'alert_created',
        'alert_acknowledged',
        'alert_resolved',
        'heartbeat',
      ];

      eventTypes.forEach(eventType => {
        es.addEventListener(eventType, (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            const event: SSEEvent = {
              event: eventType,
              data,
              id: e.lastEventId || undefined,
            };
            setLastEvent(event);
            setEventCount(prev => prev + 1);
            onEvent?.(event);
          } catch (parseError) {
            console.warn('Failed to parse SSE event:', parseError);
          }
        });
      });

      // Handle default (unnamed) events
      es.onmessage = (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          const event: SSEEvent = {
            event: 'message',
            data,
            id: e.lastEventId || undefined,
          };
          setLastEvent(event);
          setEventCount(prev => prev + 1);
          onEvent?.(event);
        } catch (parseError) {
          console.warn('Failed to parse SSE message:', parseError);
        }
      };

    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to create EventSource');
      setError(error);
      onError?.(error);
      scheduleReconnect();
    }
  }, [endpoint, enabled, onEvent, onError, onOpen, onClose]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    if (maxRetries >= 0 && retryCountRef.current >= maxRetries) {
      setError(new Error('Max reconnection attempts reached'));
      return;
    }

    const delay = Math.min(reconnectInterval * Math.pow(1.5, retryCountRef.current), 30000);
    retryCountRef.current++;

    reconnectTimeoutRef.current = setTimeout(() => {
      connect();
    }, delay);
  }, [connect, maxRetries, reconnectInterval]);

  const disconnect = useCallback(() => {
    isIntentionalDisconnectRef.current = true;
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setIsConnected(false);
    onClose?.();
  }, [onClose]);

  // Auto-connect on mount and when enabled changes
  useEffect(() => {
    if (enabled) {
      connect();
    } else {
      disconnect();
    }

    return () => {
      disconnect();
    };
  }, [enabled, connect, disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  return {
    isConnected,
    lastEvent,
    error,
    connect,
    disconnect,
    eventCount,
  };
}

/**
 * Specialized hook for media item updates
 */
export function useMediaItemUpdates(
  onItemUpdate?: (itemId: string, data: Record<string, any>) => void,
  onProgressUpdate?: (itemId: string, progress: number, state: string) => void,
  onStateChange?: (itemId: string, newState: string, oldState: string | null) => void
) {
  const [itemEvents, setItemEvents] = useState<Record<string, SSEEvent>>({});

  const handleEvent = useCallback((event: SSEEvent) => {
    const itemId = event.data.item_id;
    if (!itemId) return;

    setItemEvents(prev => ({ ...prev, [itemId]: event }));

    switch (event.event) {
      case 'progress_update':
      case 'download_progress':
      case 'download_started':
        onProgressUpdate?.(itemId, event.data.progress || 0, event.data.state || event.event);
        break;
      case 'item_state_change':
      case 'download_completed':
      case 'download_failed':
      case 'import_completed':
      case 'import_failed':
      case 'available':
      case 'stuck':
        onStateChange?.(itemId, event.data.new_state || event.data.state || event.event, event.data.old_state || null);
        break;
      case 'item_update':
      case 'item_created':
      default:
        onItemUpdate?.(itemId, event.data);
        break;
    }
  }, [onItemUpdate, onProgressUpdate, onStateChange]);

  const stream = useEventStream('/api/events/stream', {
    onEvent: handleEvent,
  });

  return {
    ...stream,
    itemEvents,
    getItemEvent: (itemId: string) => itemEvents[itemId],
  };
}