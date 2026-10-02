"""Correlation package."""
from backend.correlation.engine import CorrelationEngine, get_correlation_engine
from backend.correlation.matching import match_torrent_to_media, find_candidate_events
from backend.correlation.state_machine import StateMachine

__all__ = [
    "CorrelationEngine",
    "get_correlation_engine",
    "match_torrent_to_media",
    "find_candidate_events",
    "StateMachine",
]