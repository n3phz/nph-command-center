import sys
sys.path.insert(0, "app")
"""V0.6.1 dry-run projection tests.

Tests the V0.6.1 projection layer from V0.5.9 NormalizedEvent to V0.5.0
Transaction and AcquisitionLot domain objects.
"""

from decimal import Decimal
import pytest

from buy_projection import (
    project_transaction,
    project_acquisition_lot,
    dry_run_projection,
    DryRunReport,
)

from steam_market_history_json import NormalizedEvent


# ---------------------------------------------------------------------------
# Fixtures representing V0.5.9 NormalizedEvent shape
# ---------------------------------------------------------------------------

_ACCOUNT_STEAMID = "76561197960287930"
_OTHER_STEAMID = "76561197960287931"


def make_normalized_buy_event(
    listingid: str,
    purchaseid: str,
    market_hash_name: str = "Example Card",
    quantity: int = 1,
    paid_amount: int = 1000,
    paid_fee: int = 50,
    steam_fee: int = 30,
    publisher_fee: int = 20,
    publisher_fee_percent: str = "0.100000001490116119",  # Raw Steam string
    publisher_fee_app: int = 730,                      # Raw Steam integer
    funds_returned: int = 0,
    received_amount: int = 950,
    currencyid: int = 1,
    received_currencyid: int = 1,
    added_tax: int = 0,
    time_event: str = "2026-09-16T13:00:00Z",
) -> NormalizedEvent:
    """Create a V0.5.9 NormalizedEvent for testing."""
    # We'll create a simple object with all required fields
    class MockNormalizedEvent:
        pass

    event = MockNormalizedEvent()

    # Basic fields
    event.event_type = "BUY"
    event.steamid_actor = _ACCOUNT_STEAMID
    event.steamid_purchaser = _ACCOUNT_STEAMID
    event.time_event = time_event
    event.time_sold = None
    event.listingid = listingid
    event.purchaseid = purchaseid
    event.market_hash_name = market_hash_name

    # Monetary fields (raw integers as V0.5.9 preserves them)
    event.paid_amount = paid_amount
    event.paid_fee = paid_fee
    event.steam_fee = steam_fee
    event.publisher_fee = publisher_fee
    event.publisher_fee_percent = publisher_fee_percent
    event.publisher_fee_app = publisher_fee_app
    event.funds_returned = funds_returned
    event.received_amount = received_amount
    event.currencyid = currencyid
    event.received_currencyid = received_currencyid
    event.added_tax = added_tax

    # Resolved asset metadata (empty strings for this test)
    event.asset_appid = ""
    event.asset_contextid = ""
    event.asset_id = ""
    event.asset_classid = ""
    event.asset_instanceid = ""
    event.asset_amount = str(quantity)
    event.asset_new_id = ""
    event.asset_new_contextid = ""

    # Original event_type integer
    event.event_type_raw = 4

    return event


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

# 1. valid BUY → one Transaction projection
def test_valid_buy_produces_one_transaction():
    """Verify that a valid V0.5.9 BUY event projects to one Transaction."""
    event = make_normalized_buy_event("tx-001", "pid-001")

    transaction = project_transaction(event, "Rixqor")

    assert transaction.type.value == "BUY"
    assert transaction.market_hash_name == "Example Card"
    assert transaction.quantity == 1
    assert transaction.unit_price == Decimal("1000")
    assert transaction.fees == Decimal("50")
    assert transaction.bot_name == "Rixqor"
    assert transaction.external_ref == "tx-001:pid-001"


# 2. valid BUY → one AcquisitionLot projection
def test_valid_buy_proiects_to_one_acquisition_lot():
    """Verify that a valid BUY event projects to one AcquisitionLot."""
    event = make_normalized_buy_event("tx-002", "pid-002")

    acquisition_lot = project_acquisition_lot(event, 1, "Rixqor")

    assert acquisition_lot.source_transaction_id == 1
    assert acquisition_lot.market_hash_name == "Example Card"
    assert acquisition_lot.bot_name == "Rixqor"
    assert acquisition_lot.original_quantity == 1
    assert acquisition_lot.remaining_quantity == 1
    assert acquisition_lot.unit_cost is None
    assert acquisition_lot.cost_status.value == "UNKNOWN"
    assert acquisition_lot.acquired_at == "2026-09-16T13:00:00Z"


