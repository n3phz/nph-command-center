import sys
sys.path.insert(0, "/workspace/projects/steam-trade-bot")

from decimal import Decimal, ROUND_HALF_UP
from economic import (
    calculate_gross,
    calculate_steam_fee,
    calculate_game_fee,
    calculate_total_fees,
    calculate_net,
    calculate_profit,
    calculate_roi,
    calculate_margin,
    calculate_economics,
    _money,
)

def test_normal_sale():
    # unit_price 0.10, quantity 2 => gross 0.20, steam fee = max(0.01, 0.01) = 0.01
    gross = calculate_gross(0.10, 2)
    assert gross == Decimal('0.20')
    steam_fee = calculate_steam_fee(gross)
    assert steam_fee == Decimal('0.01')  # 5% of 0.20 = 0.01
    game_fee = calculate_game_fee(gross, None)
    assert game_fee == Decimal('0.00')
    total_fees = calculate_total_fees(gross, None)
    assert total_fees == Decimal('0.01')
    net = calculate_net(gross, None)
    assert net == Decimal('0.19')  # 0.20 - 0.01 = 0.19
    profit = calculate_profit(net, None)
    assert profit is None  # acquisition_cost unknown
    roi = calculate_roi(profit, None)
    assert roi is None
    margin = calculate_margin(profit, net)
    assert margin is None  # profit unknown => margin None

    econ = calculate_economics(0.10, 2, None, None)
    assert econ['gross_proceeds'] == Decimal('0.20')
    assert econ['steam_fee'] == Decimal('0.01')
    assert econ['game_fee'] == Decimal('0.00')
    assert econ['total_fees'] == Decimal('0.01')
    assert econ['net_proceeds'] == Decimal('0.19')
    assert econ['profit'] is None
    assert econ['roi'] is None
    assert econ['margin'] is None  # profit unknown => margin None


def test_minimum_steam_fee():
    # unit_price 0.01, quantity 1 => gross 0.01, steam fee = max(0.0005, 0.01) = 0.01
    gross = calculate_gross(0.01, 1)
    assert gross == Decimal('0.01')
    steam_fee = calculate_steam_fee(gross)
    assert steam_fee == Decimal('0.01')
    net = calculate_net(gross, None)
    assert net == Decimal('0.00')  # 0.01 - 0.01 = 0


def test_normal_steam_fee():
    # unit_price 0.50, quantity 1 => gross 0.50, steam fee = 0.025 -> rounded half-up = 0.03
    gross = calculate_gross(0.50, 1)
    assert gross == Decimal('0.50')
    steam_fee = calculate_steam_fee(gross)
    assert steam_fee == Decimal('0.03')  # 5% of 0.50 = 0.025 -> rounded to 0.03
    net = calculate_net(gross, None)
    assert net == Decimal('0.47')  # 0.50 - 0.03 = 0.47


def test_game_fee():
    # game fee 10% with TF2 category (assume game_fee_rate = 0.10)
    gross = calculate_gross(1.00, 1)
    steam_fee = calculate_steam_fee(gross)
    game_fee = calculate_game_fee(gross, 0.10)
    assert game_fee == Decimal('0.10')
    total_fees = calculate_total_fees(gross, 0.10)
    assert total_fees == steam_fee + game_fee
    net = calculate_net(gross, 0.10)
    assert net == gross - total_fees


def test_zero_acquisition_cost():
    net = calculate_net(Decimal('10.00'), None)
    profit = calculate_profit(net, 0)
    assert profit == net
    roi = calculate_roi(profit, 0)
    assert roi is None  # zero-cost ROI is None


def test_unknown_acquisition_cost():
    net = calculate_net(Decimal('10.00'), None)
    profit = calculate_profit(net, None)
    assert profit is None
    roi = calculate_roi(profit, None)
    assert roi is None


def test_positive_profit():
    profit = calculate_profit(Decimal('20.00'), Decimal('10.00'))
    assert profit == Decimal('10.00')
    roi = calculate_roi(profit, Decimal('10.00'))
    assert roi == Decimal('1.00')  # 10/10 = 1.00


def test_zero_profit():
    profit = calculate_profit(Decimal('5.00'), Decimal('5.00'))
    assert profit == Decimal('0.00')
    roi = calculate_roi(profit, Decimal('5.00'))
    assert roi == Decimal('0.00')
    # margin = 0 / net = 0
    margin = calculate_margin(profit, Decimal('5.00'))
    assert margin == Decimal('0.00')


def test_positive_margin():
    margin = calculate_margin(Decimal('10.00'), Decimal('50.00'))
    assert margin == Decimal('0.20')


def test_negative_margin():
    margin = calculate_margin(Decimal('-5.00'), Decimal('20.00'))
    assert margin == Decimal('-0.25')


