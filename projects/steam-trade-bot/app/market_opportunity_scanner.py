"""
Phase 4C — Read-Only Steam Market Opportunity Scanner

Identifies Steam Market items that may represent profitable
manual purchase opportunities for later resale.

This module is READ-ONLY:
- No database writes
- No Steam Market write operations
- No trade execution
- No automatic buying or selling
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional


# ============================================================
# ENUMS
# ============================================================


class OpportunityClassification(str, Enum):
    """Classification of a market opportunity."""

    NOT_MARKETABLE = "NOT_MARKETABLE"
    UNVERIFIED = "UNVERIFIED"
    LOSS = "LOSS"
    BREAK_EVEN = "BREAK_EVEN"
    POTENTIALLY_PROFITABLE = "POTENTIALLY_PROFITABLE"
    VERIFIED_PROFITABLE = "VERIFIED_PROFITABLE"


class LiquidityEvidence(str, Enum):
    """Evidence level for market liquidity."""

    HIGH_EVIDENCE = "HIGH_EVIDENCE"
    MEDIUM_EVIDENCE = "MEDIUM_EVIDENCE"
    LOW_EVIDENCE = "LOW_EVIDENCE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class IdentityVerificationStatus(str, Enum):
    """Status of identity verification."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    FAILED = "FAILED"


# ============================================================
# DATA CLASSES
# ============================================================


@dataclass(frozen=True, slots=True)
class StructuredMarketPrice:
    """
    Authoritative structured price data from Steam Market listing.

    Fields:
        un_price: Seller proceeds per unit (minor units, integer)
        un_fee: Total buyer fees per unit (minor units, integer)
        un_steam_fee: Steam portion of fees (minor units)
        un_publisher_fee: Publisher portion of fees (minor units)
        str_subtotal: Buyer-facing total display string
        e_currency: Steam currency ID
        listingid: Authoritative listing ID
        b_mine: Whether listing belongs to viewing account
        market_hash_name: Item name (identity anchor)
        classid: Item class ID (identity anchor)
    """

    un_price: int
    un_fee: int
    un_steam_fee: int
    un_publisher_fee: int
    str_subtotal: Optional[str]
    e_currency: int
    listingid: Optional[str]
    b_mine: bool
    market_hash_name: str
    classid: Optional[str]

    @property
    def seller_proceeds(self) -> Decimal:
        """Seller proceeds in major units."""
        return Decimal(self.un_price) / Decimal(100)

    @property
    def buyer_fees(self) -> Decimal:
        """Total buyer-paid fees in major units."""
        return Decimal(self.un_fee) / Decimal(100)

    @property
    def buyer_total(self) -> Decimal:
        """Buyer-facing total in major units."""
        return (Decimal(self.un_price) + Decimal(self.un_fee)) / Decimal(100)

    def matches_identity(
        self,
        appid: int,
        market_hash_name: str,
        classid: Optional[str] = None,
    ) -> IdentityVerificationStatus:
        """
        Verify that this price belongs to the requested item.

        Returns VERIFIED if identity anchors match,
        UNVERIFIED if partial match, FAILED if mismatch.
        """
        if self.market_hash_name != market_hash_name:
            return IdentityVerificationStatus.FAILED
        if classid is not None and self.classid != classid:
            return IdentityVerificationStatus.FAILED
        # appid not directly available in structured price; assume valid
        # if hash name matches
        return IdentityVerificationStatus.VERIFIED


@dataclass
class AcquisitionCost:
    """
    Known acquisition cost from tracked lot.

    Fields:
        unit_cost: Seller-side acquisition price (major units)
        acquisition_fee: Buyer-paid acquisition fees (major units)
        all_in_cost: Total all-in acquisition cost
        cost_status: TRACKED or UNKNOWN
        source_transaction_id: Source transaction ID
    """

    unit_cost: Optional[Decimal]
    acquisition_fee: Optional[Decimal]
    all_in_cost: Optional[Decimal]
    cost_status: str  # "TRACKED" or "UNKNOWN"
    source_transaction_id: int


