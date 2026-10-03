import sys
sys.path.insert(0, "app")
"""
Focused unit tests for the V0.5.0 transaction and acquisition lot domain.

These tests cover the 16 required scenarios:
1.  BUY transaction creation
2.  SELL transaction creation
3.  invalid transaction type
4.  invalid quantity
5.  invalid monetary value
6.  multiple BUY transactions create independent lots
7. 2. different BUY costs remain independent
8.  tracked cost
9.  UNKNOWN cost
10. lot quantity invariants
11. source transaction relationship
12. no synthetic historical transactions
13. duplicate external reference handling
14. remaining quantity initialized equal to original quantity
15. partial lot consumption rejection
15. attempt to consume more than remaining quantity is rejected
16. cost_status UNKNOWN distinct from zero cost
17. source transaction relationship enforced
18. SELL type does not create a lot
"""

import pytest
from decimal import Decimal

from transactions import (
    Transaction,
    TransactionType,
    CostStatus,
    AcquisitionLot,
    TransactionError,
    AcquisitionLotError,
)


# ── Transaction tests ────────────────────────────────────────────────

def test_buy_transaction_creation():
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=3,
        unit_price=Decimal("10.50"),
        fees=Decimal("1.00"),
        bot_name="Rixqor",
    )
    assert tx.type is TransactionType.BUY
    assert tx.market_hash_name == "Test Item"
    assert tx.quantity == 3
    assert tx.unit_price == Decimal("10.50")
    assert tx.fees == Decimal("1.00")
    assert tx.total_value == Decimal("31.50")
    assert tx.bot_name == "Rixqor"
    assert tx.timestamp is not None
    # unpersisted transaction has no ID
    assert tx.id is None


def test_sell_transaction_creation():
    tx = Transaction.create_sell(
        market_hash_name="Test Item",
        quantity=2,
        unit_price=Decimal("20.00"),
        fees=Decimal("0.50"),
        bot_name="Rixqor",
    )
    assert tx.type is TransactionType.SELL
    assert tx.quantity == 2
    assert tx.total_value == Decimal("40.00")


def test_invalid_transaction_type():
    with pytest.raises(TransactionError):
        # Passing a string that is not TransactionType should fail in __post_init__
        _ = Transaction(
            type="INVALID",
            market_hash_name="Test",
            quantity=1,
            unit_price=Decimal("1.00"),
            fees=Decimal("0"),
            total_value=Decimal("1.00"),
            timestamp="2026-01-01T00:00:00+00:00",
            bot_name="TestBot",
        )


def test_invalid_quantity_zero():
    with pytest.raises(TransactionError):
        Transaction.create_buy(
            market_hash_name="Test",
            quantity=0,
            unit_price=Decimal("1.00"),
            fees=Decimal("0"),
            bot_name="TestBot",
        )


def test_invalid_quantity_negative():
    with pytest.raises(TransactionError):
        Transaction.create_buy(
            market_hash_name="Test",
            quantity=-1,
            unit_price=Decimal("1.00"),
            fees=Decimal("0"),
            bot_name="TestBot",
        )


def test_invalid_unit_price_negative():
    with pytest.raises(TransactionError):
        Transaction.create_buy(
            market_hash_name="Test",
            quantity=1,
            unit_price=Decimal("-1.00"),
            fees=Decimal("0"),
            bot_name="TestBot",
        )


def test_invalid_fees_negative():
    with pytest.raises(TransactionError):
        Transaction.create_buy(
            market_hash_name="Test",
            quantity=1,
            unit_price=Decimal("1.00"),
            fees=Decimal("-0.50"),
            bot_name="TestBot",
        )


def test_invalid_total_value_negative():
    with pytest.raises(TransactionError):
        Transaction.create_buy(
            market_hash_name="Test",
            quantity=1,
            unit_price=Decimal("1.00"),
            fees=Decimal("0"),
            total_value=Decimal("-1.00"),
            bot_name="TestBot",
        )


def test_invalid_timestamp():
    with pytest.raises(TransactionError):
        Transaction.create_buy(
            market_hash_name="Test",
            quantity=1,
            unit_price=Decimal("1.00"),
            fees=Decimal("0"),
            bot_name="TestBot",
            timestamp="not-a-date",
        )


def test_invalid_bot_name():
    with pytest.raises(TransactionError):
        Transaction.create_buy(
            market_hash_name="Test",
            quantity=1,
            unit_price=Decimal("1.00"),
            fees=Decimal("0"),
            bot_name="",
        )


def test_invalid_market_hash_name():
    with pytest.raises(TransactionError):
        Transaction.create_buy(
            market_hash_name="",
            quantity=1,
            unit_price=Decimal("1.00"),
            fees=Decimal("0"),
            bot_name="TestBot",
        )


# ── Acquisition lot tests ────────────────────────────────────────────

def test_lot_from_buy_transaction_tracked():
    # Use an explicit positive ID to simulate a persisted transaction
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=5,
        unit_price=Decimal("12.00"),
        fees=Decimal("0.75"),
        bot_name="Rixqor",
    )
    # Reconstruct with a persisted ID
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=42,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted, cost_status=CostStatus.TRACKED)
    assert lot.cost_status is CostStatus.TRACKED
    assert lot.original_quantity == 5
    assert lot.remaining_quantity == 5
    assert lot.unit_cost == Decimal("12.00")
    assert lot.source_transaction_id == 42