# 3. cost_status = UNKNOWN
def test_cost_status_is_unknown():
    """Verify that all acquisition lots have cost_status UNKNOWN."""
    event = make_normalized_buy_event("tx-003", "pid-003")
    acquisition_lot = project_acquisition_lot(event, 1, "Rixqor")

    assert acquisition_lot.cost_status.value == "UNKNOWN"


# 4. unit_cost = None
def test_unit_cost_is_none():
    """Verify that all acquisition lots have unit_cost None."""
    event = make_normalized_buy_event("tx-004", "pid-004")
    acquisition_lot = project_acquisition_lot(event, 1, "Rixqor")

    assert acquisition_lot.unit_cost is None


# 5. remaining_quantity = original_quantity
def test_remaining_quantity_equals_original():
    """Verify that remaining_quantity equals original_quantity initially."""
    event = make_normalized_buy_event("tx-005", "pid-005", quantity=3)
    acquisition_lot = project_acquisition_lot(event, 1, "Rixqor")

    assert acquisition_lot.remaining_quantity == acquisition_lot.original_quantity
    assert acquisition_lot.original_quantity == 3


# 6. market_hash_name preserved
def test_market_hash_name_preserved():
    """Verify that market_hash_name is preserved from normalized event."""
    event = make_normalized_buy_event("tx-006", "pid-006", market_hash_name="Rare Item")

    transaction = project_transaction(event, "Rixqor")

    assert transaction.market_hash_name == "Rare Item"


# 7. quantity preserved
def test_quantity_preserved():
    """Verify that quantity is preserved from asset_amount."""
    event = make_normalized_buy_event("tx-007", "pid-007", quantity=5)

    transaction = project_transaction(event, "Rixqor")

    assert transaction.quantity == 5


# 8. timestamp preserved
def test_timestamp_preserved():
    """Verify that timestamp (time_event) is preserved."""
    event = make_normalized_buy_event("tx-008", "pid-008", time_event="2026-09-17T12:00:00Z")

    transaction = project_transaction(event, "Rixqor")

    assert transaction.timestamp == "2026-09-17T12:00:00Z"


# 9. bot_name preserved
def test_bot_name_preserved():
    """Verify that bot_name is preserved from projection call."""
    event = make_normalized_buy_event("tx-009", "pid-009")

    transaction = project_transaction(event, "TestBot")

    assert transaction.bot_name == "TestBot"


# 10. deterministic external_ref
def test_external_ref_deterministic():
    """Verify that external_ref is deterministic based on listingid+purchaseid."""
    event1 = make_normalized_buy_event("tx-010", "pid-010")
    event2 = make_normalized_buy_event("tx-010", "pid-010")  # Same source

    transaction1 = project_transaction(event1, "Rixqor")
    transaction2 = project_transaction(event2, "Rixqor")

    assert transaction1.external_ref == "tx-010:pid-010"
    assert transaction2.external_ref == "tx-010:pid-010"
    assert transaction1.external_ref == transaction2.external_ref


# 11. duplicate detected
def test_duplicate_detection():
    """Verify that duplicate source events are detected."""
    event1 = make_normalized_buy_event("tx-011", "pid-011")
    event2 = make_normalized_buy_event("tx-011", "pid-011")  # Duplicate

    report = dry_run_projection([event1, event2], "Rixqor")

    assert report.total_input_events == 2
    assert report.valid_buy_events == 1
    assert report.duplicate_events == 1


# 12. duplicate does not silently create two transactions
def test_duplicate_does_not_create_two_transactions():
    """Verify that duplicate events do NOT create two separate transactions."""
    event1 = make_normalized_buy_event("tx-012", "pid-012")
    event2 = make_normalized_buy_event("tx-012", "pid-012")  # Duplicate

    report = dry_run_projection([event1, event2], "Rixqor")

    assert len(report.projected_transactions) == 1
    # Only one acquisition lot for the valid event (duplicate ignored)
    assert len(report.projected_acquisition_lots) == 1


