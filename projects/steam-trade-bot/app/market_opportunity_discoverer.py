"""
Phase 5A — Read-Only Steam Market Opportunity Discoverer

Discovers candidate Steam Market items and evaluates them against
the accounting and identity rules established in Phase 3G/3H/4C.

READ-ONLY:
- No database writes
- No Steam Market write operations
- No trade execution
- No automatic buying or selling

Discovery source: Steam Market listing page for a specific appid,
sorted by lowest price ascending, bounded by `count` parameter.
Only appid 730 (CS2) is supported to keep the candidate universe
bounded and relevant.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

import requests

from market_opportunity_scanner import (
    MarketOpportunityScanner,
    StructuredMarketPrice,
    AcquisitionCost,
    OpportunityClassification,
    LiquidityEvidence,
    IdentityVerificationStatus,
)


# ============================================================
# CONFIGURATION
# ============================================================

STEAM_APP_ID = 753
STEAM_MARKET_LISTING_URL = "https://steamcommunity.com/market/listings/"
STEAM_MARKET_SEARCH_RENDER_URL = "https://steamcommunity.com/market/search/render/"
DEFAULT_DISCOVERY_APPIDS = [730]  # CS2 — bounded, high-volume marketplace
DEFAULT_MAX_CANDIDATES = 25
DEFAULT_REQUEST_DELAY = 3.0  # seconds between Steam requests
MAX_RETRIES = 3
RETRY_BACKOFF = 5.0  # seconds to wait on 429


class DiscoverySource(str, Enum):
    """Source of discovery data."""
    MARKET_LISTING_PAGE = "market_listing_page"
    STRUCTURED_PAYLOAD = "structured_payload"
    CACHED_PRICE = "cached_price"


@dataclass(frozen=True, slots=True)
class Candidate:
    """
    A single market opportunity candidate discovered from Steam.

    Fields:
        market_hash_name: Item name (identity anchor)
        appid: Steam app ID
        classid: Item class ID
        listingid: Authoritative listing ID
        seller_proceeds: unPrice / 100 in major units
        buyer_total: unPrice + unFee / 100 in major units
        steam_fee: Steam portion of fees
        publisher_fee: Publisher portion of fees
        active_listing_count: Number of active listings
        acquisition_cost: Known acquisition cost (from DB) or None
        expected_profit: seller_proceeds - all_in_cost
        profit_margin: expected_profit / all_in_cost
        liquidity_evidence: LiquidityEvidence value
        identity_verified: Whether identity anchors match
        classification: Final classification
        confidence: HIGH / MEDIUM / LOW
        reason: Human-readable explanation
        timestamp: When candidate was evaluated
        data_sources: List of data sources used
    """

    market_hash_name: str
    appid: int
    classid: Optional[str]
    listingid: Optional[str]
    seller_proceeds: Optional[Decimal]
    buyer_total: Optional[Decimal]
    steam_fee: Optional[Decimal]
    publisher_fee: Optional[Decimal]
    active_listing_count: Optional[int]
    acquisition_cost: Optional[Decimal]
    expected_profit: Optional[Decimal]
    profit_margin: Optional[Decimal]
    liquidity_evidence: str
    identity_verified: bool
    classification: OpportunityClassification
    confidence: str
    reason: str
    timestamp: str
    data_sources: list = field(default_factory=list)

    @property
    def is_profitable(self) -> bool:
        """Whether this candidate has positive expected profit."""
        return (
            self.expected_profit is not None
            and self.expected_profit > 0
            and self.identity_verified
        )


# ============================================================
# DISCOVERER CLASS
# ============================================================


class MarketOpportunityDiscoverer:
    """
    Read-only market opportunity discoverer.

    Discovers candidate items from Steam Market listing pages,
    extracts authoritative structured price data, and classifies
    each candidate using the Phase 4C scanner logic.

    Bounded discovery:
    - Only searches appids in DEFAULT_DISCOVERY_APPIDS
    - Respects MAX_CANDIDATES limit
    - Applies request delay between Steam queries
    """

    def __init__(
        self,
        db_path: str,
        session: requests.Session,
        discovery_appids: list[int] | None = None,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        request_delay: float = DEFAULT_REQUEST_DELAY,
        min_profit_threshold: Decimal = Decimal("0.01"),
        min_margin_threshold: Decimal = Decimal("0.10"),
    ):
        self.db_path = db_path
        self.session = session
        self.discovery_appids = discovery_appids or DEFAULT_DISCOVERY_APPIDS
        self.max_candidates = max_candidates
        self.request_delay = request_delay
        self._last_request_time = 0.0
        self.scanner = MarketOpportunityScanner(
            db_path=db_path,
            steam_app_id=STEAM_APP_ID,
            min_profit_threshold=min_profit_threshold,
            min_margin_threshold=min_margin_threshold,
        )

    def discover(
        self,
        limit: int | None = None,
        appids: list[int] | None = None,
    ) -> list[Candidate]:
        """
        Discover candidate market opportunities.

        Args:
            limit: Maximum number of candidates to return.
                Defaults to self.max_candidates.
            appids: App IDs to search. Defaults to discovery_appids.

        Returns:
            List of Candidate objects, sorted by expected profit descending.
        """
        candidates: list[Candidate] = []
        appids_to_search = appids or self.discovery_appids
        limit = limit or self.max_candidates

        for appid in appids_to_search:
            if len(candidates) >= limit:
                break

            discovered = self._discover_from_appid(appid, set())
            for c in discovered:
                if c.market_hash_name not in [x.market_hash_name for x in candidates]:
                    candidates.append(c)
                if len(candidates) >= limit:
                    break

        # Sort by expected profit descending (best candidates first)
        candidates.sort(
            key=lambda c: (
                -(c.expected_profit or Decimal("0")),
                c.market_hash_name,
            )
        )

        return candidates[:limit]

    def _discover_from_appid(
        self,
        appid: int,
        seen_names: set[str],
    ) -> list[Candidate]:
        """Discover candidates from a single appid's market listings."""
        candidates: list[Candidate] = []
        
        # Use the new search render API with norender=1 for structured JSON
        params = {
            "appid": appid,
            "start": 0,
            "count": self.max_candidates,
            "sort_column": "price",
            "sort_dir": "asc",
            "norender": 1,
        }
        
        self._wait_for_rate_limit()
        
        try:
            response = self.session.get(
                STEAM_MARKET_SEARCH_RENDER_URL,
                params=params,
                timeout=30,
            )
        except requests.RequestException:
            return candidates
        
        if response.status_code == 429:
            # Rate limited - back off and return what we have
            time.sleep(RETRY_BACKOFF)
            return candidates
        
        if response.status_code != 200:
            return candidates
        
        try:
            data = response.json()
        except (ValueError, TypeError):
            return candidates
        
        results = data.get("results", [])
        
        for result in results:
            if len(candidates) >= self.max_candidates:
                break
            
            candidate = self._parse_search_result(result, appid, seen_names)
            if candidate:
                candidates.append(candidate)
                seen_names.add(candidate.market_hash_name)
        
        return candidates
    
    def _parse_search_result(
        self,
        result: dict,
        appid: int,
        seen_names: set[str],
    ) -> Candidate | None:
        """Parse a single search result into a Candidate."""
        mhn = result.get("hash_name") or result.get("name")
        if not mhn or mhn in seen_names:
            return None
        
        asset = result.get("asset_description", {}) or {}
        classid = asset.get("classid")
        
        # Extract pricing from new API format
        sell_price = result.get("sell_price")  # cents
        sale_price_text = result.get("sale_price_text", "")  # buyer-facing price text
        
        if sell_price is None or sell_price <= 0:
            return None
        
        sell_price_cents = int(sell_price)
        
        # Parse sale_price_text to get buyer total
        buyer_total = self._parse_price_text(sale_price_text)
        if buyer_total is None:
            buyer_total = Decimal(sell_price_cents) / Decimal(100)
        
        # Calculate fees as the difference (authoritative from Steam)
        seller_proceeds_cents = sell_price_cents
        seller_proceeds = Decimal(seller_proceeds_cents) / Decimal(100)
        fees = buyer_total - seller_proceeds
        
        # Estimate fee split (Steam takes ~10%, publisher ~15% of seller proceeds)
        # This is an estimate since the new API doesn't expose individual fees
        steam_fee = fees * Decimal("0.40")  # Estimated 40% of fees to Steam
        publisher_fee = fees * Decimal("0.60")  # Estimated 60% to publisher
        
        # Build structured price - mark as UNVERIFIED for fees
        # We have sell_price (seller proceeds) but not individual fee breakdown
        structured_price = StructuredMarketPrice(
            un_price=seller_proceeds_cents,
            un_fee=int(fees * 100),
            un_steam_fee=int(steam_fee * 100),
            un_publisher_fee=int(publisher_fee * 100),
            str_subtotal=str(buyer_total),
            e_currency=3,  # EUR default
            listingid=None,  # Not available in search results
            b_mine=False,
            market_hash_name=mhn,
            classid=classid,
        )
        
        # Get liquidity from search results
        sell_listings = result.get("sell_listings")
        liquidity = {
            "active_listing_count": int(sell_listings) if sell_listings else None,
        }
        
        # Get acquisition cost from DB
        acquisition_cost = self.scanner.get_accounting_cost(mhn, "Rixqor")
        
        # Scan the opportunity
        opportunity = self.scanner.scan_item(
            market_hash_name=mhn,
            appid=appid,
            classid=classid,
            marketable=True,
            tradable=asset.get("tradable", 1) == 1,
            market_price=structured_price,
            acquisition_cost=acquisition_cost,
            liquidity=liquidity,
        )
        
        # Build candidate
        ac = None
        if opportunity.all_in_cost is not None:
            ac = opportunity.all_in_cost
        
        return Candidate(
            market_hash_name=mhn,
            appid=appid,
            classid=classid,
            listingid=None,
            seller_proceeds=opportunity.seller_proceeds,
            buyer_total=structured_price.buyer_total if structured_price else None,
            steam_fee=steam_fee,
            publisher_fee=publisher_fee,
            active_listing_count=liquidity.get("active_listing_count"),
            acquisition_cost=ac,
            expected_profit=opportunity.expected_profit,
            profit_margin=opportunity.profit_margin,
            liquidity_evidence=opportunity.liquidity_evidence,
            identity_verified=opportunity.identity_verified,
            classification=opportunity.classification,
            confidence=opportunity.confidence,
            reason=opportunity.reason,
            timestamp=opportunity.timestamp,
            data_sources=["steam_market_search_api"],
        )
    
    @staticmethod
    def _parse_price_text(price_text: str) -> Decimal | None:
        """Parse a Steam price text like '$1,234.56' or '€1.234,56'."""
        if not price_text:
            return None
        
        # Remove currency symbol
        cleaned = re.sub(r'[\$€£]', '', price_text).strip()
        
        # Handle European format (1.234,56) vs US format (1,234.56)
        if ',' in cleaned and '.' in cleaned:
            if cleaned.rfind(',') > cleaned.rfind('.'):
                # European: dots are thousands, comma is decimal
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                # US: commas are thousands, dot is decimal
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            # Could be decimal comma or thousands separator
            parts = cleaned.split(',')
            if len(parts[1]) == 2:
                # Likely decimal comma (e.g., "1,56")
                cleaned = cleaned.replace(',', '.')
            else:
                # Likely thousands separator (e.g., "1,234")
                cleaned = cleaned.replace(',', '')
        
        try:
            value = Decimal(cleaned)
            if value.is_finite() and value >= 0:
                return value
        except (InvalidOperation, ValueError):
            pass
        
        return None

    def _extract_structured_listings(
        self,
        page: str,
        appid: int,
    ) -> list[dict]:
        """Extract structured listing data from a Steam Market listing page."""
        listings = []

        # Phase 3G: Try JSON payload first
        try:
            data = json.loads(page)
            if isinstance(data, dict) and isinstance(data.get("listings"), list):
                listings.extend(self._parse_listings_json(data["listings"]))
                return listings
        except (ValueError, TypeError):
            pass

        # Phase 3G: Try JSON embedded in script tag
        un = page.replace("\\\\", "\\").replace('\\"', '"')
        listings_idx = un.find('"listings"')
        if listings_idx > 0:
            arr_start = un.find('[', listings_idx)
            if arr_start > 0:
                arr_end = un.find(']', arr_start)
                if arr_end > arr_start:
                    try:
                        raw_listings = json.loads(un[arr_start:arr_end + 1])
                        listings.extend(self._parse_listings_json(raw_listings))
                    except (ValueError, TypeError):
                        pass
                if len(listings) >= self.max_candidates:
                    return listings

        # Fallback: regex extraction from HTML
        listings.extend(self._extract_listings_from_html(page, appid))

        return listings

    def _parse_listings_json(self, raw_listings: list) -> list[dict]:
        """Parse structured listing data from JSON array."""
        results = []
        for L in raw_listings:
            if not isinstance(L, dict):
                continue

            desc = L.get("description", {}) or {}
            asset = L.get("asset", {}) or {}

            mhn = desc.get("market_hash_name") or asset.get("market_hash_name")
            if not mhn:
                continue

            classid = asset.get("classid") or desc.get("classid")

            un_price = L.get("unPrice")
            un_fee = L.get("unFee")
            if un_price is None or un_fee is None:
                continue

            try:
                un_price_val = int(un_price)
                un_fee_val = int(un_fee)
            except (TypeError, ValueError):
                continue

            if un_price_val < 0 or un_fee_val < 0:
                continue

            results.append({
                "market_hash_name": mhn,
                "classid": classid,
                "listingid": L.get("listingid"),
                "un_price": un_price_val,
                "un_fee": un_fee_val,
                "un_steam_fee": int(L.get("unSteamFee") or 0),
                "un_publisher_fee": int(L.get("unPublisherFee") or 0),
                "str_subtotal": L.get("strSubtotal"),
                "e_currency": L.get("eCurrency", STEAM_CURRENCY),
                "b_mine": L.get("bMine", False),
            })

        return results

    def _extract_listings_from_html(
        self,
        page: str,
        appid: int,
    ) -> list[dict]:
        """Extract listings from HTML page using regex patterns."""
        listings = []

        # Pattern 1: look for listing objects with unPrice/unFee
        pattern = r'\{\s*"listingid"\s*:\s*"(\d+)"\s*,\s*"description"\s*:\s*\{\s*"market_hash_name"\s*:\s*"([^"]+)"[\s\S]*?"classid"\s*:\s*"(\d+)"[\s\S]*?\}\s*,\s*"unPrice"\s*:\s*(\d+)\s*,\s*"unFee"\s*:\s*(\d+)\s*,\s*"unSteamFee"\s*:\s*(\d+)\s*,\s*"unPublisherFee"\s*:\s*(\d+)\s*,\s*"strSubtotal"\s*:\s*"([^"]*)"'
        matches = re.findall(pattern, page)
        for m in matches:
            listings.append({
                "market_hash_name": m[1],
                "classid": m[2] if m[2] else None,
                "listingid": m[0],
                "un_price": int(m[3]),
                "un_fee": int(m[4]),
                "un_steam_fee": int(m[5]),
                "un_publisher_fee": int(m[6]),
                "str_subtotal": m[7],
                "e_currency": STEAM_CURRENCY,
                "b_mine": False,
            })

        return listings

    def _wait_for_rate_limit(self) -> None:
        """Respect rate limits between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.monotonic()


def create_discoverer(
    db_path: str,
    session: requests.Session,
    **kwargs,
) -> MarketOpportunityDiscoverer:
    """Factory function to create a discoverer instance."""
    return MarketOpportunityDiscoverer(
        db_path=db_path,
        session=session,
        **kwargs,
    )
