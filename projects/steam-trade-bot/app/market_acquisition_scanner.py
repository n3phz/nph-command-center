"""
Phase 6A — Read-Only Acquisition Opportunity Scanner

Discovers Steam Market items and evaluates whether buying now at
current buyer-facing prices and later selling could produce a positive
economic return, after Steam fees and accounting for liquidity.

This module is READ-ONLY:
- No database writes
- No Steam Market write operations
- No trade execution
- No automatic buying or selling

Economic model:
  round_trip_profit = seller_proceeds - buyer_acquisition_cost
  round_trip_margin = round_trip_profit / buyer_acquisition_cost

Where:
  - buyer_acquisition_cost = the price a buyer pays per unit (authoritative)
  - seller_proceeds = the price the seller receives per unit (authoritative)
  - Steam fees are embedded in the relationship between the two

Data sources:
  - /market/search/render/?norender=1 → structured listings with pricing
  - /market/priceoverview/ → lowest market price (buyer-facing)

LIMITATIONS:
  - Buy order book data is NOT available via authenticated API
  - Price history is NOT available via public API
  - We work with visible listing prices, not executed trade prices
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import requests

from market_opportunity_scanner import (
    OpportunityClassification,
    LiquidityEvidence,
    IdentityVerificationStatus,
)


# ============================================================
# CONFIGURATION
# ============================================================

STEAM_MARKET_SEARCH_RENDER_URL = "https://steamcommunity.com/market/search/render/"
STEAM_MARKET_PRICE_OVERVIEW_URL = "https://steamcommunity.com/market/priceoverview/"

DEFAULT_REQUEST_DELAY = 3.0
DEFAULT_MAX_CANDIDATES = 25
DEFAULT_MIN_MARGIN_THRESHOLD = Decimal("0.10")  # 10%
DEFAULT_MIN_PRICE = Decimal("0.01")
DEFAULT_MAX_PRICE = Decimal("1000.00")
DEFAULT_MIN_LISTINGS = 2


# ============================================================
# ENUMS
# ============================================================


class EconomicEvidence:
    """Quality of economic data."""
    AUTHORITATIVE = "AUTHORITATIVE"
    ESTIMATED = "ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


class AcquisitionClassification(str):
    """Classification of an acquisition opportunity."""
    DIRECT_ROUND_TRIP_EDGE = "DIRECT_ROUND_TRIP_EDGE"
    POTENTIAL_RESALE_EDGE = "POTENTIAL_RESALE_EDGE"
    PRICE_ANOMALY = "PRICE_ANOMALY"
    UNVERIFIED = "UNVERIFIED"
    LOSS = "LOSS"
    BREAK_EVEN = "BREAK_EVEN"
    NOT_MARKETABLE = "NOT_MARKETABLE"


# ============================================================
# DATA CLASSES
# ============================================================


@dataclass(frozen=True, slots=True)
class BuyerPrice:
    """Authoritative buyer-facing price data."""
    market_hash_name: str
    appid: int
    classid: Optional[str]
    buyer_total: Decimal  # Price buyer pays
    buyer_total_text: Optional[str]
    source: EconomicEvidence  # AUTHORITATIVE or ESTIMATED
    listing_count: Optional[int] = None


@dataclass(frozen=True, slots=True)
class SellerProceeds:
    """Authoritative seller proceeds data."""
    market_hash_name: str
    appid: int
    classid: Optional[str]
    seller_proceeds: Decimal  # Price seller receives
    seller_proceeds_text: Optional[str]
    source: EconomicEvidence
    active_listings: Optional[int] = None


@dataclass(frozen=True, slots=True)
class AcquisitionCandidate:
    """A single acquisition opportunity candidate."""
    
    # Identity
    market_hash_name: str
    appid: int
    classid: Optional[str]
    
    # Economics
    buyer_acquisition_cost: Optional[Decimal]
    buyer_acquisition_source: EconomicEvidence
    seller_proceeds_per_unit: Optional[Decimal]
    seller_proceeds_source: EconomicEvidence
    
    # Calculations
    round_trip_profit: Optional[Decimal]
    round_trip_margin: Optional[Decimal]
    steam_fees: Optional[Decimal]
    steam_fee_percentage: Optional[Decimal]
    
    # Liquidity
    active_listings: Optional[int]
    liquidity_evidence: str
    
    # Classification
    classification: AcquisitionClassification
    confidence: str  # HIGH, MEDIUM, LOW
    reason: str
    evidence: str  # AUTHORITATIVE, ESTIMATED, UNAVAILABLE
    
    # Metadata
    timestamp: str
    data_sources: list = field(default_factory=list)
    
    @property
    def is_profitable(self) -> bool:
        return (
            self.round_trip_profit is not None
            and self.round_trip_profit > 0
            and self.classification in (
                AcquisitionClassification.DIRECT_ROUND_TRIP_EDGE,
                AcquisitionClassification.POTENTIAL_RESALE_EDGE,
            )
        )


@dataclass(frozen=True, slots=True)
class AcquisitionSearchResult:
    """Complete result of an acquisition opportunity scan."""
    
    timestamp: str
    search_params: dict
    candidates_evaluated: int
    candidates_accepted: int
    candidates_rejected: int
    candidates: list[AcquisitionCandidate]
    classification_counts: dict[str, int]
    rate_limited: bool = False
    
    @property
    def profitable_count(self) -> int:
        return sum(1 for c in self.candidates if c.is_profitable)
    
    @property
    def verified_count(self) -> int:
        return sum(
            1 for c in self.candidates
            if c.classification == AcquisitionClassification.DIRECT_ROUND_TRIP_EDGE
        )


# ============================================================
# SCANNER CLASS
# ============================================================


class MarketAcquisitionScanner:
    """
    Read-only scanner for acquisition opportunities.
    
    Discovers Steam Market items and evaluates whether the current
    buyer-facing price presents a profitable round-trip opportunity
    compared to seller proceeds.
    """
    
    def __init__(
        self,
        session: requests.Session,
        request_delay: float = DEFAULT_REQUEST_DELAY,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        min_margin_threshold: Decimal = DEFAULT_MIN_MARGIN_THRESHOLD,
        min_price: Decimal = DEFAULT_MIN_PRICE,
        max_price: Decimal = DEFAULT_MAX_PRICE,
        min_listings: int = DEFAULT_MIN_LISTINGS,
    ):
        self.session = session
        self.request_delay = request_delay
        self.max_candidates = max_candidates
        self.min_margin_threshold = min_margin_threshold
        self.min_price = min_price
        self.max_price = max_price
        self.min_listings = min_listings
        self._last_request_time = 0.0
    
    def _wait_for_rate_limit(self) -> None:
        """Respect rate limits between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.monotonic()
    
    def discover_candidates(
        self,
        appid: int = 730,
        limit: int = DEFAULT_MAX_CANDIDATES,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        min_listings: Optional[int] = None,
    ) -> AcquisitionSearchResult:
        """
        Discover acquisition candidates from Steam Market.
        
        Args:
            appid: Steam app ID to search (default: 730 for CS2)
            limit: Maximum number of candidates to evaluate
            min_price: Minimum buyer price to consider
            max_price: Maximum buyer price to consider
            min_listings: Minimum active listings for liquidity
        
        Returns:
            AcquisitionSearchResult with classified candidates
        """
        evaluation_timestamp = datetime.now(timezone.utc).isoformat()
        min_price = min_price or self.min_price
        max_price = max_price or self.max_price
        min_listings = min_listings or self.min_listings
        
        params = {
            "appid": appid,
            "start": 0,
            "count": limit,
            "sort_column": "price",
            "sort_dir": "asc",
            "norender": 1,
        }
        
        candidates: list[AcquisitionCandidate] = []
        seen_names: set[str] = set()
        evaluated = 0
        rejected = 0
        rate_limited = False
        
        try:
            self._wait_for_rate_limit()
            resp = self.session.get(
                STEAM_MARKET_SEARCH_RENDER_URL,
                params=params,
                timeout=30,
            )
        except requests.RequestException as e:
            return AcquisitionSearchResult(
                timestamp=evaluation_timestamp,
                search_params=params,
                candidates_evaluated=0,
                candidates_accepted=0,
                candidates_rejected=0,
                candidates=[],
                classification_counts={},
                rate_limited=False,
            )
        
        if resp.status_code == 429:
            rate_limited = True
            return AcquisitionSearchResult(
                timestamp=evaluation_timestamp,
                search_params=params,
                candidates_evaluated=0,
                candidates_accepted=0,
                candidates_rejected=0,
                candidates=[],
                classification_counts={},
                rate_limited=True,
            )
        
        if resp.status_code != 200:
            return AcquisitionSearchResult(
                timestamp=evaluation_timestamp,
                search_params=params,
                candidates_evaluated=0,
                candidates_accepted=0,
                candidates_rejected=0,
                candidates=[],
                classification_counts={},
                rate_limited=False,
            )
        
        try:
            data = resp.json()
        except (ValueError, TypeError):
            return AcquisitionSearchResult(
                timestamp=evaluation_timestamp,
                search_params=params,
                candidates_evaluated=0,
                candidates_accepted=0,
                candidates_rejected=0,
                candidates=[],
                classification_counts={},
                rate_limited=False,
            )
        
        results = data.get("results", [])
        
        for result in results:
            if evaluated >= limit:
                break
            
            candidate = self._parse_search_result(result, appid, seen_names)
            if candidate is None:
                continue
            
            evaluated += 1
            
            # Apply filters
            if candidate.buyer_acquisition_cost is None:
                rejected += 1
                continue
            
            if candidate.buyer_acquisition_cost < min_price:
                rejected += 1
                continue
            
            if candidate.buyer_acquisition_cost > max_price:
                rejected += 1
                continue
            
            if candidate.active_listings is not None and candidate.active_listings < min_listings:
                rejected += 1
                continue
            
            # Check profitability thresholds
            if candidate.round_trip_profit is not None and candidate.round_trip_profit <= 0:
                # Still include losses for visibility
                pass
            
            candidates.append(candidate)
        
        # Count classifications
        classification_counts = {}
        for c in candidates:
            cls = c.classification
            classification_counts[cls] = classification_counts.get(cls, 0) + 1
        
        return AcquisitionSearchResult(
            timestamp=evaluation_timestamp,
            search_params=params,
            candidates_evaluated=evaluated,
            candidates_accepted=len(candidates),
            candidates_rejected=rejected,
            candidates=candidates,
            classification_counts=classification_counts,
            rate_limited=rate_limited,
        )
    
    def _parse_search_result(
        self,
        result: dict,
        appid: int,
        seen_names: set[str],
    ) -> Optional[AcquisitionCandidate]:
        """Parse a single Steam Market search result into a candidate."""
        mhn = result.get("hash_name") or result.get("name")
        if not mhn or mhn in seen_names:
            return None
        
        seen_names.add(mhn)
        
        asset = result.get("asset_description", {}) or {}
        classid = asset.get("classid")
        tradable = asset.get("tradable", 0)
        marketable = asset.get("marketable", 0)
        
        # Check marketability
        if not tradable or not marketable:
            return AcquisitionCandidate(
                market_hash_name=mhn,
                appid=appid,
                classid=classid,
                buyer_acquisition_cost=None,
                buyer_acquisition_source=EconomicEvidence.UNAVAILABLE,
                seller_proceeds_per_unit=None,
                seller_proceeds_source=EconomicEvidence.UNAVAILABLE,
                round_trip_profit=None,
                round_trip_margin=None,
                steam_fees=None,
                steam_fee_percentage=None,
                active_listings=None,
                liquidity_evidence=LiquidityEvidence.INSUFFICIENT_DATA,
                classification=AcquisitionClassification.NOT_MARKETABLE,
                confidence="HIGH",
                reason="Item is not marketable or tradable on Steam.",
                evidence=EconomicEvidence.UNAVAILABLE,
                timestamp=datetime.now(timezone.utc).isoformat(),
                data_sources=["steam_market_search"],
            )
        
        # Extract pricing
        sell_price_cents = result.get("sell_price")
        sale_price_text = result.get("sale_price_text", "")
        buy_price_text = result.get("buy_price_text", "")
        sell_listings = result.get("sell_listings")
        
        # Parse seller proceeds (what seller receives)
        seller_proceeds = None
        seller_proceeds_source = EconomicEvidence.UNAVAILABLE
        if sell_price_cents is not None and sell_price_cents > 0:
            seller_proceeds = Decimal(int(sell_price_cents)) / Decimal(100)
            seller_proceeds_source = EconomicEvidence.AUTHORITATIVE
        
        # Parse buyer price (what buyer pays)
        buyer_cost = None
        buyer_source = EconomicEvidence.UNAVAILABLE
        buyer_total_text = sale_price_text or buy_price_text
        
        if sale_price_text:
            parsed = self._parse_price_text(sale_price_text)
            if parsed is not None and parsed > 0:
                buyer_cost = parsed
                buyer_source = EconomicEvidence.AUTHORITATIVE
        elif buy_price_text:
            parsed = self._parse_price_text(buy_price_text)
            if parsed is not None and parsed > 0:
                buyer_cost = parsed
                buyer_source = EconomicEvidence.AUTHORITATIVE
        
        # Calculate round-trip economics
        round_trip_profit = None
        round_trip_margin = None
        steam_fees = None
        fee_percentage = None
        
        if buyer_cost is not None and seller_proceeds is not None:
            round_trip_profit = seller_proceeds - buyer_cost
            if buyer_cost > 0:
                round_trip_margin = round_trip_profit / buyer_cost
            steam_fees = buyer_cost - seller_proceeds
            if buyer_cost > 0:
                fee_percentage = (steam_fees / buyer_cost) * Decimal(100)
        
        # Determine liquidity
        active_listings = int(sell_listings) if sell_listings else None
        liquidity_evidence = self._classify_liquidity(active_listings)
        
        # Classify opportunity
        classification, confidence, reason, evidence = self._classify_candidate(
            buyer_cost=buyer_cost,
            seller_proceeds=seller_proceeds,
            round_trip_profit=round_trip_profit,
            round_trip_margin=round_trip_margin,
            liquidity_evidence=liquidity_evidence,
            active_listings=active_listings,
            buyer_source=buyer_source,
            seller_source=seller_proceeds_source,
        )
        
        return AcquisitionCandidate(
            market_hash_name=mhn,
            appid=appid,
            classid=classid,
            buyer_acquisition_cost=buyer_cost,
            buyer_acquisition_source=buyer_source,
            seller_proceeds_per_unit=seller_proceeds,
            seller_proceeds_source=seller_proceeds_source,
            round_trip_profit=round_trip_profit,
            round_trip_margin=round_trip_margin,
            steam_fees=steam_fees,
            steam_fee_percentage=fee_percentage,
            active_listings=active_listings,
            liquidity_evidence=liquidity_evidence,
            classification=classification,
            confidence=confidence,
            reason=reason,
            evidence=evidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data_sources=["steam_market_search"],
        )
    
    def _classify_candidate(
        self,
        buyer_cost: Optional[Decimal],
        seller_proceeds: Optional[Decimal],
        round_trip_profit: Optional[Decimal],
        round_trip_margin: Optional[Decimal],
        liquidity_evidence: str,
        active_listings: Optional[int],
        buyer_source: EconomicEvidence,
        seller_source: EconomicEvidence,
    ) -> tuple:
        """Classify an acquisition candidate."""
        # Missing critical evidence
        if buyer_source == EconomicEvidence.UNAVAILABLE or seller_source == EconomicEvidence.UNAVAILABLE:
            return (
                AcquisitionClassification.UNVERIFIED,
                "LOW",
                "Missing authoritative price data.",
                EconomicEvidence.UNAVAILABLE,
            )
        
        if buyer_cost is None or seller_proceeds is None:
            return (
                AcquisitionClassification.UNVERIFIED,
                "LOW",
                "Could not parse price data.",
                EconomicEvidence.UNAVAILABLE,
            )
        
        # Calculate profit
        if round_trip_profit is None:
            return (
                AcquisitionClassification.UNVERIFIED,
                "LOW",
                "Profit calculation failed.",
                EconomicEvidence.ESTIMATED,
            )
        
        # Loss or price anomaly
        if round_trip_profit <= 0:
            if round_trip_profit < 0:
                return (
                    AcquisitionClassification.LOSS,
                    "HIGH",
                    f"Round-trip loss: -{abs(round_trip_profit):.2f} EUR",
                    EconomicEvidence.AUTHORITATIVE,
                )
            else:
                return (
                    AcquisitionClassification.BREAK_EVEN,
                    "MEDIUM",
                    "Break-even opportunity.",
                    EconomicEvidence.AUTHORITATIVE,
                )
        
        # Price anomaly: seller proceeds exceed buyer cost (economically impossible)
        if seller_proceeds > buyer_cost:
            return (
                AcquisitionClassification.PRICE_ANOMALY,
                "HIGH",
                f"Seller proceeds ({seller_proceeds:.2f}) exceed buyer cost ({buyer_cost:.2f}); Steam price fields require independent settlement evidence",
                EconomicEvidence.AUTHORITATIVE,
            )
        
        # Positive profit — check thresholds
        is_verifiable = (
            round_trip_margin is not None
            and round_trip_margin >= self.min_margin_threshold
            and liquidity_evidence in (
                LiquidityEvidence.HIGH_EVIDENCE,
                LiquidityEvidence.MEDIUM_EVIDENCE,
            )
        )
        
        if is_verifiable:
            return (
                AcquisitionClassification.DIRECT_ROUND_TRIP_EDGE,
                "HIGH",
                f"Verified edge: +{round_trip_profit:.2f} EUR ({round_trip_margin:.1%} margin)",
                EconomicEvidence.AUTHORITATIVE,
            )
        
        # Positive but insufficient evidence
        return (
            AcquisitionClassification.POTENTIAL_RESALE_EDGE,
            "MEDIUM",
            f"Positive spread: +{round_trip_profit:.2f} EUR but insufficient evidence for verification",
            EconomicEvidence.ESTIMATED,
        )
    
    def _classify_liquidity(self, active_listings: Optional[int]) -> str:
        """Classify liquidity evidence level."""
        if active_listings is None:
            return LiquidityEvidence.INSUFFICIENT_DATA
        
        if active_listings >= 10:
            return LiquidityEvidence.HIGH_EVIDENCE
        
        if active_listings >= 5:
            return LiquidityEvidence.MEDIUM_EVIDENCE
        
        if active_listings >= 2:
            return LiquidityEvidence.LOW_EVIDENCE
        
        return LiquidityEvidence.INSUFFICIENT_DATA
    
    @staticmethod
    def _parse_price_text(price_text: str) -> Optional[Decimal]:
        """Parse a Steam price text like '$1,234.56' or '€1.234,56'."""
        if not price_text:
            return None
        
        cleaned = re.sub(r'[\$€£]', '', price_text).strip()
        
        if ',' in cleaned and '.' in cleaned:
            if cleaned.rfind(',') > cleaned.rfind('.'):
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            parts = cleaned.split(',')
            if len(parts[1]) == 2:
                cleaned = cleaned.replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        
        try:
            value = Decimal(cleaned)
            if value.is_finite() and value > 0:
                return value
        except (InvalidOperation, ValueError):
            pass
        
        return None


def create_scanner(
    session: requests.Session,
    **kwargs,
) -> MarketAcquisitionScanner:
    """Factory function to create a MarketAcquisitionScanner."""
    return MarketAcquisitionScanner(
        session=session,
        **kwargs,
    )