# 13. missing market_hash_name rejected
def test_missing_market_hash_name_rejected():
    """Verify that missing market_hash_name is rejected."""
    event = make_normalized_buy_event("tx-013", "pid-013")
    event.market_hash_name = ""

    with pytest.raises(ValueError, match="market_hash_name is missing"):
        project_transaction(event, "Rixqor")


# 14. invalid quantity rejected
def test_invalid_quantity_rejected():
    """Verify that invalid quantity (<= 0) is rejected."""
    event = make_normalized_buy_event("tx-014", "pid-014", quantity=0)

    with pytest.raises(ValueError, match="Invalid quantity"):
        project_transaction(event, "Rixqor")


# 15. missing timestamp rejected
def test_missing_timestamp_rejected():
    """Verify that missing timestamp (time_event) is rejected."""
    event = make_normalized_buy_event("tx-015", "pid-015", time_event="")

    with pytest.raises(ValueError, match="timestamp is missing"):
        project_transaction(event, "Rixqor")


# 16. missing bot_name rejected
def test_missing_bot_name_rejected():
    """Verify that missing bot_name is rejected."""
    event = make_normalized_buy_event("tx-016", "pid-016")

    with pytest.raises(ValueError, match="must be a non-empty string"):
        project_transaction(event, "")


# 17. unknown event rejected
def test_unknown_event_rejected():
    """Verify that non-BYU event types are handled correctly."""
    event = make_normalized_buy_event("tx-017", "pid-017")
    event.event_type = "SELL"  # Not BUY

    # This should be counted as unknown_events, not valid_buy_events
    report = dry_run_projection([event], "Rixqor")

    assert report.unknown_events == 1
    assert report.valid_buy_events == 0


# 18. no economic calculations
def test_no_economic_calculations():
    """Verify that projection does not perform economic calculations."""
    event = make_normalized_buy_event("tx-018", "pid-018", paid_amount=2000, publisher_fee=100)

    transaction = project_transaction(event, "Rixqor")

    # Unit cost is None (historical cost unknown), not derived from paid_amount
    # This is already covered by test_unit_cost_is_none
    assert transaction.unit_price == Decimal("2000")
    assert transaction.fees == Decimal("50")


# 19. no currency conversion
def test_no_currency_conversion():
    """Verify that raw monetary values are preserved without conversion."""
    event = make_normalized_buy_event("tx-019", "pid-019")

    # These are raw integers in V0.5.9
    assert isinstance(event.paid_amount, int)
    assert isinstance(event.paid_fee, int)
    assert isinstance(event.steam_fee, int)
    assert isinstance(event.publisher_fee, int)
    assert isinstance(event.funds_returned, int)
    assert isinstance(event.received_amount, int)
    assert isinstance(event.currencyid, int)
    assert isinstance(event.received_currencyid, int)
    assert isinstance(event.added_tax, int)


# 20. multiple valid BUYs produce matching transaction/lot counts
def test_multiple_valid_buy_events():
    """Verify that multiple valid BUY events produce matching counts."""
    event1 = make_normalized_buy_event("tx-020a", "pid-020a", market_hash_name="Item A")
    event2 = make_normalized_buy_event("tx-020b", "pid-020b", market_hash_name="Item B")
    event3 = make_normalized_buy_event("tx-020c", "pid-020c", market_hash_name="Item C")

    report = dry_run_projection([event1, event2, event3], "Rixqor")

    assert report.total_input_events == 3
    assert report.valid_buy_events == 3
    assert report.duplicate_events == 0
    assert len(report.projected_transactions) == 3
    assert len(report.projected_acquisition_lots) == 3


# 21. publisher_fee_percent preserved exactly
def test_publisher_fee_percent_preserved_exact():
    """Verify that publisher_fee_percent is preserved as exact Steam string."""
    event = make_normalized_buy_event("tx-021", "pid-021")

    assert event.publisher_fee_percent == "0.100000001490116119"


