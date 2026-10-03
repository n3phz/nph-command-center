import sys
sys.path.insert(0, "app")
"""V0.6.2 persistence tests for the dry-run BUY projection layer."""

from decimal import Decimal
import sqlite3
import pytest

from buy_projection import dry_run_projection, DryRunReport
from projection_persistence import (
    create_schema,
    persist_projection,
    PersistenceReport,
)
from steam_market_history_json import NormalizedEvent
from transactions import CostStatus


# ---------------------------------------------------------------------------
# Test fixtures (reusing V0.6.1 pattern)
# ---------------------------------------------------------------------------

_ACCOUNT_STEAMID = "76561197960287930"


def make_normalized_buy_event(
    listingid: str,
    purchaseid: str,
    market_hash_name: str = "Example Card",
    quantity: int = 1,
    paid_amount: int = 1000,
    paid_fee: int = 50,
    time_event: str = "2026-09-16T13:00:00Z",
) -> NormalizedEvent:
    """Create a V0.5.9 NormalizedEvent for testing."""
    class MockNormalizedEvent:
        pass

    event = MockNormalizedEvent()
    event.event_type = "BUY"
    event.steamid_actor = _ACCOUNT_STEAMID
    event.steamid_purchaser = _ACCOUNT_STEAMID
    event.time_event = time_event
    event.time_sold = None
    event.listingid = listingid
    event.purchaseid = purchaseid
    event.market_hash_name = market_hash_name

    event.paid_amount = paid_amount
    event.paid_fee = paid_fee
    event.steam_fee = 30
    event.publisher_fee = 20
    event.publisher_fee_percent = "0.100000001490116119"
    event.publisher_fee_app = 730
    event.funds_returned = 0
    event.received_amount = 950
    event.currencyid = 1
    event.received_currencyid = 1
    event.added_tax = 0

    event.asset_appid = ""
    event.asset_contextid = ""
    event.asset_id = ""
    event.asset_classid = ""
    event.asset_instanceid = ""
    event.asset_amount = str(quantity)
    event.asset_new_id = ""
    event.asset_new_contextid = ""

    event.event_type_raw = 4

    return event


def make_test_conn():
    """Create a fresh in-memory SQLite database with V0.5.0 schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    return conn


def make_plain_test_conn():
    """Create a connection using SQLite's default tuple row factory."""
    conn = sqlite3.connect(':memory:')
    create_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

# A. Empty DB - persist N projected BUYs → N transactions, N lots
def test_empty_db_persists_all_events():
    """Empty DB: N projected BUYs → N transactions and N lots inserted."""
    events = [
        make_normalized_buy_event("tx-001", "pid-001", "Card A"),
        make_normalized_buy_event("tx-002", "pid-002", "Card B"),
        make_normalized_buy_event("tx-003", "pid-003", "Card C", quantity=2),
    ]
    report = dry_run_projection(events, "Rixqor")

    conn = make_test_conn()
    result = persist_projection(report, conn)

    assert result.attempted == 3
    assert result.inserted_transactions == 3
    assert result.inserted_lots == 3
    assert result.skipped_duplicates == 0
    assert result.errors == []

    # Verify actual rows
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 3
    assert lot_count == 3

    conn.close()


# B. Repeat same report → no duplicate transactions/lots, all counted as skipped
def test_repeat_report_is_idempotent():
    """Repeating the same report produces no duplicates; all skipped."""
    events = [
        make_normalized_buy_event("tx-010", "pid-010", "Card A"),
        make_normalized_buy_event("tx-011", "pid-011", "Card B"),
    ]
    report = dry_run_projection(events, "Rixqor")

    conn = make_test_conn()
    result1 = persist_projection(report, conn)
    result2 = persist_projection(report, conn)

    # First persistence
    assert result1.attempted == 2
    assert result1.inserted_transactions == 2
    assert result1.inserted_lots == 2
    assert result1.skipped_duplicates == 0

    # Second persistence (same data)
    assert result2.attempted == 2
    assert result2.inserted_transactions == 0
    assert result2.inserted_lots == 0
    assert result2.skipped_duplicates == 2

    # DB still has only 2 transactions and 2 lots
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 2
    assert lot_count == 2

    conn.close()


# J. Default row factory (tuple rows) - persistence works without row_factory
def test_repeat_report_is_idempotent_with_default_tuple_rows():
    """Repeated persistence works with SQLite's default tuple rows."""
    events = [make_normalized_buy_event('tx-100', 'pid-100', 'Card A')]
    report = dry_run_projection(events, 'Rixqor')

    conn = make_plain_test_conn()
    try:
        first = persist_projection(report, conn)
        row = conn.execute('SELECT id FROM transactions').fetchone()
        assert isinstance(row, tuple)

        second = persist_projection(report, conn)

        assert first.inserted_transactions == 1
        assert first.inserted_lots == 1
        assert first.skipped_duplicates == 0
        assert second.inserted_transactions == 0
        assert second.inserted_lots == 0
        assert second.skipped_duplicates == 1
        assert conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM acquisition_lots').fetchone()[0] == 1
    finally:
        conn.close()


