"""
Phase 5F — Read-Only Tracked Inventory Profitability Monitor Tests

Tests for the inventory profitability monitor that evaluates
tracked inventory items against current Steam Market exit prices.

READ-ONLY: No database writes, no Steam Market write operations.
"""

import sys
import sqlite3
import tempfile
import os
from decimal import Decimal
from unittest import mock

import pytest

sys.path.insert(0, "projects/steam-trade-bot/app")

from market_inventory_monitor import (
    InventoryProfitabilityMonitor,
    InventoryItem,
    InventoryOpportunity,
    InventoryExclusion,
    InventoryMonitorResult,
    create_monitor,
)
from market_opportunity_scanner import OpportunityClassification, LiquidityEvidence


# ============================================================
# FIXTURES
# ============================================================


def create_test_db(path: str) -> str:
    """Create a test database with sample data."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE acquisition_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_transaction_id INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            original_quantity INTEGER NOT NULL CHECK(original_quantity > 0),
            remaining_quantity INTEGER NOT NULL CHECK(remaining_quantity >= 0 AND remaining_quantity <= original_quantity),
            unit_cost TEXT,
            acquired_at TEXT NOT NULL,
            cost_status TEXT NOT NULL CHECK(cost_status IN ('TRACKED', 'UNKNOWN')),
            provenance TEXT,
            source_type TEXT,
            external_ref TEXT,
            acquisition_fee TEXT,
            all_in_cost TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            market_hash_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price TEXT NOT NULL,
            fees TEXT NOT NULL DEFAULT '0',
            total_value TEXT NOT NULL DEFAULT '0',
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            external_ref TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE inventory_items (
            id INTEGER PRIMARY KEY,
            snapshot_id INTEGER NOT NULL,
            bot_name TEXT NOT NULL,
            app_id INTEGER NOT NULL,
            context_id INTEGER NOT NULL,
            asset_id TEXT NOT NULL,
            class_id TEXT NOT NULL,
            instance_id TEXT,
            amount INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL,
            market_name TEXT,
            type TEXT,
            tradable INTEGER NOT NULL,
            marketable INTEGER NOT NULL,
            raw_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE inventory_snapshots (
            id INTEGER PRIMARY KEY,
            bot_name TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            app_id INTEGER NOT NULL,
            context_id INTEGER NOT NULL,
            item_count INTEGER NOT NULL,
            raw_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE market_prices (
            id INTEGER PRIMARY KEY,
            market_hash_name TEXT NOT NULL,
            app_id INTEGER NOT NULL,
            currency INTEGER NOT NULL,
            currency_name TEXT NOT NULL,
            lowest_price TEXT,
            median_price TEXT,
            volume INTEGER,
            lowest_price_value TEXT,
            median_price_value TEXT,
            fetched_at TEXT NOT NULL,
            fetched_at_unix INTEGER NOT NULL,
            success INTEGER NOT NULL,
            error TEXT,
            source TEXT NOT NULL
        )
    """)

    # Insert test data
    # Profitable item: cost=10.00, fee=1.50, all_in=11.50, seller_proceeds=15.00
    conn.execute("""
        INSERT INTO acquisition_lots
        (source_transaction_id, market_hash_name, bot_name, original_quantity, remaining_quantity,
         unit_cost, acquired_at, cost_status, acquisition_fee, all_in_cost)
        VALUES (1, 'Test Profitable Item', 'Rixqor', 5, 3, '10.00', '2024-01-01T00:00:00Z', 'TRACKED', '1.50', '11.50')
    """)
    # Loss item: cost=20.00, fee=3.00, all_in=23.00, seller_proceeds=20.00
    conn.execute("""
        INSERT INTO acquisition_lots
        (source_transaction_id, market_hash_name, bot_name, original_quantity, remaining_quantity,
         unit_cost, acquired_at, cost_status, acquisition_fee, all_in_cost)
        VALUES (2, 'Test Loss Item', 'Rixqor', 3, 2, '20.00', '2024-01-01T00:00:00Z', 'TRACKED', '3.00', '23.00')
    """)
    # Unknown cost item
    conn.execute("""
        INSERT INTO acquisition_lots
        (source_transaction_id, market_hash_name, bot_name, original_quantity, remaining_quantity,
         unit_cost, acquired_at, cost_status, acquisition_fee, all_in_cost)
        VALUES (3, 'Test Unknown Item', 'Rixqor', 2, 1, '5.00', '2024-01-01T00:00:00Z', 'UNKNOWN', NULL, NULL)
    """)
    # Not marketable item
    conn.execute("""
        INSERT INTO acquisition_lots
        (source_transaction_id, market_hash_name, bot_name, original_quantity, remaining_quantity,
         unit_cost, acquired_at, cost_status, acquisition_fee, all_in_cost)
        VALUES (4, 'Not Marketable', 'Rixqor', 1, 1, '5.00', '2024-01-01T00:00:00Z', 'TRACKED', NULL, '5.00')
    """)
    # Zero remaining
    conn.execute("""
        INSERT INTO acquisition_lots
        (source_transaction_id, market_hash_name, bot_name, original_quantity, remaining_quantity,
         unit_cost, acquired_at, cost_status, acquisition_fee, all_in_cost)
        VALUES (5, 'Sold Out Item', 'Rixqor', 1, 0, '10.00', '2024-01-01T00:00:00Z', 'TRACKED', NULL, '10.00')
    """)

    # Insert inventory items
    conn.execute("""
        INSERT INTO inventory_snapshots (bot_name, captured_at, app_id, context_id, item_count, raw_json, created_at)
        VALUES ('Rixqor', '2024-01-01T00:00:00Z', 730, 2, 5, '{}', '2024-01-01T00:00:00Z')
    """)
    snapshot_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute("""
        INSERT INTO inventory_items (snapshot_id, bot_name, app_id, context_id, asset_id, class_id, amount, market_hash_name, market_name, type, tradable, marketable)
        VALUES (?, 'Rixqor', 730, 2, 'asset1', '12345', 3, 'Test Profitable Item', 'Test Profitable Item', 'Type', 1, 1)
    """, (snapshot_id,))
    conn.execute("""
        INSERT INTO inventory_items (snapshot_id, bot_name, app_id, context_id, asset_id, class_id, amount, market_hash_name, market_name, type, tradable, marketable)
        VALUES (?, 'Rixqor', 730, 2, 'asset2', '12346', 2, 'Test Loss Item', 'Test Loss Item', 'Type', 1, 1)
    """, (snapshot_id,))
    conn.execute("""
        INSERT INTO inventory_items (snapshot_id, bot_name, app_id, context_id, asset_id, class_id, amount, market_hash_name, market_name, type, tradable, marketable)
        VALUES (?, 'Rixqor', 730, 2, 'asset3', '12347', 1, 'Test Unknown Item', 'Test Unknown Item', 'Type', 1, 1)
    """, (snapshot_id,))
    conn.execute("""
        INSERT INTO inventory_items (snapshot_id, bot_name, app_id, context_id, asset_id, class_id, amount, market_hash_name, market_name, type, tradable, marketable)
        VALUES (?, 'Rixqor', 730, 2, 'asset4', '12348', 1, 'Not Marketable', 'Not Marketable', 'Type', 0, 0)
    """, (snapshot_id,))
    conn.execute("""
        INSERT INTO inventory_items (snapshot_id, bot_name, app_id, context_id, asset_id, class_id, amount, market_hash_name, market_name, type, tradable, marketable)
        VALUES (?, 'Rixqor', 730, 2, 'asset5', '12349', 1, 'Sold Out Item', 'Sold Out Item', 'Type', 1, 1)
    """, (snapshot_id,))

    conn.commit()
    conn.close()
    return path