def test_zero_profit_margin():
    profit = calculate_profit(Decimal('5.00'), Decimal('5.00'))
    assert profit == Decimal('0.00')
    roi = calculate_roi(profit, Decimal('5.00'))
    assert roi == Decimal('0.00')


def test_negative_profit():
    profit = calculate_profit(Decimal('3.00'), Decimal('5.00'))
    assert profit == Decimal('-2.00')
    roi = calculate_roi(profit, Decimal('5.00'))
    assert roi == Decimal('-0.40')  # -2/5 = -0.40


def test_roi():
    profit = calculate_profit(Decimal('8.00'), Decimal('4.00'))
    roi = calculate_roi(profit, Decimal('4.00'))
    assert roi == Decimal('1.00')  # profit=8-4=4, roi=4/4=1.00


def test_zero_cost_roi():
    profit = calculate_profit(Decimal('5.00'), Decimal('0.00'))
    roi = calculate_roi(profit, Decimal('0.00'))
    assert roi is None


def test_unknown_cost_roi():
    profit = calculate_profit(Decimal('5.00'), None)
    roi = calculate_roi(profit, None)
    assert roi is None


def test_negative_cost_roi():
    profit = calculate_profit(Decimal('5.00'), Decimal('-1.00'))
    roi = calculate_roi(profit, Decimal('-1.00'))
    assert roi is None  # non-positive acquisition cost rejected


def test_margin():
    # profit / net_proceeds
    assert calculate_margin(Decimal('0.80'), Decimal('1.00')) == Decimal('0.80')
    assert calculate_margin(Decimal('0.00'), Decimal('1.00')) == Decimal('0.00')
    assert calculate_margin(Decimal('-5.00'), Decimal('20.00')) == Decimal('-0.25')


def test_multiple_quantity():
    gross = calculate_gross(0.25, 4)
    assert gross == Decimal('1.00')
    steam_fee = calculate_steam_fee(gross)
    assert steam_fee == Decimal('0.05')  # 5% of 1.00 = 0.05
    net = calculate_net(gross, None)
    assert net == Decimal('0.95')


def test_rounding():
    # Example where rounding matters: 0.33 * 0.05 = 0.0165 -> rounded half-up = 0.02
    gross_calc = calculate_gross(0.33, 1)
    assert gross_calc == Decimal('0.33')
    steam_fee = calculate_steam_fee(gross_calc)
    assert steam_fee == Decimal('0.02')  # 5% of 0.33 = 0.0165 -> rounded to 0.02


def test_missing_price():
    # unit_price None
    gross = calculate_gross(None, 1)
    assert gross is None
    # subsequent calls should return None for missing gross
    steam_fee = calculate_steam_fee(gross)
    assert steam_fee is None
    game_fee = calculate_game_fee(gross, 0.10)
    assert game_fee is None
    total_fees = calculate_total_fees(gross, 0.10)
    assert total_fees is None
    net = calculate_net(gross, None)
    assert net is None


def test_zero_gross():
    # quantity = 0
    gross = calculate_gross(1.00, 0)
    assert gross == Decimal('0.00')
    steam_fee = calculate_steam_fee(gross)
    assert steam_fee == Decimal('0.00')  # no minimum fee on zero-value transaction
    net = calculate_net(gross, None)
    assert net == Decimal('0.00')


def test_acquisition_cost_total_semantics():
    """
    acquisition_cost is the TOTAL cost for the quantity being calculated,
    not unit cost. Verify with quantity=4, unit_price=0.15 (gross=0.60),
    total acquisition cost=0.40.
    """
    econ = calculate_economics(0.15, 4, 0.40, None)
    assert econ['gross_proceeds'] == Decimal('0.60')
    assert econ['steam_fee'] == Decimal('0.03')  # 5% of 0.60 = 0.03
    assert econ['net_proceeds'] == Decimal('0.57')  # 0.60 - 0.03
    # profit = net - total_acquisition_cost = 0.57 - 0.40 = 0.17
    assert econ['profit'] == Decimal('0.17')
    # roi = profit / acquisition_cost = 0.17 / 0.40 = 0.425 -> 0.43
    assert econ['roi'] == Decimal('0.43')
    # margin = profit / net_proceeds = 0.17 / 0.57 = 0.298... -> 0.30
    assert econ['margin'] == Decimal('0.30')


def test_edge_cases():
    gross = calculate_gross(1.00, 0)
    assert gross == Decimal('0.00')
    steam_fee = calculate_steam_fee(gross)
    assert steam_fee == Decimal('0.00')  # no minimum fee on zero gross
    net = calculate_net(gross, None)
    assert net == Decimal('0.00')  # 0 - 0 = 0