# C. Partial existing state - transaction exists but lot missing → explicit failure
def test_partial_existing_state_fails():
    """Transaction exists but acquisition lot is missing → explicit error, no silent duplication."""
    events = [make_normalized_buy_event("tx-020", "pid-020", "Card A")]

    conn = make_test_conn()
    # Manually insert a transaction WITHOUT its lot
    conn.execute(
        """
        INSERT INTO transactions (type, market_hash_name, quantity, unit_price, fees,
                                  total_value, timestamp, bot_name, external_ref)
        VALUES ('BUY', 'Card A', 1, '1000', '50', '1000', '2026-09-16T13:00:00Z', 'Rixqor', 'tx-020:pid-020')
        """
    )
    conn.commit()

    report = dry_run_projection(events, "Rixqor")

    with pytest.raises(ValueError, match="Inconsistent existing state.*acquisition lot is missing"):
        persist_projection(report, conn)

    # DB should still have only the manually inserted transaction, no lot
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 1
    assert lot_count == 0

    conn.close()


# D. Conflicting existing state - same external_ref but different data → explicit failure
def test_conflicting_existing_state_fails():
    """Same external_ref with different economic data → explicit error."""
    events = [make_normalized_buy_event("tx-030", "pid-030", "Card A", paid_amount=1000)]

    conn = make_test_conn()
    # Manually insert a transaction with DIFFERENT data
    conn.execute(
        """
        INSERT INTO transactions (type, market_hash_name, quantity, unit_price, fees,
                                  total_value, timestamp, bot_name, external_ref)
        VALUES ('BUY', 'Different Card', 5, '999', '10', '5000', '2026-09-16T13:00:00Z', 'Rixqor', 'tx-030:pid-030')
        """
    )
    conn.execute(
        """
        INSERT INTO acquisition_lots (source_transaction_id, market_hash_name, bot_name,
                                      original_quantity, remaining_quantity, unit_cost,
                                      acquired_at, cost_status)
        VALUES (1, 'Different Card', 'Rixqor', 5, 5, NULL, '2026-09-16T13:00:00Z', 'UNKNOWN')
        """
    )
    conn.commit()

    report = dry_run_projection(events, "Rixqor")

    with pytest.raises(ValueError, match="Conflicting existing state.*differs from projection"):
        persist_projection(report, conn)

    # No new rows should be added
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 1
    assert lot_count == 1

    conn.close()


# E. Atomic rollback - batch with one invalid/conflicting event → zero new rows
def test_atomic_rollback_on_conflict():
    """Batch with one conflicting event → zero new rows after rollback."""
    events = [
        make_normalized_buy_event("tx-040", "pid-040", "Card A"),  # Valid
        make_normalized_buy_event("tx-041", "pid-041", "Card B"),  # Valid
    ]

    conn = make_test_conn()
    # Pre-insert a conflicting transaction for the SECOND event
    conn.execute(
        """
        INSERT INTO transactions (type, market_hash_name, quantity, unit_price, fees,
                                  total_value, timestamp, bot_name, external_ref)
        VALUES ('BUY', 'Different Card', 5, '999', '10', '5000', '2026-09-16T13:00:00Z', 'Rixqor', 'tx-041:pid-041')
        """
    )
    conn.execute(
        """
        INSERT INTO acquisition_lots (source_transaction_id, market_hash_name, bot_name,
                                      original_quantity, remaining_quantity, unit_cost,
                                      acquired_at, cost_status)
        VALUES (1, 'Different Card', 'Rixqor', 5, 5, NULL, '2026-09-16T13:00:00Z', 'UNKNOWN')
        """
    )
    conn.commit()

    report = dry_run_projection(events, "Rixqor")

    with pytest.raises(ValueError, match="Conflicting existing state"):
        persist_projection(report, conn)

    # Atomic rollback: no new rows at all
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 1  # Only the pre-existing one
    assert lot_count == 1

    conn.close()


# F. UNKNOWN cost - acquisition_lots.cost_status == UNKNOWN, unit_cost IS NULL
def test_unknown_cost_status_persisted():
    """All persisted lots have cost_status=UNKNOWN and unit_cost=NULL."""
    events = [
        make_normalized_buy_event("tx-050", "pid-050", "Card A", quantity=3),
    ]
    report = dry_run_projection(events, "Rixqor")

    conn = make_test_conn()
    result = persist_projection(report, conn)

    assert result.inserted_lots == 1

    lot = conn.execute(
        "SELECT cost_status, unit_cost FROM acquisition_lots"
    ).fetchone()

    assert lot["cost_status"] == "UNKNOWN"
    assert lot["unit_cost"] is None

    conn.close()


