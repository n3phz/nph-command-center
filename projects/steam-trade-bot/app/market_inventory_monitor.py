"""
Phase 5F — Read-Only Tracked Inventory Profitability Monitor

Monitors tracked inventory items for profitability against current
Steam Market exit prices. For each marketable/tradable tracked item,
computes unrealized profit/loss based on verified acquisition costs
and current seller proceeds.

READ-ONLY:
- No database writes
- No Steam Market write operations
- No trade execution
- No automatic buying or selling

Economic model:
- acquisition_cost = unit_cost + acquisition_fee (from ledger)
- seller_proceeds = current market price / 100 (authoritative from Steam)
- expected_profit = seller_proceeds - all_in_cost
- Fees are already reflected in seller proceeds per Steam's data model.
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

STEAM_MARKET_SEARCH_RENDER_URL = "https://steamcommunity.com/market/search/render/"
DEFAULT_REQUEST_DELAY = 3.0


# ============================================================
# DATA CLASSES
# ============================================================


@dataclass(frozen=True, slots=True)
class InventoryItem:
    """A single inventory item from the snapshot."""

    market_hash_name: str
    appid: int
    classid: Optional[str]
    quantity: int
    tradable: bool
    marketable: bool
    asset_id: Optional[str] = None


@dataclass(frozen=True, slots=True)
class InventoryOpportunity:
    """Profitability analysis for a tracked inventory item."""

    market_hash_name: str
    appid: int
    classid: Optional[str]
    quantity: int
    bot_name: str

    # Acquisition side (from ledger)
    unit_cost: Optional[Decimal]
    acquisition_fee: Optional[Decimal]
    remaining_all_in_cost: Optional[Decimal]
    cost_status: str  # "TRACKED" or "UNKNOWN"

    # Exit side (from Steam Market)
    seller_proceeds_per_unit: Optional[Decimal]
    total_seller_proceeds: Optional[Decimal]
    active_listings: Optional[int]
    liquidity_evidence: str

    # Calculation
    expected_profit: Optional[Decimal]
    profit_margin: Optional[Decimal]
    classification: OpportunityClassification
    confidence: str
    reason: str

    timestamp: str
    data_sources: list = field(default_factory=list)

    @property
    def is_profitable(self) -> bool:
        return (
            self.expected_profit is not None
            and self.expected_profit > 0
            and self.classification == OpportunityClassification.VERIFIED_PROFITABLE
        )


@dataclass(frozen=True, slots=True)
class InventoryExclusion:
    """Reason why an inventory item was excluded from monitoring."""

    market_hash_name: str
    appid: int
    classid: Optional[str]
    reason: str
    category: str  # "NOT_MARKETABLE", "NO_ACQUISITION", "ZERO_REMAINING", etc.


@dataclass(frozen=True, slots=True)
class InventoryMonitorResult:
    """Complete result of inventory profitability monitoring."""

    bot_name: str
    evaluation_timestamp: str
    total_inventory_items: int
    eligible_items: int
    excluded_items: int
    opportunities: list[InventoryOpportunity]
    exclusions: list[InventoryExclusion]
    classification_counts: dict[str, int]

    @property
    def profitable_count(self) -> int:
        return sum(1 for o in self.opportunities if o.is_profitable)

    @property
    def loss_count(self) -> int:
        return sum(1 for o in self.opportunities if o.classification == OpportunityClassification.LOSS)

    @property
    def unverified_count(self) -> int:
        return sum(1 for o in self.opportunities if o.classification == OpportunityClassification.UNVERIFIED)


# ============================================================
# MONITOR CLASS
# ============================================================


class InventoryProfitabilityMonitor:
    """
    Read-only monitor for tracked inventory profitability.

    Evaluates inventory items against current Steam Market prices
    to determine unrealized profit/loss.
    """

    def __init__(
        self,
        db_path: str,
        session: requests.Session,
        request_delay: float = DEFAULT_REQUEST_DELAY,
        min_profit_threshold: Decimal = Decimal("0.01"),
        min_margin_threshold: Decimal = Decimal("0.10"),
    ):
        self.db_path = db_path
        self.session = session
        self.request_delay = request_delay
        self._last_request_time = 0.0
        self.scanner = MarketOpportunityScanner(
            db_path=db_path,
            steam_app_id=730,
            min_profit_threshold=min_profit_threshold,
            min_margin_threshold=min_margin_threshold,
        )

    def _wait_for_rate_limit(self) -> None:
        """Respect rate limits between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.monotonic()

    def get_inventory(self, bot_name: str) -> tuple[Optional[int], list[InventoryItem]]:
        """
        Get latest inventory snapshot for a bot.

        Returns (snapshot_id, items) or (None, []) if no snapshot.
        """
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            # Get latest snapshot
            snapshot = conn.execute(
                """
                SELECT id, bot_name, captured_at
                FROM inventory_snapshots
                WHERE bot_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (bot_name,),
            ).fetchone()

            if not snapshot:
                return None, []

            # Get inventory items
            rows = conn.execute(
                """
                SELECT
                    market_hash_name,
                    app_id,
                    class_id,
                    amount,
                    tradable,
                    marketable,
                    asset_id
                FROM inventory_items
                WHERE snapshot_id = ?
                ORDER BY market_hash_name
                """,
                (snapshot["id"],),
            ).fetchall()

            items = []
            for row in rows:
                items.append(InventoryItem(
                    market_hash_name=row["market_hash_name"],
                    appid=int(row["app_id"]),
                    classid=row["class_id"] if row["class_id"] else None,
                    quantity=int(row["amount"] or 0),
                    tradable=bool(row["tradable"]),
                    marketable=bool(row["marketable"]),
                    asset_id=row["asset_id"],
                ))

            return snapshot["id"], items

        finally:
            conn.close()

    def get_acquisition_cost(self, market_hash_name: str, bot_name: str) -> Optional[AcquisitionCost]:
        """
        Get acquisition cost for a tracked lot.

        Returns AcquisitionCost if TRACKED lot exists with remaining quantity,
        or None if not found or cost unknown.
        """
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            row = conn.execute(
                """
                SELECT
                    id,
                    source_transaction_id,
                    unit_cost,
                    acquisition_fee,
                    all_in_cost,
                    cost_status,
                    remaining_quantity
                FROM acquisition_lots
                WHERE market_hash_name = ?
                AND bot_name = ?
                AND cost_status = 'TRACKED'
                AND remaining_quantity > 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (market_hash_name, bot_name),
            ).fetchone()

            if row is None:
                return None

            unit_cost = Decimal(str(row["unit_cost"])) if row["unit_cost"] else None
            acquisition_fee = Decimal(str(row["acquisition_fee"])) if row["acquisition_fee"] else None
            all_in_cost = Decimal(str(row["all_in_cost"])) if row["all_in_cost"] else None

            # Calculate all_in_cost if not stored
            if all_in_cost is None and unit_cost is not None:
                all_in_cost = unit_cost
                if acquisition_fee is not None:
                    all_in_cost += acquisition_fee

            return AcquisitionCost(
                unit_cost=unit_cost,
                acquisition_fee=acquisition_fee,
                all_in_cost=all_in_cost,
                cost_status="TRACKED",
                source_transaction_id=row["source_transaction_id"],
            )

        finally:
            conn.close()

    def get_current_seller_proceeds(
        self,
        market_hash_name: str,
        appid: int = 730,
    ) -> tuple[Optional[Decimal], Optional[int]]:
        """
        Get current seller proceeds from Steam Market search.

        Returns (seller_proceeds_per_unit, active_listing_count).
        """
        try:
            params = {
                "appid": appid,
                "start": 0,
                "count": 1,
                "sort_column": "price",
                "sort_dir": "asc",
                "norender": 1,
            }
            self._wait_for_rate_limit()
            resp = self.session.get(
                STEAM_MARKET_SEARCH_RENDER_URL,
                params=params,
                timeout=30,
            )

            if resp.status_code != 200:
                return None, None

            data = resp.json()
            results = data.get("results", [])

            if not results:
                return None, None

            result = results[0]
            sell_price_cents = result.get("sell_price")

            if sell_price_cents is None or sell_price_cents <= 0:
                return None, None

            seller_proceeds = Decimal(int(sell_price_cents)) / Decimal(100)
            active_listings = int(result.get("sell_listings", 0))

            return seller_proceeds, active_listings

        except Exception:
            return None, None

    def monitor_inventory(
        self,
        bot_name: str,
        limit: int = 50,
    ) -> InventoryMonitorResult:
        """
        Monitor tracked inventory for profitability.

        Evaluates each marketable/tradable inventory item against
        its tracked acquisition cost and current market exit price.

        Returns InventoryMonitorResult with classification counts.
        """
        evaluation_timestamp = datetime.now(timezone.utc).isoformat()

        # Get inventory
        snapshot_id, items = self.get_inventory(bot_name)
        if not items:
            return InventoryMonitorResult(
                bot_name=bot_name,
                evaluation_timestamp=evaluation_timestamp,
                total_inventory_items=0,
                eligible_items=0,
                excluded_items=0,
                opportunities=[],
                exclusions=[],
                classification_counts={},
            )

        opportunities: list[InventoryOpportunity] = []
        exclusions: list[InventoryExclusion] = []

        for item in items:
            # Check marketability first
            if not item.marketable or not item.tradable:
                reason = "Item is not marketable or tradable on Steam."
                if not item.marketable:
                    reason = "Item is not marketable on Steam."
                elif not item.tradable:
                    reason = "Item is not tradable on Steam."
                exclusions.append(InventoryExclusion(
                    market_hash_name=item.market_hash_name,
                    appid=item.appid,
                    classid=item.classid,
                    reason=reason,
                    category="NOT_MARKETABLE",
                ))
                continue

            # Check remaining quantity (from inventory, not acquisition lot)
            if item.quantity <= 0:
                exclusions.append(InventoryExclusion(
                    market_hash_name=item.market_hash_name,
                    appid=item.appid,
                    classid=item.classid,
                    reason="No remaining quantity in inventory.",
                    category="ZERO_REMAINING",
                ))
                continue

            # Check for tracked acquisition cost
            acquisition = self.get_acquisition_cost(item.market_hash_name, bot_name)
            if acquisition is None:
                exclusions.append(InventoryExclusion(
                    market_hash_name=item.market_hash_name,
                    appid=item.appid,
                    classid=item.classid,
                    reason="No tracked acquisition cost found.",
                    category="NO_ACQUISITION",
                ))
                continue

            # Get current seller proceeds
            seller_proceeds, active_listings = self.get_current_seller_proceeds(
                item.market_hash_name,
                item.appid,
            )

            if seller_proceeds is None:
                # Missing market data - still evaluate with known cost
                opportunities.append(InventoryOpportunity(
                    market_hash_name=item.market_hash_name,
                    appid=item.appid,
                    classid=item.classid,
                    quantity=item.quantity,
                    bot_name=bot_name,
                    unit_cost=acquisition.unit_cost,
                    acquisition_fee=acquisition.acquisition_fee,
                    remaining_all_in_cost=acquisition.all_in_cost,
                    cost_status=acquisition.cost_status,
                    seller_proceeds_per_unit=None,
                    total_seller_proceeds=None,
                    active_listings=None,
                    liquidity_evidence=LiquidityEvidence.INSUFFICIENT_DATA.value,
                    expected_profit=None,
                    profit_margin=None,
                    classification=OpportunityClassification.UNVERIFIED,
                    confidence="LOW",
                    reason="Current seller proceeds not available.",
                    timestamp=evaluation_timestamp,
                    data_sources=["accounting_database"],
                ))
                continue

            # Calculate economics
            remaining_all_in = acquisition.all_in_cost or Decimal("0")
            seller_per_unit = seller_proceeds
            total_proceeds = seller_per_unit * item.quantity

            expected_profit = total_proceeds - remaining_all_in
            profit_margin = (
                expected_profit / remaining_all_in
                if remaining_all_in > 0
                else Decimal("0")
            )

            # Classify
            classification, confidence, reason = self._classify_inventory_opportunity(
                marketable=item.marketable,
                tradable=item.tradable,
                seller_proceeds_verified=seller_per_unit is not None and seller_per_unit > 0,
                acquisition_cost_verified=acquisition.cost_status == "TRACKED" and remaining_all_in > 0,
                expected_profit=expected_profit,
                profit_margin=profit_margin,
                active_listings=active_listings,
            )

            opportunities.append(InventoryOpportunity(
                market_hash_name=item.market_hash_name,
                appid=item.appid,
                classid=item.classid,
                quantity=item.quantity,
                bot_name=bot_name,
                unit_cost=acquisition.unit_cost,
                acquisition_fee=acquisition.acquisition_fee,
                remaining_all_in_cost=remaining_all_in,
                cost_status=acquisition.cost_status,
                seller_proceeds_per_unit=seller_per_unit,
                total_seller_proceeds=total_proceeds,
                active_listings=active_listings,
                liquidity_evidence=self._classify_liquidity(active_listings),
                expected_profit=expected_profit,
                profit_margin=profit_margin,
                classification=classification,
                confidence=confidence,
                reason=reason,
                timestamp=evaluation_timestamp,
                data_sources=["steam_market_search_api", "accounting_database"],
            ))

            if len(opportunities) >= limit:
                break

        # Count classifications
        classification_counts = {}
        for opp in opportunities:
            cls = opp.classification.value
            classification_counts[cls] = classification_counts.get(cls, 0) + 1

        return InventoryMonitorResult(
            bot_name=bot_name,
            evaluation_timestamp=evaluation_timestamp,
            total_inventory_items=len(items),
            eligible_items=len(opportunities),
            excluded_items=len(exclusions),
            opportunities=opportunities,
            exclusions=exclusions,
            classification_counts=classification_counts,
        )

    @staticmethod
    def _classify_inventory_opportunity(
        marketable: bool,
        tradable: bool,
        seller_proceeds_verified: bool,
        acquisition_cost_verified: bool,
        expected_profit,
        profit_margin,
        active_listings,
    ) -> tuple:
        """Classify an inventory opportunity."""
        # Not marketable
        if not marketable or not tradable:
            return (
                OpportunityClassification.NOT_MARKETABLE,
                "HIGH",
                "Item is not marketable or tradable on Steam.",
            )

        # Missing critical evidence
        if not seller_proceeds_verified:
            return (
                OpportunityClassification.UNVERIFIED,
                "LOW",
                "Seller proceeds could not be verified.",
            )

        if not acquisition_cost_verified:
            return (
                OpportunityClassification.UNVERIFIED,
                "LOW",
                "Acquisition cost not verified; cannot establish profitability.",
            )

        # Have all evidence — calculate profit
        if expected_profit is None:
            return (
                OpportunityClassification.UNVERIFIED,
                "LOW",
                "Profit calculation failed.",
            )

        if expected_profit < 0:
            return (
                OpportunityClassification.LOSS,
                "HIGH",
                f"Expected loss of {expected_profit:.2f} EUR.",
            )

        if expected_profit == 0:
            return (
                OpportunityClassification.BREAK_EVEN,
                "MEDIUM",
                "Break-even opportunity.",
            )

        # Positive profit — check thresholds
        min_margin_threshold = Decimal("0.10")
        is_verifiable = (
            active_listings is not None and active_listings >= 2
            and profit_margin is not None
            and profit_margin >= min_margin_threshold
        )

        if is_verifiable:
            return (
                OpportunityClassification.VERIFIED_PROFITABLE,
                "HIGH",
                f"Verified profitable: +{expected_profit:.2f} EUR ({profit_margin:.1%} margin).",
            )

        return (
            OpportunityClassification.POTENTIALLY_PROFITABLE,
            "MEDIUM",
            f"Positive spread: +{expected_profit:.2f} EUR but insufficient evidence for verification.",
        )

    @staticmethod
    def _classify_liquidity(active_listings) -> str:
        """Classify liquidity evidence level."""
        if active_listings is None:
            return LiquidityEvidence.INSUFFICIENT_DATA.value

        if active_listings >= 5:
            return LiquidityEvidence.HIGH_EVIDENCE.value

        if active_listings >= 2:
            return LiquidityEvidence.MEDIUM_EVIDENCE.value

        return LiquidityEvidence.LOW_EVIDENCE.value


def create_monitor(
    db_path: str,
    session: requests.Session,
    **kwargs,
) -> InventoryProfitabilityMonitor:
    """Factory function to create an InventoryProfitabilityMonitor."""
    return InventoryProfitabilityMonitor(
        db_path=db_path,
        session=session,
        **kwargs,
    )
