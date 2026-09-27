export interface MediaItem {
  id: string;
  media_type: 'movie' | 'episode';
  title: string;
  season?: number;
  episode?: number;
  tvdb_id?: string;
  tmdb_id?: string;
  imdb_id?: string;
  current_state: string;
  progress?: number;
  current_service?: string;
  last_event_at?: string;
  next_expected_state?: string;
  event_count: number;
  first_seen_at?: string;
}

export interface Event {
  id: number;
  timestamp: string;
  source_service: string;
  event_type: string;
  media_type: string;
  title: string;
  season?: number;
  episode?: number;
  correlation_key: string;
  status: string;
  error_message?: string;
}

export interface ServiceStatus {
  service: string;
  status: string;
  version?: string;
  error?: string;
}

export interface TimelineEvent {
  timestamp: string;
  source: string;
  event_type: string;
  status: string;
  error_message?: string;
  normalized_metadata?: Record<string, any>;
}

export interface ItemDetail extends MediaItem {
  timeline: TimelineEvent[];
  last_event?: TimelineEvent;
}

export interface Explanation {
  correlation_key: string;
  current_state: string;
  reason: string;
  evidence: string[];
  timeline_summary: string;
}

export interface SummaryCounts {
  active: number;
  attention: number;
  completed_today: number;
  failed: number;
}