# G. Source identity - external_ref remains exactly listingid:purchaseid
def test_external_ref_preserved_exactly():
    """external_ref = listingid:purchaseid is preserved without modification."""
    events = [make_normalized_buy_event("my-listing-123", "my-purchase-456", "Card A")]
    report = dry_run_projection(events, "TestBot")

    conn = make_test_conn()
    persist_projection(report, conn)

    tx = conn.execute("SELECT external_ref FROM transactions").fetchone()
    assert tx["external_ref"] == "my-listing-123:my-purchase-456"

    conn.close()


# H. Numeric preservation - unit_price/total_value persisted per schema representation
def test_numeric_preservation():
    """Monetary values preserved as decimal strings (no currency conversion)."""
    # paid_amount=2500, quantity=2 → unit_price=2500, total_value=5000
    events = [
        make_normalized_buy_event("tx-060", "pid-060", "Card A",
                                  quantity=2, paid_amount=2500, paid_fee=75)
    ]
    report = dry_run_projection(events, "Rixqor")

    conn = make_test_conn()
    persist_projection(report, conn)

    tx = conn.execute("SELECT unit_price, fees, total_value FROM transactions").fetchone()
    assert tx["unit_price"] == "2500"
    assert tx["fees"] == "75"
    assert tx["total_value"] == "5000"  # 2500 * 2

    lot = conn.execute("SELECT unit_cost FROM acquisition_lots").fetchone()
    assert lot["unit_cost"] is None  # UNKNOWN cost

    conn.close()


# I. Empty input - valid zero-operation report without modifying DB
def test_empty_input_noop():
    """Empty report → zero-operation PersistenceReport, DB unchanged."""
    report = dry_run_projection([], "Rixqor")

    conn = make_test_conn()
    result = persist_projection(report, conn)

    assert result.attempted == 0
    assert result.inserted_transactions == 0
    assert result.inserted_lots == 0
    assert result.skipped_duplicates == 0
    assert result.errors == []

    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 0
    assert lot_count == 0

    conn.close()


# Additional: quantity preserved correctly in lots
def test_quantity_preserved_in_lots():
    """original_quantity and remaining_quantity match projected quantity."""
    events = [make_normalized_buy_event("tx-070", "pid-070", "Card A", quantity=7)]
    report = dry_run_projection(events, "Rixqor")

    conn = make_test_conn()
    persist_projection(report, conn)

    lot = conn.execute(
        "SELECT original_quantity, remaining_quantity FROM acquisition_lots"
    ).fetchone()

    assert lot["original_quantity"] == 7
    assert lot["remaining_quantity"] == 7

    conn.close()


# Additional: bot_name isolation - same external_ref for different bots is allowed
def test_same_external_ref_different_bots_allowed():
    """Same external_ref for different bots is NOT a duplicate (unique index is per-bot)."""
    events1 = [make_normalized_buy_event("shared", "ref", "Card A")]
    events2 = [make_normalized_buy_event("shared", "ref", "Card B")]

    report1 = dry_run_projection(events1, "BotA")
    report2 = dry_run_projection(events2, "BotB")

    conn = make_test_conn()
    persist_projection(report1, conn)
    persist_projection(report2, conn)

    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 2
    assert lot_count == 2

    bots = conn.execute("SELECT DISTINCT bot_name FROM transactions").fetchall()
    bot_names = {row["bot_name"] for row in bots}
    assert bot_names == {"BotA", "BotB"}

    conn.close()


# Additional: PersistenceReport is immutable
def test_persistence_report_immutable():
    """PersistenceReport is a frozen dataclass."""
    from dataclasses import FrozenInstanceError

    report = PersistenceReport(
        attempted=1, inserted_transactions=1, inserted_lots=1,
        skipped_duplicates=0, errors=[]
    )

    with pytest.raises(FrozenInstanceError):
        report.attempted = 99


# Additional: batch with mixed new and duplicate events
def test_mixed_new_and_duplicate_batch():
    """Batch containing both new and duplicate events inserts only new ones."""
    events_new = [
        make_normalized_buy_event("new-1", "pid-1", "New Card 1"),
        make_normalized_buy_event("new-2", "pid-2", "New Card 2"),
    ]
    events_dup = [
        make_normalized_buy_event("dup-1", "pid-dup", "Dup Card"),
        make_normalized_buy_event("dup-2", "pid-dup", "Dup Card 2"),  # Different card, same source
    ]

    report1 = dry_run_projection(events_new + events_dup, "Rixqor")
    conn = make_test_conn()
    persist_projection(report1, conn)

    # Now repeat with some new, some duplicate
    events_mixed = [
        make_normalized_buy_event("new-1", "pid-1", "New Card 1"),  # duplicate
        make_normalized_buy_event("new-3", "pid-3", "New Card 3"),  # new
    ]
    report2 = dry_run_projection(events_mixed, "Rixqor")
    result2 = persist_projection(report2, conn)

    assert result2.attempted == 2
    assert result2.inserted_transactions == 1
    assert result2.inserted_lots == 1
    assert result2.skipped_duplicates == 1

    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