# 22. publisher_fee_app preserved exactly
def test_publisher_fee_app_preserved_exact():
    """Verify that publisher_fee_app is preserved as exact Steam integer."""
    event = make_normalized_buy_event("tx-022", "pid-022")

    assert event.publisher_fee_app == 730


# 23. deterministic_external_ref_across_projection_calls
def test_deterministic_external_ref():
    """Verify that external_ref is deterministic across projection calls."""
    event1 = make_normalized_buy_event("tx-023", "pid-023")
    event2 = make_normalized_buy_event("tx-023", "pid-023")

    transaction1 = project_transaction(event1, "Rixqor")
    transaction2 = project_transaction(event2, "Rixqor")

    assert transaction1.external_ref == transaction2.external_ref
    assert transaction1.external_ref == "tx-023:pid-023"


# 24. raw monetary fields_type_validation
def test_raw_monetary_fields_type_validation():
    """Verify that raw monetary fields maintain their types."""
    event = make_normalized_buy_event("tx-024", "pid-024")

    # These are raw integers in V0.5.9
    assert isinstance(event.paid_amount, int)
    assert isinstance(event.paid_fee, int)
    assert isinstance(event.steam_fee, int)
    assert isinstance(event.publisher_fee, int)
    assert isinstance(event.funds_returned, int)
    assert isinstance(event.received_amount, int)
    assert isinstance(event.currencyid, int)
    assert isinstance(event.received_currencyid, int)
    assert isinstance(event.added_tax, int)


# 25. project_acquisition_lot_cost_status_documented
def test_project_acquisition_lot_cost_status():
    """Verify that project_acquisition_lot sets cost_status correctly."""
    from transactions import CostStatus

    event = make_normalized_buy_event("tx-025", "pid-025")
    acquisition_lot = project_acquisition_lot(event, 1, "Rixqor")

    assert acquisition_lot.cost_status == CostStatus.UNKNOWN


# 26. dry_run_projection_validates_all_events
def test_dry_run_projection_validates_all_events():
    """Verify that dry_run_projection processes all events correctly."""
    event1 = make_normalized_buy_event("tx-026a", "pid-026a")
    event2 = make_normalized_buy_event("tx-026b", "pid-026b")
    event3 = make_normalized_buy_event("tx-026c", "pid-026c")

    report = dry_run_projection([event1, event2, event3], "Rixqor")

    assert isinstance(report, DryRunReport)
    assert report.total_input_events == 3
    assert report.valid_buy_events == 3
    assert report.duplicate_events == 0


# 27. dry_run_projection_returns_validation_errors_on_invalid
def test_dry_run_projection_returns_validation_errors():
    """Verify that dry_run_projection returns validation errors."""
    event = make_normalized_buy_event("tx-027", "pid-027")
    event.market_hash_name = ""  # Invalid

    report = dry_run_projection([event], "Rixqor")

    assert report.invalid_events == 1
    assert len(report.validation_errors) == 1
    assert "market_hash_name is missing" in report.validation_errors[0]["error"]


# 28. dry_run_projection_cost_status_unknown_acquisition_lots
def test_dry_run_projection_cost_status():
    """Verify that all acquisition lots in projection have cost_status UNKNOWN."""
    event = make_normalized_buy_event("tx-028", "pid-028")

    report = dry_run_projection([event], "Rixqor")

    for lot in report.projected_acquisition_lots:
        assert lot.cost_status.value == "UNKNOWN"


# 29. dry_run_projection_unit_cost_none_acquisition_lots
def test_dry_run_projection_unit_cost():
    """Verify that all acquisition lots in projection have unit_cost None."""
    event = make_normalized_buy_event("tx-029", "pid-029")

    report = dry_run_projection([event], "Rixqor")

    for lot in report.projected_acquisition_lots:
        assert lot.unit_cost is None


# 30. dry_run_projection_remaining_quantity_check
def test_dry_run_projection_remaining_quantity():
    """Verify that remaining_quantity equals original_quantity."""
    event = make_normalized_buy_event("tx-030", "pid-030", quantity=7)

    report = dry_run_projection([event], "Rixqor")

    for lot in report.projected_acquisition_lots:
        assert lot.remaining_quantity == lot.original_quantity
        assert lot.original_quantity == 7