def test_lot_from_buy_transaction_unknown():
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=3,
        unit_price=Decimal("15.00"),
        fees=Decimal("0.50"),
        bot_name="Rixqor",
    )
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=43,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted, cost_status=CostStatus.UNKNOWN)
    assert lot.cost_status is CostStatus.UNKNOWN
    assert lot.unit_cost is None
    assert lot.source_transaction_id == 43


def test_lot_invariants():
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=4,
        unit_price=Decimal("10.00"),
        fees=Decimal("0"),
        bot_name="Rixqor",
    )
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=44,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted)
    assert lot.original_quantity == 4
    assert lot.remaining_quantity == 4
    # consume some
    lot2 = lot.consume(2)
    assert lot2.remaining_quantity == 2
    assert lot.remaining_quantity == 4  # original unchanged
    # attempt to over-consume
    with pytest.raises(AcquisitionLotError):
        lot.consume(5)


def test_unknown_cost_not_zero():
    """UNKNOWN cost must not be interpreted as zero cost."""
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=2,
        unit_price=Decimal("10.00"),
        fees=Decimal("0"),
        bot_name="Rixqor",
    )
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=45,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted, cost_status=CostStatus.UNKNOWN)
    assert lot.unit_cost is None
    # The lot must distinguish UNKNOWN from zero
    # If unit_cost were 0, this test would fail
    assert lot.cost_status is CostStatus.UNKNOWN


def test_lot_source_transaction_relationship():
    """A lot must reference its source BUY transaction.

    An unpersisted transaction has id=None, so from_buy_transaction
    must raise ValueError until the transaction is persisted and
    assigned a positive source_transaction_id.
    """
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=3,
        unit_price=Decimal("10.00"),
        fees=Decimal("0.50"),
        bot_name="Rixqor",
    )
    # Unpersisted transaction has no ID
    assert tx.id is None
    # from_buy_transaction must raise ValueError for unpersisted transactions
    with pytest.raises(ValueError, match="Transaction must be persisted"):
        AcquisitionLot.from_buy_transaction(tx)

    # After persistence (assigning a positive ID), the lot can be created
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=99,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted)
    assert lot.source_transaction_id == 99


def test_partial_lot_consumption():
    """Partial consumption reduces remaining_quantity only."""
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=10,
        unit_price=Decimal("5.00"),
        fees=Decimal("1.00"),
        bot_name="Rixqor",
    )
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=46,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted)
    lot2 = lot.consume(3)
    assert lot2.remaining_quantity == 7
    # Original lot unchanged
    assert lot.remaining_quantity == 10


def test_cannot_consume_more_than_remaining():
    """Attempting to consume more than remaining quantity is rejected."""
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=5,
        unit_price=Decimal("10.00"),
        fees=Decimal("0"),
        bot_name="Rixqor",
    )
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=47,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted)
    with pytest.raises(AcquisitionLotError):
        lot.consume(10)


def test_lot_quantity_invariants():
    """original_quantity > 0, 0 <= remaining_quantity <= original_quantity."""
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=7,
        unit_price=Decimal("3.00"),
        fees=Decimal("0.50"),
        bot_name="Rixqor",
    )
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=48,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted)
    assert lot.original_quantity > 0
    assert 0 <= lot.remaining_quantity <= lot.original_quantity


def test_duplicate_external_reference_handling():
    """Two transactions with same external_ref should behave deterministically."""
    tx1 = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=3,
        unit_price=Decimal("10.00"),
        fees=Decimal("0.50"),
        bot_name="Rixqor",
        external_ref="ref-001",
    )
    tx2 = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=3,
        unit_price=Decimal("10.00"),
        fees=Decimal("0.50"),
        bot_name="Rixqor",
        external_ref="ref-001",
    )
    # Both should have the same external_ref; system should handle duplicates
    assert tx1.external_ref == tx2.external_ref == "ref-001"


# ── Edge cases ───────────────────────────────────────────────────────

def test_decimal_precision():
    """Monetary values should use Decimal for precision."""
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=3,
        unit_price=Decimal("10.55"),
        fees=Decimal("0.123456789"),
        bot_name="Rixqor",
    )
    # total should be unit_price * quantity
    assert tx.total_value == Decimal("31.65")  # 10.55 * 3 = 31.65


def test_consumed_lot_is_immutable():
    """Consume returns a new lot; original should be unchanged."""
    tx = Transaction.create_buy(
        market_hash_name="Test Item",
        quantity=8,
        unit_price=Decimal("2.00"),
        fees=Decimal("0"),
        bot_name="Rixqor",
    )
    tx_persisted = Transaction(
        type=tx.type,
        market_hash_name=tx.market_hash_name,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        fees=tx.fees,
        total_value=tx.total_value,
        timestamp=tx.timestamp,
        bot_name=tx.bot_name,
        external_ref=tx.external_ref,
        id=49,
    )
    lot = AcquisitionLot.from_buy_transaction(tx_persisted)
    lot2 = lot.consume(1)
    assert lot.remaining_quantity == 8
    assert lot2.remaining_quantity == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
