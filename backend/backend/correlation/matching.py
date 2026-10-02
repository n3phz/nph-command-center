"""Matching utilities for correlating events."""
import re
from typing import List, Optional, Tuple
from datetime import datetime

from backend.adapters.base import RawEvent, SourceService, MediaType


def match_torrent_to_media(
    torrent_event: RawEvent,
    candidates: List[RawEvent]
) -> Optional[Tuple[RawEvent, RawEvent]]:
    """Match a qBittorrent torrent event to a potential Sonarr/Radarr event.
    
    Uses deterministic matching where possible:
    1. Match by source_download_id if available
    2. Match by title similarity (normalized)
    3. Match by TVDB/TMDB/IMDB ID from metadata
    """
    # Strategy 1: Direct hash match
    if torrent_event.source_download_id:
        for candidate in candidates:
            if candidate.correlation_key and torrent_event.source_download_id in candidate.correlation_key:
                return (torrent_event, candidate)
    
    # Strategy 2: Title normalization and matching
    torrent_title = _normalize_title(torrent_event.title)
    
    for candidate in candidates:
        candidate_title = _normalize_title(candidate.title)
        
        # Exact match
        if torrent_title == candidate_title:
            return (torrent_event, candidate)
        
        # Torrent name contains show/movie name
        if candidate_title in torrent_title or torrent_title in candidate_title:
            return (torrent_event, candidate)
        
        # Both contain common words
        torrent_words = set(re.findall(r'\w+', torrent_title))
        candidate_words = set(re.findall(r'\w+', candidate_title))
        
        if len(torrent_words) > 0 and len(candidate_words) > 0:
            common = torrent_words & candidate_words
            if len(common) >= min(3, len(candidate_words)):
                return (torrent_event, candidate)
    
    return None


def _normalize_title(title: str) -> str:
    """Normalize title for comparison."""
    # Lowercase and remove common punctuation
    normalized = title.lower().strip()
    normalized = re.sub(r'[._\-:]', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


def find_candidate_events(
    event: RawEvent,
    all_events: List[RawEvent],
    exclude_service: Optional[SourceService] = None
) -> List[RawEvent]:
    """Find candidate events that could be related to the given event."""
    candidates = []
    
    for candidate in all_events:
        if candidate.correlation_key == event.correlation_key:
            candidates.append(candidate)
        elif _titles_overlap(event.title, candidate.title):
            candidates.append(candidate)
    
    if exclude_service:
        candidates = [c for c in candidates if c.source_service != exclude_service]
    
    return candidates


def _titles_overlap(title1: str, title2: str) -> bool:
    """Check if two titles share significant overlap."""
    words1 = set(re.findall(r'\w+', title1.lower()))
    words2 = set(re.findall(r'\w+', title2.lower()))
    
    if not words1 or not words2:
        return False
    
    common = words1 & words2
    ratio = len(common) / max(len(words1), len(words2))
    
    # For cross-seed matching, be more lenient - check for SxxEyy pattern match
    # and at least 2 other common words
    sxxeyy1 = {w for w in words1 if re.match(r's\d{1,2}e\d{1,2}', w)}
    sxxeyy2 = {w for w in words2 if re.match(r's\d{1,2}e\d{1,2}', w)}
    
    if sxxeyy1 and sxxeyy2 and sxxeyy1 & sxxeyy2:
        # Episode pattern matches - check for additional common words
        other_common = common - sxxeyy1 - sxxeyy2
        return len(other_common) >= 2
    
    return ratio > 0.5 and len(common) >= 2