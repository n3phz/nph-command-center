import { MediaItem, Event, ServiceStatus, Explanation } from '../types'

const API_BASE = '/api'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options)
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  // Health
  health: () => request('/health'),
  ready: () => request('/ready'),
  
  // Items
  getItems: (params?: { state?: string; media_type?: string; limit?: number; offset?: number }) => {
    const search = new URLSearchParams()
    if (params?.state) search.append('state', params.state)
    if (params?.media_type) search.append('media_type', params.media_type)
    if (params?.limit) search.append('limit', params.limit.toString())
    if (params?.offset) search.append('offset', params.offset.toString())
    return request<MediaItem[]>(`/items${search.toString() ? `?${search}` : ''}`)
  },
  
  getItem: (id: string) => request(`/items/${id}`),
  
  getItemTimeline: (id: string) => request(`/items/${id}/timeline`),
  
  getItemExplanation: (id: string) => request<Explanation>(`/items/${id}/explain`),
  
  // Events
  getEvents: (params?: { limit?: number; offset?: number; source_service?: string; event_type?: string }) => {
    const search = new URLSearchParams()
    if (params?.limit) search.append('limit', params.limit.toString())
    if (params?.offset) search.append('offset', params.offset.toString())
    if (params?.source_service) search.append('source_service', params.source_service)
    if (params?.event_type) search.append('event_type', params.event_type)
    return request<Event[]>(`/events${search.toString() ? `?${search}` : ''}`)
  },
  
  // Services
  getServices: () => request<ServiceStatus[]>('/services'),
  
  forcePoll: () => request('/services/poll', { method: 'POST' }),
}