@pytest.fixture
def test_db():
    """Create a test database with sample data."""
    tmpdb = os.path.join(tempfile.gettempdir(), 'phase5f_test.db')
    if os.path.exists(tmpdb):
        os.unlink(tmpdb)
    create_test_db(tmpdb)
    yield tmpdb
    if os.path.exists(tmpdb):
        os.unlink(tmpdb)


@pytest.fixture
def mock_session():
    """Create a mock HTTP session."""
    return mock.MagicMock()


@pytest.fixture
def monitor(test_db, mock_session):
    """Create a monitor with test database and mock session."""
    return InventoryProfitabilityMonitor(
        db_path=test_db,
        session=mock_session,
        request_delay=0.0,
    )


@pytest.fixture
def sample_search_response():
    """Sample Steam Market search response."""
    return {
        "success": True,
        "total_count": 100,
        "results": [
            {
                "hash_name": "Test Profitable Item",
                "sell_price": 1500,  # 15.00 EUR
                "sale_price_text": "€15.00",
                "sell_listings": 100,
                "asset_description": {"appid": 730, "classid": "12345"},
            },
            {
                "hash_name": "Test Loss Item",
                "sell_price": 2000,  # 20.00 EUR
                "sale_price_text": "€20.00",
                "sell_listings": 50,
                "asset_description": {"appid": 730, "classid": "12346"},
            },
        ],
    }


