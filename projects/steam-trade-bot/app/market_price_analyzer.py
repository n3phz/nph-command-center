"""
Phase 5E — Read-Only Steam Market Price Analyzer

Analyzes authoritative Steam Market data sources to identify potential
acquisition edges. This module is READ-ONLY:
- No database writes
- No Steam Market write operations
- No trade execution
- No automatic buying or selling

Data sources investigated:
1. Price Overview API — lowest market price (buyer-facing)
2. Search Render API — sell listings with pricing and quantity
3. Market History API — completed transactions (requires purchases)

LIMITATIONS ESTABLISHED:
- Buy order book: NOT ACCESSIBLE via authenticated API
- Price history: NOT ACCESSIBLE via public API
- Order book depth: NOT ACCESSIBLE

ACQUISITION EDGE CONCLUSION:
Profitable opportunities require acquisition BELOW market price.
The bot must track acquisition costs and compare against sell prices.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import requests


# ============================================================
# CONFIGURATION
# ============================================================

STEAM_MARKET_PRICE_OVERVIEW_URL = "https://steamcommunity.com/market/priceoverview/"
STEAM_MARKET_SEARCH_RENDER_URL = "https://steamcommunity.com/market/search/render/"
STEAM_MARKET_HISTORY_URL = "https://steamcommunity.com/market/myhistory/render/"

DEFAULT_REQUEST_DELAY = 3.0
MAX_RETRIES = 3
RETRY_BACKOFF = 5.0


# ============================================================
# DATA CLASSES
# ============================================================


@dataclass(frozen=True, slots=True)
class PriceOverview:
    """Lowest market price from Price Overview API."""
    
    market_hash_name: str
    appid: int
    currency: int
    lowest_price: Optional[str]
    lowest_price_value: Optional[Decimal]
    success: bool
    error: Optional[str] = None
    
    @property
    def is_available(self) -> bool:
        return self.success and self.lowest_price_value is not None


@dataclass(frozen=True, slots=True)
class SellListing:
    """A sell listing from Search Render API."""
    
    market_hash_name: str
    appid: int
    classid: Optional[str]
    sell_price_cents: int
    sale_price_text: str
    sell_listings: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True, slots=True)
class PriceSpread:
    """Spread between buyer price and seller proceeds."""
    
    market_hash_name: str
    appid: int
    seller_proceeds: Decimal
    buyer_total: Decimal
    fees: Decimal
    fee_percentage: Decimal
    active_listings: int
    classification: str  # "UNVERIFIED", "LOSS", etc.
    reason: str


@dataclass(frozen=True, slots=True)
class AcquisitionEdge:
    """Analysis of potential acquisition opportunity."""
    
    market_hash_name: str
    appid: int
    classid: Optional[str]
    
    # Acquisition side (what we pay)
    acquisition_cost: Optional[Decimal] = None
    acquisition_source: Optional[str] = None  # "tracked_cost", "buy_order", "listing"
    
    # Exit side (what we receive)
    exit_proceeds: Optional[Decimal] = None
    exit_source: Optional[str] = None  # "sell_listing", "buy_order"
    
    # Economic analysis
    expected_profit: Optional[Decimal] = None
    expected_margin: Optional[Decimal] = None
    fees: Optional[Decimal] = None
    fee_percentage: Optional[Decimal] = None
    
    # Classification
    classification: str = "UNVERIFIED"
    confidence: str = "LOW"
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Data sources used
    data_sources: list = field(default_factory=list)
    
    @property
    def is_profitable(self) -> bool:
        return (
            self.expected_profit is not None
            and self.expected_profit > 0
            and self.classification == "VERIFIED_PROFITABLE"
        )
    
    @property
    def is_verified(self) -> bool:
        return self.classification in ("VERIFIED_PROFITABLE", "POTENTIALLY_PROFITABLE")


# ============================================================
# ANALYZER CLASS
# ============================================================


class MarketPriceAnalyzer:
    """
    Read-only analyzer of Steam Market data sources.
    
    Investigates authoritative pricing data to identify potential
    acquisition edges. Does NOT execute any trades.
    """
    
    def __init__(
        self,
        session: requests.Session,
        request_delay: float = DEFAULT_REQUEST_DELAY,
    ):
        self.session = session
        self.request_delay = request_delay
        self._last_request_time = 0.0
    
    def _wait_for_rate_limit(self) -> None:
        """Respect rate limits between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.monotonic()
    
    def get_price_overview(
        self,
        market_hash_name: str,
        appid: int = 730,
        currency: int = 3,
    ) -> PriceOverview:
        """
        Get lowest market price from Price Overview API.
        
        Returns PriceOverview with lowest_price (buyer-facing).
        """
        try:
            params = {
                "appid": appid,
                "currency": currency,
                "market_hash_name": market_hash_name,
            }
            self._wait_for_rate_limit()
            resp = self.session.get(
                STEAM_MARKET_PRICE_OVERVIEW_URL,
                params=params,
                timeout=15,
            )
            
            if resp.status_code != 200:
                return PriceOverview(
                    market_hash_name=market_hash_name,
                    appid=appid,
                    currency=currency,
                    lowest_price=None,
                    lowest_price_value=None,
                    success=False,
                    error=f"HTTP {resp.status_code}",
                )
            
            data = resp.json()
            
            lowest_price = data.get("lowest_price")
            lowest_price_value = self._parse_price_text(lowest_price)
            
            return PriceOverview(
                market_hash_name=market_hash_name,
                appid=appid,
                currency=currency,
                lowest_price=lowest_price,
                lowest_price_value=lowest_price_value,
                success=data.get("success", False),
            )
        except Exception as e:
            return PriceOverview(
                market_hash_name=market_hash_name,
                appid=appid,
                currency=currency,
                lowest_price=None,
                lowest_price_value=None,
                success=False,
                error=str(e),
            )
    
    def get_sell_listings(
        self,
        appid: int = 730,
        limit: int = 10,
        sort_column: str = "price",
        sort_dir: str = "asc",
    ) -> list[SellListing]:
        """
        Get sell listings from Search Render API.
        
        Returns list of SellListing objects with pricing and quantity.
        """
        listings = []
        
        try:
            params = {
                "appid": appid,
                "start": 0,
                "count": limit,
                "sort_column": sort_column,
                "sort_dir": sort_dir,
                "norender": 1,
            }
            self._wait_for_rate_limit()
            resp = self.session.get(
                STEAM_MARKET_SEARCH_RENDER_URL,
                params=params,
                timeout=30,
            )
            
            if resp.status_code != 200:
                return listings
            
            data = resp.json()
            results = data.get("results", [])
            
            for result in results:
                mhn = result.get("hash_name") or result.get("name")
                if not mhn:
                    continue
                
                sell_price = result.get("sell_price")
                if sell_price is None or sell_price <= 0:
                    continue
                
                asset = result.get("asset_description", {}) or {}
                classid = asset.get("classid")
                
                listings.append(SellListing(
                    market_hash_name=mhn,
                    appid=appid,
                    classid=classid,
                    sell_price_cents=int(sell_price),
                    sale_price_text=result.get("sale_price_text", ""),
                    sell_listings=int(result.get("sell_listings", 0)),
                ))
                
                if len(listings) >= limit:
                    break
                    
        except Exception:
            pass
        
        return listings
    
    def get_market_history(
        self,
        start: int = 0,
        count: int = 10,
    ) -> dict:
        """
        Get recent market history (completed transactions).
        
        Requires authenticated session with purchased items.
        Returns dict with events, listings, assets.
        """
        try:
            params = {
                "start": start,
                "count": count,
                "norender": 1,
            }
            self._wait_for_rate_limit()
            resp = self.session.get(
                STEAM_MARKET_HISTORY_URL,
                params=params,
                timeout=30,
            )
            
            if resp.status_code != 200:
                return {"success": False, "error": f"HTTP {resp.status_code}"}
            
            return resp.json()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def analyze_spread(
        self,
        market_hash_name: str,
        appid: int,
        seller_proceeds: Decimal,
        buyer_total: Decimal,
        active_listings: int,
    ) -> PriceSpread:
        """
        Analyze the spread between seller proceeds and buyer total.
        
        Calculates fees and fee percentage.
        """
        fees = buyer_total - seller_proceeds
        fee_pct = (fees / buyer_total * 100) if buyer_total > 0 else Decimal("0")
        
        # Determine classification based on spread
        if fees < 0:
            # Negative fees (rounding artifact at low prices)
            classification = "UNVERIFIED"
            reason = f"Negative fees ({fees}) due to rounding at low price tier"
        elif fees == 0:
            classification = "BREAK_EVEN"
            reason = "No fees detected (unlikely in production)"
        else:
            classification = "LOSS"
            reason = f"Buyer pays ${float(buyer_total):.2f}, seller receives ${float(seller_proceeds):.2f}, fees=${float(fees):.2f} ({float(fee_pct):.1f}%)"
        
        return PriceSpread(
            market_hash_name=market_hash_name,
            appid=appid,
            seller_proceeds=seller_proceeds,
            buyer_total=buyer_total,
            fees=fees,
            fee_percentage=fee_pct,
            active_listings=active_listings,
            classification=classification,
            reason=reason,
        )
    
    def analyze_acquisition_edge(
        self,
        market_hash_name: str,
        appid: int,
        classid: Optional[str],
        acquisition_cost: Optional[Decimal],
        exit_price: Optional[Decimal],
        exit_fee_estimate: Optional[Decimal] = None,
    ) -> AcquisitionEdge:
        """
        Analyze potential acquisition opportunity.
        
        Compares acquisition cost against exit proceeds.
        """
        # Need both acquisition and exit prices
        if acquisition_cost is None or exit_price is None:
            return AcquisitionEdge(
                market_hash_name=market_hash_name,
                appid=appid,
                classid=classid,
                acquisition_cost=acquisition_cost,
                exit_proceeds=exit_price,
                classification="UNVERIFIED",
                reason="Missing acquisition cost or exit price",
                confidence="LOW",
            )
        
        # Calculate exit proceeds after fees
        if exit_fee_estimate is None:
            # Estimate 15% total fee
            exit_fee_estimate = exit_price * Decimal("0.15")
        
        net_exit = exit_price - exit_fee_estimate
        profit = net_exit - acquisition_cost
        margin = (profit / acquisition_cost * 100) if acquisition_cost > 0 else Decimal("0")
        
        # Classify
        if profit <= 0:
            classification = "LOSS"
            reason = f"Loss of ${float(-profit):.2f} after estimated fees"
            confidence = "HIGH"
        elif margin < Decimal("10"):
            classification = "POTENTIALLY_PROFITABLE"
            reason = f"Profit ${float(profit):.2f} ({float(margin):.1f}%), below 10% threshold"
            confidence = "MEDIUM"
        else:
            classification = "VERIFIED_PROFITABLE"
            reason = f"Profit ${float(profit):.2f} ({float(margin):.1f}%)"
            confidence = "HIGH"
        
        return AcquisitionEdge(
            market_hash_name=market_hash_name,
            appid=appid,
            classid=classid,
            acquisition_cost=acquisition_cost,
            exit_proceeds=exit_price,
            expected_profit=profit,
            expected_margin=margin,
            fees=exit_fee_estimate,
            fee_percentage=Decimal("15.0"),  # Estimated
            classification=classification,
            reason=reason,
            confidence=confidence,
            data_sources=["estimated_fees"],
        )
    
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
            if value.is_finite() and value >= 0:
                return value
        except (InvalidOperation, ValueError):
            pass
        
        return None


def create_analyzer(session: requests.Session, **kwargs) -> MarketPriceAnalyzer:
    """Factory function to create a MarketPriceAnalyzer."""
    return MarketPriceAnalyzer(session=session, **kwargs)