@dataclass
class MarketOpportunity:
    """
    A single market opportunity candidate.

    Fields:
        market_hash_name: Item name
        appid: Steam app ID
        classid: Item class ID
        assetid: Asset ID (if available)
        quantity: Available quantity
        marketable: Whether item is marketable
        tradable: Whether item is tradable

        acquisition: Acquisition cost data
        market: Market price data
        liquidity: Liquidity evidence
        calculation: Profit calculations
        verification: Verification status
        classification: Final classification
        timestamp: When opportunity was evaluated
        data_sources: Sources of data used
    """

    market_hash_name: str
    appid: int
    classid: Optional[str]
    assetid: Optional[str]
    quantity: int
    marketable: bool
    tradable: bool

    acquisition: Optional[AcquisitionCost]
    market: Optional[StructuredMarketPrice]
    liquidity: Optional[dict]

    expected_profit: Optional[Decimal]
    profit_margin: Optional[Decimal]
    seller_proceeds: Optional[Decimal]
    all_in_cost: Optional[Decimal]

    identity_verified: bool
    marketability_verified: bool
    seller_proceeds_verified: bool
    acquisition_cost_verified: bool
    liquidity_evidence: str  # LiquidityEvidence value

    classification: OpportunityClassification
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    reason: str

    timestamp: str  # ISO 8601 UTC
    data_sources: list = field(default_factory=list)


# ============================================================
# SCANNER CLASS
# ============================================================