# ============================================================
# INVENTORY RETRIEVAL TESTS
# ============================================================


class TestInventoryRetrieval:
    """Test inventory retrieval methods."""

    def test_get_inventory(self, monitor):
        """Should retrieve inventory items."""
        snapshot_id, items = monitor.get_inventory("Rixqor")

        assert snapshot_id is not None
        assert len(items) == 5
        assert all(isinstance(item, InventoryItem) for item in items)

    def test_get_inventory_missing_bot(self, monitor):
        """Should return empty for missing bot."""
        snapshot_id, items = monitor.get_inventory("NonExistentBot")

        assert snapshot_id is None
        assert len(items) == 0

    def test_inventory_item_fields(self, monitor):
        """Should populate all InventoryItem fields."""
        _, items = monitor.get_inventory("Rixqor")

        profitable = next((i for i in items if i.market_hash_name == "Test Profitable Item"), None)
        assert profitable is not None
        assert profitable.market_hash_name == "Test Profitable Item"
        assert profitable.appid == 730
        assert profitable.quantity == 3
        assert profitable.tradable is True
        assert profitable.marketable is True


# ============================================================
# ACQUISITION COST TESTS
# ============================================================


class TestAcquisitionCost:
    """Test acquisition cost retrieval."""

    def test_get_tracked_cost(self, monitor):
        """Should retrieve TRACKED acquisition cost."""
        cost = monitor.get_acquisition_cost("Test Profitable Item", "Rixqor")

        assert cost is not None
        assert cost.unit_cost == Decimal("10.00")
        assert cost.acquisition_fee == Decimal("1.50")
        assert cost.all_in_cost == Decimal("11.50")
        assert cost.cost_status == "TRACKED"

    def test_get_unknown_cost(self, monitor):
        """Should return None for UNKNOWN cost status."""
        cost = monitor.get_acquisition_cost("Test Unknown Item", "Rixqor")

        assert cost is None

    def test_get_missing_cost(self, monitor):
        """Should return None for missing item."""
        cost = monitor.get_acquisition_cost("Missing Item", "Rixqor")

        assert cost is None

    def test_zero_remaining_excluded(self, monitor):
        """Should exclude lots with zero remaining quantity."""
        cost = monitor.get_acquisition_cost("Sold Out Item", "Rixqor")

        assert cost is None


# ============================================================
# SELLER PROCEEDS TESTS
# ============================================================


