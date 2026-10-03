import sys
sys.path.insert(0, "app")
from decision_engine import (
    ACTION_IGNORE,
    ACTION_SELL,
    ACTION_WATCH,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    FRESH,
    STALE,
    UNKNOWN,
    VERY_STALE,
    decide_inventory_action,
)


def test_fresh_actionable_item_is_sell():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=50,
    )

    assert result["action"] == ACTION_SELL
    assert result["confidence"] == CONFIDENCE_HIGH


def test_fresh_score_above_baseline_is_sell():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=90,
    )

    assert result["action"] == ACTION_SELL


def test_fresh_non_actionable_item_is_ignore():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=49,
    )

    assert result["action"] == ACTION_IGNORE
    assert result["confidence"] == CONFIDENCE_HIGH


def test_missing_price_is_watch():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=None,
        freshness_status=FRESH,
        economic_score=100,
    )

    assert result["action"] == ACTION_WATCH
    assert result["confidence"] == CONFIDENCE_LOW


def test_missing_quantity_is_watch():
    result = decide_inventory_action(
        quantity=None,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=100,
    )

    assert result["action"] == ACTION_WATCH
    assert result["confidence"] == CONFIDENCE_LOW


def test_zero_quantity_is_ignore():
    result = decide_inventory_action(
        quantity=0,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=100,
    )

    assert result["action"] == ACTION_IGNORE


def test_negative_quantity_is_ignore():
    result = decide_inventory_action(
        quantity=-1,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=100,
    )

    assert result["action"] == ACTION_IGNORE


def test_unknown_freshness_is_watch():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=UNKNOWN,
        economic_score=100,
    )

    assert result["action"] == ACTION_WATCH
    assert result["confidence"] == CONFIDENCE_LOW


def test_very_stale_is_watch():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=VERY_STALE,
        economic_score=100,
    )

    assert result["action"] == ACTION_WATCH
    assert result["confidence"] == CONFIDENCE_LOW


def test_stale_is_watch():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=STALE,
        economic_score=100,
    )

    assert result["action"] == ACTION_WATCH
    assert result["confidence"] == CONFIDENCE_MEDIUM


def test_stale_never_produces_sell():
    for freshness in (STALE, VERY_STALE, UNKNOWN):
        result = decide_inventory_action(
            quantity=2,
            median_price_value=1.00,
            freshness_status=freshness,
            economic_score=100,
        )
        assert result["action"] != ACTION_SELL


def test_invalid_quantity_is_watch():
    result = decide_inventory_action(
        quantity="invalid",
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=100,
    )

    assert result["action"] == ACTION_WATCH
    assert result["confidence"] == CONFIDENCE_LOW


def test_invalid_score_is_watch():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score="invalid",
    )

    assert result["action"] == ACTION_WATCH
    assert result["confidence"] == CONFIDENCE_LOW


def test_no_fabricated_economic_or_portfolio_fields():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=50,
    )

    forbidden = {
        "acquisition_cost",
        "account_balance",
        "capital_remaining",
        "portfolio_exposure",
        "position",
        "realized_profit",
        "unrealized_profit",
        "predicted_price",
        "risk_score",
        "liquidity_score",
    }

    assert not (forbidden & result.keys())


def test_no_new_scoring_formula_is_exposed():
    result = decide_inventory_action(
        quantity=2,
        median_price_value=1.00,
        freshness_status=FRESH,
        economic_score=50,
    )

    assert set(result) == {"action", "reason", "confidence"}