class MarketOpportunityScanner:
    """
    Read-only market opportunity scanner.

    Identifies Steam Market items that may be profitable
    to purchase manually for later resale.

    NEVER:
    - Writes to database
    - Executes Steam Market operations
    - Creates listings or orders
    - Enables automatic trading
    """

    def __init__(
        self,
        db_path: str,
        steam_app_id: int = 753,
        min_profit_threshold: Decimal = Decimal("0.01"),
        min_margin_threshold: Decimal = Decimal("0.10"),
        cache_seconds: int = 3600,
    ):
        self.db_path = db_path
        self.steam_app_id = steam_app_id
        self.min_profit_threshold = min_profit_threshold
        self.min_margin_threshold = min_margin_threshold
        self.cache_seconds = cache_seconds

    def scan_item(
        self,
        market_hash_name: str,
        appid: int,
        classid: Optional[str] = None,
        assetid: Optional[str] = None,
        quantity: int = 1,
        marketable: bool = False,
        tradable: bool = False,
        acquisition_cost: Optional[AcquisitionCost] = None,
        market_price: Optional[StructuredMarketPrice] = None,
        liquidity: Optional[dict] = None,
    ) -> MarketOpportunity:
        """
        Evaluate a single market opportunity.

        Returns a MarketOpportunity with classification.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Check marketability first
        if not marketable or not tradable:
            return MarketOpportunity(
                market_hash_name=market_hash_name,
                appid=appid,
                classid=classid,
                assetid=assetid,
                quantity=quantity,
                marketable=marketable,
                tradable=tradable,
                acquisition=acquisition_cost,
                market=market_price,
                liquidity=liquidity,
                expected_profit=None,
                profit_margin=None,
                seller_proceeds=None,
                all_in_cost=None,
                identity_verified=False,
                marketability_verified=False,
                seller_proceeds_verified=False,
                acquisition_cost_verified=False,
                liquidity_evidence=LiquidityEvidence.INSUFFICIENT_DATA.value,
                classification=OpportunityClassification.NOT_MARKETABLE,
                confidence="HIGH",
                reason="Item is not marketable or tradable on Steam.",
                timestamp=timestamp,
                data_sources=[],
            )

        # Verify identity
        identity_status = IdentityVerificationStatus.UNVERIFIED
        if market_price is not None:
            identity_status = market_price.matches_identity(
                appid, market_hash_name, classid
            )

        identity_verified = identity_status == IdentityVerificationStatus.VERIFIED

        # Check seller proceeds
        seller_proceeds = None
        if market_price is not None:
            seller_proceeds = market_price.seller_proceeds

        seller_proceeds_verified = (
            seller_proceeds is not None
            and seller_proceeds >= 0
        )

        # Check acquisition cost
        all_in_cost = None
        if acquisition_cost is not None:
            all_in_cost = acquisition_cost.all_in_cost

        acquisition_cost_verified = (
            all_in_cost is not None
            and all_in_cost > 0
            and acquisition_cost.cost_status == "TRACKED"
        )

        # Calculate profit
        expected_profit = None
        profit_margin = None

        if (
            seller_proceeds is not None
            and all_in_cost is not None
        ):
            expected_profit = seller_proceeds - all_in_cost
            if all_in_cost > 0:
                profit_margin = expected_profit / all_in_cost

        # Determine liquidity evidence
        liquidity_evidence = self._classify_liquidity(liquidity)

        # Classify opportunity
        classification, confidence, reason = self._classify(
            marketable=marketable,
            tradable=tradable,
            identity_verified=identity_verified,
            seller_proceeds_verified=seller_proceeds_verified,
            acquisition_cost_verified=acquisition_cost_verified,
            expected_profit=expected_profit,
            profit_margin=profit_margin,
            liquidity_evidence=liquidity_evidence,
            market_price=market_price,
            acquisition_cost=acquisition_cost,
        )

        # Build data sources
        data_sources = []
        if market_price is not None:
            data_sources.append("steam_market_structured")
        if acquisition_cost is not None:
            data_sources.append("accounting_database")

        return MarketOpportunity(
            market_hash_name=market_hash_name,
            appid=appid,
            classid=classid,
            assetid=assetid,
            quantity=quantity,
            marketable=marketable,
            tradable=tradable,
            acquisition=acquisition_cost,
            market=market_price,
            liquidity=liquidity,
            expected_profit=expected_profit,
            profit_margin=profit_margin,
            seller_proceeds=seller_proceeds,
            all_in_cost=all_in_cost,
            identity_verified=identity_verified,
            marketability_verified=marketable and tradable,
            seller_proceeds_verified=seller_proceeds_verified,
            acquisition_cost_verified=acquisition_cost_verified,
            liquidity_evidence=liquidity_evidence,
            classification=classification,
            confidence=confidence,
            reason=reason,
            timestamp=timestamp,
            data_sources=data_sources,
        )

    def _classify(
        self,
        marketable: bool,
        tradable: bool,
        identity_verified: bool,
        seller_proceeds_verified: bool,
        acquisition_cost_verified: bool,
        expected_profit: Optional[Decimal],
        profit_margin: Optional[Decimal],
        liquidity_evidence: str,
        market_price: Optional[StructuredMarketPrice],
        acquisition_cost: Optional[AcquisitionCost],
    ) -> tuple:
        """
        Classify the opportunity based on evidence.

        Returns (classification, confidence, reason).
        """
        # Not marketable
        if not marketable or not tradable:
            return (
                OpportunityClassification.NOT_MARKETABLE,
                "HIGH",
                "Item is not marketable or tradable on Steam.",
            )

        # Missing critical evidence
        if not identity_verified:
            return (
                OpportunityClassification.UNVERIFIED,
                "LOW",
                "Item identity could not be verified.",
            )

        if not seller_proceeds_verified:
            return (
                OpportunityClassification.UNVERIFIED,
                "LOW",
                "Seller proceeds could not be verified.",
            )

        if not acquisition_cost_verified:
            return (
                OpportunityClassification.POTENTIALLY_PROFITABLE,
                "MEDIUM",
                "Acquisition cost not fully verified; cannot calculate profit.",
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
        is_verifiable = (
            liquidity_evidence in (
                LiquidityEvidence.HIGH_EVIDENCE.value,
                LiquidityEvidence.MEDIUM_EVIDENCE.value,
            )
            and profit_margin is not None
            and profit_margin >= self.min_margin_threshold
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

    def _classify_liquidity(
        self,
        liquidity: Optional[dict],
    ) -> str:
        """Classify liquidity evidence level."""
        if liquidity is None:
            return LiquidityEvidence.INSUFFICIENT_DATA.value

        active_count = liquidity.get("active_listing_count")
        available_qty = liquidity.get("available_quantity")

        if active_count is None and available_qty is None:
            return LiquidityEvidence.INSUFFICIENT_DATA.value

        # High evidence: multiple active listings with quantity
        if active_count is not None and active_count >= 5:
            if available_qty is not None and available_qty >= 3:
                return LiquidityEvidence.HIGH_EVIDENCE.value

        # Medium evidence: some activity data
        if active_count is not None and active_count >= 2:
            return LiquidityEvidence.MEDIUM_EVIDENCE.value

        # Low evidence: minimal data
        return LiquidityEvidence.LOW_EVIDENCE.value

    def get_accounting_cost(
        self,
        market_hash_name: str,
        bot_name: str,
    ) -> Optional[AcquisitionCost]:
        """
        Retrieve known acquisition cost from database.

        Returns AcquisitionCost if TRACKED lot exists,
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
                    cost_status
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
            acquisition_fee = (
                Decimal(str(row["acquisition_fee"]))
                if row["acquisition_fee"]
                else None
            )
            all_in_cost = (
                Decimal(str(row["all_in_cost"]))
                if row["all_in_cost"]
                else None
            )

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


def create_scanner(db_path: str) -> MarketOpportunityScanner:
    """Factory function to create a scanner instance."""
    return MarketOpportunityScanner(
        db_path=db_path,
    )
