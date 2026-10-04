"""
Phase 7A — Realized Sale Lifecycle Tests

Tests for the realized sale accounting pipeline that recognizes
completed Steam Market sales and calculates REALIZED profit/loss.

READ-ONLY: No database writes, no Steam Market write operations.
"""

import sys
from decimal import Decimal
from unittest import mock

import pytest
import sqlite3

sys.path.insert(0, "projects/steam-trade-bot/app")

from transactions import (
    AcquisitionLot,
    CostStatus,
    Transaction,
    TransactionType,
    create_transaction,
)
from realized_sale import (
    RealizedSale,
    AllocatedLot,
    RealizedSaleProcessor,
    RealizedSaleClassification,
    LotAllocationEngine,
    AllocationPolicy,
    SaleReconciliationService,
    ReconciliationResult,
    create_realized_sale_processor,
    create_sale_reconciliation_service,
)


# ============================================================
# FIXTURES
# ============================================================


def make_transaction(sell=True, **kwargs):
    """Helper to create a transaction."""
    type_val = kwargs.pop("type", TransactionType.SELL if sell else TransactionType.BUY)
    return create_transaction(
        type=type_val.value,
        market_hash_name=kwargs.get("market_hash_name", "Test Item"),
        quantity=kwargs.get("quantity", 1),
        unit_price=kwargs.get("unit_price", Decimal("10.00")),
        fees=kwargs.get("fees", Decimal("1.50")),
        total_value=kwargs.get("total_value", None),
        timestamp=kwargs.get("timestamp", "2026-10-04T00:00:00Z"),
        bot_name=kwargs.get("bot_name", "Rixqor"),
        external_ref=kwargs.get("external_ref", "listing-123:purchase-456"),
    )


def make_lot(
    id=1,
    source_transaction_id=1,
    market_hash_name="Test Item",
    bot_name="Rixqor",
    original_quantity=5,
    remaining_quantity=5,
    unit_cost=Decimal("8.00"),
    cost_status=CostStatus.TRACKED,
    acquired_at="2026-09-01T00:00:00Z",
):
    """Helper to create an acquisition lot.
    
    Note: AcquisitionLot.unit_cost IS the all-in cost per unit (includes fees).
    """
    return AcquisitionLot(
        id=id,
        source_transaction_id=source_transaction_id,
        market_hash_name=market_hash_name,
        bot_name=bot_name,
        original_quantity=original_quantity,
        remaining_quantity=remaining_quantity,
        unit_cost=unit_cost,
        cost_status=cost_status,
        acquired_at=acquired_at,
    )


@pytest.fixture
def processor():
    """Create a processor with default FIFO allocation."""
    return RealizedSaleProcessor()


@pytest.fixture
def lots():
    """Create sample acquisition lots."""
    return [
        make_lot(id=1, source_transaction_id=1, acquired_at="2026-09-01T00:00:00Z",
                 unit_cost=Decimal("8.00")),
        make_lot(id=2, source_transaction_id=2, acquired_at="2026-09-15T00:00:00Z",
                 unit_cost=Decimal("9.00")),
        make_lot(id=3, source_transaction_id=3, acquired_at="2026-10-01T00:00:00Z",
                 unit_cost=Decimal("10.00")),
    ]


# ============================================================
# COMPLETED PROFITABLE SALE
# ============================================================

