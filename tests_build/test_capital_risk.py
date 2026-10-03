import sys
sys.path.insert(0, "/workspace/projects/steam-trade-bot")

from decimal import Decimal
from unittest.mock import patch

import capital_risk as capital_risk


def test_potential_proceeds():
    assert capital_risk.potential_proceeds(Decimal("2.50"), 4) == Decimal("10.00")


def test_potential_proceeds_zero_quantity():
    assert capital_risk.potential_proceeds(Decimal("2.50"), 0) == Decimal("0.00")


def test_potential_proceeds_missing_median_price():
    assert capital_risk.potential_proceeds(None, 4) is None


def test_potential_net_proceeds_reuses_existing_fee_calculation():
    with patch.object(
        capital_risk,
        "calculate_total_fees",
        return_value=Decimal("0.10"),
    ) as calculate_fees:
        result = capital_risk.potential_net_proceeds(Decimal("10.00"), 1)

    assert result == Decimal("9.90")
    calculate_fees.assert_called_once_with(Decimal("10.00"), None)


def test_inventory_value_estimate():
    assert capital_risk.inventory_value_estimate(Decimal("3.00"), 5) == Decimal("15.00")


def test_inventory_value_estimate_missing_median_price():
    assert capital_risk.inventory_value_estimate(None, 5) is None


def test_price_freshness_status_fresh():
    with patch.object(capital_risk.market_intelligence, "get_market_freshness", return_value=299):
        assert capital_risk.price_freshness_status("item") == "FRESH"


def test_price_freshness_status_stale():
    with patch.object(capital_risk.market_intelligence, "get_market_freshness", return_value=300):
        assert capital_risk.price_freshness_status("item") == "STALE"

    with patch.object(capital_risk.market_intelligence, "get_market_freshness", return_value=1799):
        assert capital_risk.price_freshness_status("item") == "STALE"


def test_price_freshness_status_very_stale():
    with patch.object(capital_risk.market_intelligence, "get_market_freshness", return_value=1800):
        assert capital_risk.price_freshness_status("item") == "VERY_STALE"


def test_price_freshness_status_missing_freshness():
    with patch.object(capital_risk.market_intelligence, "get_market_freshness", return_value=None):
        assert capital_risk.price_freshness_status("item") == "UNKNOWN"


def test_acquisition_cost_is_not_exposed():
    assert not hasattr(capital_risk, "acquisition_cost")


def test_account_balance_capital_remaining_exposure_and_risk_score_are_not_fabricated():
    for name in (
        "account_balance",
        "capital_remaining",
        "portfolio_exposure",
        "risk_score",
    ):
        assert not hasattr(capital_risk, name)