class TestSellerProceeds:
    """Test seller proceeds retrieval."""

    def test_get_seller_proceeds(self, monitor, sample_search_response, mock_session):
        """Should retrieve seller proceeds from Steam Market."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_response
        mock_session.get.return_value = mock_response

        proceeds, listings = monitor.get_current_seller_proceeds("Test Profitable Item", 730)

        assert proceeds == Decimal("15.00")
        assert listings == 100

    def test_get_seller_proceeds_missing(self, monitor, mock_session):
        """Should return None for missing item."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "results": []}
        mock_session.get.return_value = mock_response

        proceeds, listings = monitor.get_current_seller_proceeds("Missing Item", 730)

        assert proceeds is None
        assert listings is None

    def test_get_seller_proceeds_http_error(self, monitor, mock_session):
        """Should return None on HTTP error."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 429
        mock_session.get.return_value = mock_response

        proceeds, listings = monitor.get_current_seller_proceeds("Any Item", 730)

        assert proceeds is None
        assert listings is None


# ============================================================
# MONITOR TESTS
# ============================================================


class TestMonitor:
    """Test the main monitor functionality."""

    def test_monitor_profitable_item(self, monitor, mock_session, sample_search_response):
        """Profitable item should be classified VERIFIED_PROFITABLE."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_response
        mock_session.get.return_value = mock_response

        result = monitor.monitor_inventory("Rixqor", limit=10)

        profitable = next((o for o in result.opportunities if o.market_hash_name == "Test Profitable Item"), None)
        assert profitable is not None
        assert profitable.classification == OpportunityClassification.VERIFIED_PROFITABLE
        assert profitable.expected_profit == Decimal("33.50")  # (15.00 - 11.50) * 3
        # profit_margin = 33.50 / 11.50 = 2.913... (exact value, not rounded)
        assert abs(profitable.profit_margin - Decimal("2.913")) < Decimal("0.001")
        assert profitable.is_profitable is True

    def test_monitor_loss_item(self, monitor, mock_session):
        """Loss item should be classified LOSS."""
        # Use a search response where loss item has lower seller proceeds than all_in_cost
        loss_response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "hash_name": "Test Loss Item",
                    "sell_price": 1000,  # 10.00 EUR seller proceeds
                    "sale_price_text": "€10.00",
                    "sell_listings": 50,
                    "asset_description": {"appid": 730, "classid": "12346"},
                },
            ],
        }
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = loss_response
        mock_session.get.return_value = mock_response

        result = monitor.monitor_inventory("Rixqor", limit=10)

        loss_item = next((o for o in result.opportunities if o.market_hash_name == "Test Loss Item"), None)
        assert loss_item is not None
        assert loss_item.classification == OpportunityClassification.LOSS
        # all_in_cost=23.00, seller_proceeds=10.00, qty=2
        # total_proceeds = 10.00 * 2 = 20.00
        # expected_profit = 20.00 - 23.00 = -3.00
        assert loss_item.expected_profit == Decimal("-3.00")

    def test_monitor_unknown_cost_excluded(self, monitor):
        """Items with UNKNOWN cost should be excluded."""
        result = monitor.monitor_inventory("Rixqor", limit=10)

        unknown = next((e for e in result.exclusions if e.market_hash_name == "Test Unknown Item"), None)
        assert unknown is not None
        assert unknown.category == "NO_ACQUISITION"

    def test_monitor_not_marketable_excluded(self, monitor):
        """Non-marketable items should be excluded."""
        result = monitor.monitor_inventory("Rixqor", limit=10)

        not_marketable = next((e for e in result.exclusions if e.market_hash_name == "Not Marketable"), None)
        assert not_marketable is not None
        assert not_marketable.category == "NOT_MARKETABLE"

    def test_monitor_sold_out_excluded(self, monitor):
        """Items with zero remaining should be excluded."""
        result = monitor.monitor_inventory("Rixqor", limit=10)

        # Sold Out Item has remaining_quantity=0 in acquisition_lots,
        # so get_acquisition_cost returns None, resulting in NO_ACQUISITION exclusion
        sold_out = next((e for e in result.exclusions if e.market_hash_name == "Sold Out Item"), None)
        assert sold_out is not None
        assert sold_out.category == "NO_ACQUISITION"

    def test_monitor_empty_inventory(self, monitor):
        """Should handle empty inventory."""
        result = monitor.monitor_inventory("NonExistentBot", limit=10)

        assert result.total_inventory_items == 0
        assert result.eligible_items == 0
        assert result.excluded_items == 0
        assert result.opportunities == []
        assert result.exclusions == []

    def test_monitor_classification_counts(self, monitor, mock_session, sample_search_response):
        """Should correctly count classifications."""
        # Use a response where Test Loss Item has seller_proceeds < all_in_cost
        loss_response = {
            "success": True,
            "total_count": 100,
            "results": [
                {"hash_name": "Test Loss Item", "sell_price": 1000, "sale_price_text": "€10.00", "sell_listings": 50},
                {"hash_name": "Test Profitable Item", "sell_price": 1500, "sale_price_text": "€15.00", "sell_listings": 100},
            ],
        }
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = loss_response
        mock_session.get.return_value = mock_response

        result = monitor.monitor_inventory("Rixqor", limit=10)

        # Test Profitable: (15.00-11.50)*3 = 10.50 profit -> VERIFIED_PROFITABLE
        # Test Loss: (10.00-23.00)*2 = -26.00 loss -> LOSS
        assert result.classification_counts.get("VERIFIED_PROFITABLE", 0) == 1
        assert result.classification_counts.get("LOSS", 0) == 1
        assert result.profitable_count == 1
        assert result.loss_count == 1
        assert result.unverified_count == 0

    def test_monitor_no_db_writes(self, monitor, mock_session, sample_search_response):
        """Monitor should not write to database."""
        import os
        db_path = monitor.db_path
        initial_size = os.path.getsize(db_path)

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_response
        mock_session.get.return_value = mock_response

        result = monitor.monitor_inventory("Rixqor", limit=10)

        final_size = os.path.getsize(db_path)
        assert initial_size == final_size

    def test_monitor_no_steam_writes(self, monitor, mock_session, sample_search_response):
        """Monitor should only use GET requests."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_response
        mock_session.get.return_value = mock_response

        monitor.monitor_inventory("Rixqor", limit=10)

        # Verify only GET was called
        calls = mock_session.get.call_args_list
        assert len(calls) > 0
        for call in calls:
            assert call[0][0].startswith("https://")

    def test_monitor_partial_quantity(self, monitor, mock_session, sample_search_response):
        """Should calculate economics against remaining quantity only."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_response
        mock_session.get.return_value = mock_response

        result = monitor.monitor_inventory("Rixqor", limit=10)

        profitable = next((o for o in result.opportunities if o.market_hash_name == "Test Profitable Item"), None)
        assert profitable is not None
        # quantity=3, all_in_cost=11.50 (for the lot)
        # expected_profit = (15.00 * 3) - 11.50 = 33.50
        assert profitable.expected_profit == Decimal("33.50")
        assert profitable.quantity == 3