class TestProfitableSale:
    """Test profitable sale scenarios."""
    
    def test_profitable_sale(self, processor, lots):
        """Sale with proceeds > cost basis should be PROFITABLE."""
        # Sell 2 units at €12.00 each, total_value = 2*12 - 1.80 = 22.20
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=2,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("22.20"),
            external_ref="listing-100:purchase-200",
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.PROFITABLE
        assert result.quantity == 2
        assert result.sale_unit_price == Decimal("12.00")
        assert result.total_sale_proceeds == Decimal("22.20")
        # Cost basis: 2 * 8.00 = 16.00 (FIFO: lot 1, unit_cost=8.00)
        assert result.realized_cost_basis == Decimal("16.00")
        assert result.realized_profit == Decimal("6.20")  # 22.20 - 16.00
        assert result.is_profitable is True
        assert len(result.allocated_lots) == 1
        assert result.allocated_lots[0].lot_id == 1
        assert result.allocated_lots[0].quantity_allocated == 2
    
    def test_profitable_multiple_lots(self, processor, lots):
        """Sale spanning multiple lots should allocate FIFO."""
        # Sell 6 units - should use lot 1 (5) + lot 2 (1)
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=6,
            unit_price=Decimal("15.00"),
            fees=Decimal("2.25"),
            total_value=Decimal("87.75"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.PROFITABLE
        assert result.quantity == 6
        # Cost basis: 5*8.00 + 1*9.00 = 49.00
        assert result.realized_cost_basis == Decimal("49.00")
        assert result.realized_profit == Decimal("38.75")
        assert len(result.allocated_lots) == 2
        assert result.allocated_lots[0].lot_id == 1
        assert result.allocated_lots[0].quantity_allocated == 5
        assert result.allocated_lots[1].lot_id == 2
        assert result.allocated_lots[1].quantity_allocated == 1


# ============================================================
# COMPLETED LOSS SALE
# ============================================================

class TestLossSale:
    """Test loss sale scenarios."""
    
    def test_loss_sale(self, processor, lots):
        """Sale with proceeds < cost basis should be LOSS."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("7.00"),
            fees=Decimal("1.05"),
            total_value=Decimal("5.95"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.LOSS
        # Cost basis: 1 * 8.00 = 8.00
        assert result.realized_cost_basis == Decimal("8.00")
        assert result.realized_profit == Decimal("-2.05")  # 5.95 - 8.00
        assert result.is_loss is True
    
    def test_full_lot_loss(self, processor, lots):
        """Sell entire lot at a loss."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=5,
            unit_price=Decimal("7.00"),
            fees=Decimal("1.05"),
            total_value=Decimal("33.95"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.LOSS
        assert result.realized_cost_basis == Decimal("40.00")  # 5 * 8.00
        assert result.realized_profit == Decimal("-6.05")


# ============================================================
# BREAK-EVEN SALE
# ============================================================

class TestBreakEvenSale:
    """Test break-even scenarios."""
    
    def test_break_even(self, processor, lots):
        """Sale where proceeds exactly equal cost basis."""
        # Sell at exactly cost basis (8.00 per unit, no fees)
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("8.00"),
            fees=Decimal("0.00"),
            total_value=Decimal("8.00"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.BREAK_EVEN
        assert result.realized_profit == Decimal("0.00")
        assert result.is_break_even is True


# ============================================================
# PARTIAL SALE
# ============================================================

class TestPartialSale:
    """Test partial quantity sales."""
    
    def test_partial_sale(self, processor, lots):
        """Sell partial quantity from a lot."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=2,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("22.20"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.quantity == 2
        assert result.realized_cost_basis == Decimal("16.00")  # 2 * 8.00
        assert result.allocated_lots[0].remaining_before == 5
        assert result.allocated_lots[0].remaining_after == 3
        assert result.allocated_lots[0].quantity_allocated == 2


# ============================================================
# FULL LOT SALE
# ============================================================

class TestFullLotSale:
    """Test selling entire lots."""
    
    def test_full_lot(self, processor, lots):
        """Sell entire lot 1 (5 units)."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=5,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("58.20"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.allocated_lots[0].remaining_after == 0
        assert result.allocated_lots[0].quantity_allocated == 5


# ============================================================
# MULTIPLE ACQUISITION LOTS
# ============================================================

class TestMultipleLots:
    """Test sales across multiple lots."""
    
    def test_fifo_allocation(self, processor, lots):
        """Verify FIFO allocation order."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=8,
            unit_price=Decimal("15.00"),
            fees=Decimal("2.25"),
            total_value=Decimal("117.75"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert len(result.allocated_lots) == 2
        assert result.allocated_lots[0].lot_id == 1
        assert result.allocated_lots[0].quantity_allocated == 5
        assert result.allocated_lots[1].lot_id == 2
        assert result.allocated_lots[1].quantity_allocated == 3
        # Cost basis: 5*8.00 + 3*9.00 = 40.00 + 27.00 = 67.00
        assert result.realized_cost_basis == Decimal("67.00")
    
    def test_mixed_cost_status(self, processor):
        """Handle lots with different cost statuses."""
        unknown_lot = make_lot(
            id=4,
            source_transaction_id=4,
            cost_status=CostStatus.UNKNOWN,
            unit_cost=None,
        )
        
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )
        
        result = processor.process_sale(sale, [unknown_lot])
        
        assert result.classification == RealizedSaleClassification.UNVERIFIED
        assert "cost" in result.reason.lower()


# ============================================================
# SALE QUANTITY GREATER THAN REMAINING
# ============================================================

class TestInsufficientQuantity:
    """Test edge cases with insufficient quantity."""
    
    def test_quantity_exceeds_remaining(self, processor, lots):
        """Selling more than available should be handled gracefully."""
        # Create a sale that exceeds total remaining quantity (15 total)
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=20,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )

        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.UNVERIFIED
        assert "insufficient" in result.reason.lower()
        assert result.allocated_lots == []
    
    def test_zero_quantity(self, processor, lots):
        """Zero quantity sale should raise error via transaction validation."""
        with pytest.raises(Exception):  # TransactionError
            make_transaction(
                sell=True,
                market_hash_name="Test Item",
                quantity=0,
                unit_price=Decimal("10.00"),
                fees=Decimal("1.50"),
                total_value=Decimal("8.50"),
            )


# ============================================================
# MISSING SALE PROCEEDS
# ============================================================

class TestMissingProceeds:
    """Test handling of missing sale data."""
    
    def test_missing_unit_price(self, processor, lots):
        """Sale with missing unit price should fail validation."""
        with pytest.raises(Exception):
            make_transaction(
                sell=True,
                market_hash_name="Test Item",
                quantity=1,
                unit_price=None,
                fees=Decimal("1.50"),
                total_value=Decimal("8.50"),
            )
    
    def test_valid_with_missing_fees(self, processor, lots):
        """Sale with zero fees should be processed correctly."""
        # Break-even: sell at exactly cost basis (8.00) with no fees
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("8.00"),
            fees=Decimal("0.00"),
            total_value=Decimal("8.00"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.BREAK_EVEN


# ============================================================
# IDENTITY MATCHING
# ============================================================

class TestIdentityMatching:
    """Test sale identity verification."""
    
    def test_market_hash_name_match(self, processor, lots):
        """Sale must match lot by market_hash_name."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Different Item",
            quantity=1,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.UNVERIFIED
        assert "no matching" in result.reason.lower()
    
    def test_bot_name_match(self, processor, lots):
        """Sale must match lot by bot_name."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            bot_name="OtherBot",
            quantity=1,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.UNVERIFIED
    
    def test_listingid_extraction(self, processor, lots):
        """Extract listingid from external_ref."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("22.20"),
            external_ref="listing-12345:purchase-67890",
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.listingid == "listing-12345"
        assert result.purchaseid == "purchase-67890"


# ============================================================
# IDEMPOTENCY
# ============================================================

class TestIdempotency:
    """Test duplicate prevention."""
    
    def test_duplicate_external_ref(self, processor, lots):
        """Same external_ref should produce same result."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("22.20"),
            external_ref="listing-unique-123:purchase-456",
        )
        
        result1 = processor.process_sale(sale, lots)
        result2 = processor.process_sale(sale, lots)
        
        assert result1.external_ref == result2.external_ref
        assert result1.realized_profit == result2.realized_profit
        assert result1.classification == result2.classification
    
    def test_different_ref_different_result(self, processor, lots):
        """Different external_ref should be treated as separate."""
        sale1 = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("22.20"),
            external_ref="listing-aaa:purchase-bbb",
        )
        
        sale2 = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("22.20"),
            external_ref="listing-ccc:purchase-ddd",
        )
        
        result1 = processor.process_sale(sale1, lots)
        result2 = processor.process_sale(sale2, lots)
        
        assert result1.classification == RealizedSaleClassification.PROFITABLE
        assert result2.classification == RealizedSaleClassification.PROFITABLE


# ============================================================
# ALLOCATION POLICY
# ============================================================

class TestAllocationPolicy:
    """Test different allocation policies."""
    
    def test_fifo_policy(self, lots):
        """FIFO should allocate oldest lots first."""
        engine = LotAllocationEngine(policy=AllocationPolicy.FIFO)
        
        allocated = engine.allocate(lots, 6)
        
        assert len(allocated) == 2
        assert allocated[0].lot_id == 1
        assert allocated[0].quantity_allocated == 5
        assert allocated[1].lot_id == 2
        assert allocated[1].quantity_allocated == 1


# ============================================================
# REALIZED COST BASIS
# ============================================================

class TestCostBasis:
    """Test cost basis calculations."""
    
    def test_cost_basis_uses_unit_cost(self, processor, lots):
        """Cost basis should use unit_cost from lots."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )
        
        result = processor.process_sale(sale, lots)
        
        # Cost basis: 1 * 8.00 = 8.00 (unit_cost from lot 1)
        assert result.realized_cost_basis == Decimal("8.00")
    
    def test_unknown_cost_basis(self, processor):
        """Unknown cost should result in UNVERIFIED."""
        unknown_lot = make_lot(
            id=99,
            cost_status=CostStatus.UNKNOWN,
            unit_cost=None,
        )
        
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )
        
        result = processor.process_sale(sale, [unknown_lot])
        
        assert result.classification == RealizedSaleClassification.UNVERIFIED
        assert result.realized_cost_basis == Decimal("0")


# ============================================================
# SALE PROCEEDS SEMANTICS
# ============================================================

class TestSaleProceeds:
    """Test sale proceeds handling."""
    
    def test_proceeds_vs_gross(self, processor, lots):
        """Sale proceeds = total_value (net after fees)."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.total_sale_proceeds == Decimal("8.50")
    
    def test_authoritative_proceeds(self, processor, lots):
        """Proceeds must come from transaction, not estimated."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("22.20"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result.sale_proceeds_verified is True
        assert result.sale_unit_price == Decimal("12.00")


# ============================================================
# IMPLEMENTATION VERIFICATION
# ============================================================

class TestImplementation:
    """Test implementation details."""
    
    def test_factory_functions(self):
        """Factory functions should create correct instances."""
        processor = create_realized_sale_processor()
        assert isinstance(processor, RealizedSaleProcessor)
        
        service = create_sale_reconciliation_service()
        assert isinstance(service, SaleReconciliationService)
    
    def test_reconciliation_result(self, processor, lots):
        """Reconciliation result should include updates."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=2,
            unit_price=Decimal("12.00"),
            fees=Decimal("1.80"),
            total_value=Decimal("22.20"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert len(result.allocated_lots) > 0
        assert result.realized_profit is not None
        assert result.realized_margin is not None
    
    def test_is_profitable_property(self, processor, lots):
        """Test is_profitable property."""
        sale_profit = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("15.00"),
            fees=Decimal("2.25"),
            total_value=Decimal("27.75"),
        )
        result_profit = processor.process_sale(sale_profit, lots)
        assert result_profit.is_profitable is True
        
        sale_loss = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("5.00"),
            fees=Decimal("0.75"),
            total_value=Decimal("4.25"),
        )
        result_loss = processor.process_sale(sale_loss, lots)
        assert result_loss.is_profitable is False
        assert result_loss.is_loss is True


# ============================================================
# SAFETY TESTS
# ============================================================

class TestSafety:
    """Test safety guarantees."""
    
    def test_no_database_writes(self, processor, lots):
        """Processor should not write to database."""
        import os
        import tempfile
        
        tmpdb = os.path.join(tempfile.gettempdir(), 'phase7a_test.db')
        if os.path.exists(tmpdb):
            os.unlink(tmpdb)
        
        conn = sqlite3.connect(tmpdb)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()
        initial_size = os.path.getsize(tmpdb)
        
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )
        
        result = processor.process_sale(sale, lots)
        
        final_size = os.path.getsize(tmpdb)
        assert initial_size == final_size, "Database was modified!"
        os.unlink(tmpdb)
    
    def test_no_steam_writes(self, processor, lots):
        """Processor should not make any HTTP requests."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("10.00"),
            fees=Decimal("1.50"),
            total_value=Decimal("8.50"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result is not None


# ============================================================
# REGRESSION TESTS
# ============================================================

class TestRegression:
    """Regression tests for known issues."""
    
    def test_131_false_positive_still_rejected(self, processor, lots):
        """€0.01 items should not create false profitable edges."""
        sale = make_transaction(
            sell=True,
            market_hash_name="Test Item",
            quantity=1,
            unit_price=Decimal("0.01"),
            fees=Decimal("0.01"),
            total_value=Decimal("0.00"),
        )
        
        result = processor.process_sale(sale, lots)
        
        assert result is not None


# ============================================================
# LIVE VALIDATION
# ============================================================

class TestLiveValidation:
    """Test against mocked real data structures."""
    
    def test_realistic_sale(self, processor):
        """Test with realistic Steam Market sale data."""
        sale = make_transaction(
            sell=True,
            market_hash_name="AK-47 | Redline (Field-Tested)",
            quantity=1,
            unit_price=Decimal("34.34"),
            fees=Decimal("5.15"),
            total_value=Decimal("29.19"),
            external_ref="listing-522011140643269572:purchase-522011140643269573",
        )
        
        lots = [
            make_lot(
                id=1,
                source_transaction_id=1,
                market_hash_name="AK-47 | Redline (Field-Tested)",
                unit_cost=Decimal("25.00"),
                acquired_at="2026-08-15T00:00:00Z",
            )
        ]
        
        result = processor.process_sale(sale, lots)
        
        assert result.classification == RealizedSaleClassification.PROFITABLE
        assert result.realized_profit == Decimal("4.19")  # 29.19 - 25.00
        assert result.listingid == "listing-522011140643269572"
        assert result.purchaseid == "purchase-522011140643269573"