# ============================================================
# FACTORY TESTS
# ============================================================


class TestFactory:
    """Test factory functions."""

    def test_create_monitor(self, test_db, mock_session):
        """create_monitor should create instance."""
        monitor = create_monitor(db_path=test_db, session=mock_session)
        assert isinstance(monitor, InventoryProfitabilityMonitor)
        assert monitor.db_path == test_db


# ============================================================
# EDGE CASE TESTS
# ============================================================


class TestEdgeCases:
    """Test edge cases."""

    def test_zero_quantity_in_inventory(self, test_db, mock_session):
        """Zero quantity items should be handled."""
        # Add a zero-quantity item to the test DB
        import sqlite3
        conn = sqlite3.connect(test_db)
        conn.execute("""
            INSERT INTO acquisition_lots
            (source_transaction_id, market_hash_name, bot_name, original_quantity, remaining_quantity,
             unit_cost, acquired_at, cost_status)
            VALUES (10, 'Zero Qty Item', 'Rixqor', 1, 0, '10.00', '2024-01-01T00:00:00Z', 'TRACKED')
        """)
        conn.execute("""
            INSERT INTO inventory_items (snapshot_id, bot_name, app_id, context_id, asset_id, class_id, amount, market_hash_name, market_name, type, tradable, marketable)
            VALUES (1, 'Rixqor', 730, 2, 'asset10', '12350', 0, 'Zero Qty Item', 'Zero Qty Item', 'Type', 1, 1)
        """)
        conn.commit()
        conn.close()

        monitor = InventoryProfitabilityMonitor(db_path=test_db, session=mock_session, request_delay=0.0)
        result = monitor.monitor_inventory("Rixqor", limit=10)

        zero_qty = next((e for e in result.exclusions if e.market_hash_name == "Zero Qty Item"), None)
        assert zero_qty is not None
        assert zero_qty.category == "ZERO_REMAINING"

    def test_negative_profit_margin(self, test_db, mock_session):
        """Negative profit margin should be LOSS."""
        monitor = InventoryProfitabilityMonitor(db_path=test_db, session=mock_session, request_delay=0.0)
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "results": [{"hash_name": "Test Loss Item", "sell_price": 1000, "sale_price_text": "€10.00", "sell_listings": 10}],
        }
        mock_session.get.return_value = mock_response

        result = monitor.monitor_inventory("Rixqor", limit=10)

        loss_item = next((o for o in result.opportunities if o.market_hash_name == "Test Loss Item"), None)
        assert loss_item is not None
        assert loss_item.classification == OpportunityClassification.LOSS
        assert loss_item.expected_profit < 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
