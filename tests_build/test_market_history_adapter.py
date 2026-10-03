import sys
sys.path.insert(0, "app")
from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests

from market_history_adapter import (
    MarketHistoryParseError,
    SteamMarketHistoryClient,
    SteamMarketHistoryParser,
)


def make_response(*, event_type="+", action="Purchased",
                  price="0,04€",
                  asset_id="19764829590",
                  market_hash_name="813780-Montezuma",
                  item_name="Montezuma",
                  row_prefix="5474697168089372672"):
    row_id = f"history_row_{row_prefix}_{asset_id}"

    row = f"""
<div class="market_listing_row market_recent_listing_row" id="{row_id}">
    <div class="market_listing_left_cell market_listing_gainorloss">
        {event_type}
    </div>
    <div class="market_listing_right_cell market_listing_their_price">
        <span class="market_table_value">
            <span class="market_listing_price">
                {price}
            </span>
        </span>
    </div>
    <div class="market_listing_item_name_block">
        <span class="market_listing_item_name">{item_name}</span>
        <br>
        <span class="market_listing_game_name">Test Game Trading Card</span>
        <div class="market_listing_listed_date_combined">
            {action}: 18 Apr
        </div>
    </div>
</div>
"""

    return {
        "success": True,
        "pagesize": 10,
        "total_count": 846,
        "start": 0,
        "assets": {
            "753": {
                "6": {
                    asset_id: {
                        "appid": 753,
                        "contextid": "6",
                        "id": asset_id,
                        "market_name": item_name,
                        "market_hash_name": market_hash_name,
                    }
                }
            }
        },
        "hovers": (
            f'<div id="{row_id}_name">'
            "CreateItemHoverFromContainer("
            "g_rgAssets,"
            f'"{row_id}_name",'
            '"753",'
            '"6",'
            f'"{asset_id}",'
            "0"
            ")"
            "</div>"
        ),
        "results_html": row,
    }


def test_valid_buy_from_real_steam_shape():
    result = SteamMarketHistoryParser().parse_response(make_response())

    assert len(result) == 1

    parsed = result[0]

    assert parsed.type == "BUY"
    assert parsed.market_hash_name == "813780-Montezuma"
    assert parsed.quantity == 1
    assert parsed.unit_price == Decimal("0.04")
    assert parsed.total_value == Decimal("0.04")
    assert parsed.fees is None
    assert parsed.timestamp is None
    assert parsed.external_ref == (
        "history_row_5474697168089372672_19764829590"
    )


def test_valid_sell_from_real_steam_shape():
    result = SteamMarketHistoryParser().parse_response(
        make_response(
            event_type="-",
            action="Sold",
            asset_id="19331069164",
            market_hash_name="1797760-VR Game of the Year (Trading Card)",
            item_name="VR Game of the Year (Trading Card)",
            row_prefix="3559533086940347396",
        )
    )

    assert result[0].type == "SELL"
    assert result[0].market_hash_name == (
        "1797760-VR Game of the Year (Trading Card)"
    )


def test_multiple_rows():
    first = make_response()
    second = make_response(
        event_type="-",
        action="Sold",
        price="0,01€",
        asset_id="19331069164",
        market_hash_name="1797760-VR Game of the Year (Trading Card)",
        item_name="VR Game of the Year (Trading Card)",
        row_prefix="3559533086940347396",
    )

    first["results_html"] += second["results_html"]

    first["assets"]["753"]["6"].update(second["assets"]["753"]["6"])
    first["hovers"] += second["hovers"]

    result = SteamMarketHistoryParser().parse_response(first)

    assert len(result) == 2
    assert result[0].type == "BUY"
    assert result[1].type == "SELL"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0,04€", Decimal("0.04")),
        ("1,25€", Decimal("1.25")),
        ("12,34€", Decimal("12.34")),
        ("1.234,56€", Decimal("1234.56")),
    ],
)
def test_localized_price_parsing(raw, expected):
    result = SteamMarketHistoryParser().parse_response(
        make_response(price=raw)
    )

    assert result[0].unit_price == expected


def test_quantity_is_one_because_response_has_no_quantity_field():
    result = SteamMarketHistoryParser().parse_response(make_response())

    assert result[0].quantity == 1


def test_fees_are_not_fabricated():
    result = SteamMarketHistoryParser().parse_response(make_response())

    assert result[0].fees is None


def test_timestamp_is_not_fabricated():
    result = SteamMarketHistoryParser().parse_response(make_response())

    assert result[0].timestamp is None


def test_external_ref_is_row_id_not_claimed_transaction_id():
    result = SteamMarketHistoryParser().parse_response(make_response())

    assert result[0].external_ref.startswith("history_row_")


def test_missing_asset_rejected():
    response = make_response()
    del response["assets"]["753"]["6"]["19764829590"]

    with pytest.raises(MarketHistoryParseError, match="asset"):
        SteamMarketHistoryParser().parse_response(response)


def test_missing_price_rejected():
    response = make_response()
    response["results_html"] = response["results_html"].replace(
        '<span class="market_listing_price">\n                0,04€\n            </span>',
        "",
    )

    with pytest.raises(MarketHistoryParseError, match="missing price"):
        SteamMarketHistoryParser().parse_response(response)


@pytest.mark.parametrize(
    "event_type,action",
    [
        ("+", "Sold"),
        ("-", "Purchased"),
    ],
)
def test_inconsistent_action_rejected(event_type, action):
    response = make_response(event_type=event_type, action=action)

    with pytest.raises(MarketHistoryParseError, match="disagree"):
        SteamMarketHistoryParser().parse_response(response)


def test_invalid_price_rejected():
    response = make_response(price="not-a-price")

    with pytest.raises(MarketHistoryParseError, match="invalid Steam price"):
        SteamMarketHistoryParser().parse_response(response)


def test_no_rows_with_empty_html_is_valid():
    response = make_response()
    response["results_html"] = ""

    assert SteamMarketHistoryParser().parse_response(response) == []


def test_nonempty_unknown_html_is_rejected():
    response = make_response()
    response["results_html"] = "<div>unknown</div>"

    with pytest.raises(MarketHistoryParseError, match="recognizable"):
        SteamMarketHistoryParser().parse_response(response)


def test_pagination_parameters_are_sent():
    session = Mock(spec=requests.Session)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"success": True, "events": []}
    session.get.return_value = response

    client = SteamMarketHistoryClient(
        session,
        base_url="https://steam.example.test",
    )

    client.fetch_page(start=200, count=50)

    session.get.assert_called_once_with(
        "https://steam.example.test/market/myhistory/render/",
        params={
            "start": 200,
            "count": 50,
            "norender": 1,
        },
    )


def test_invalid_pagination_rejected():
    session = Mock(spec=requests.Session)
    client = SteamMarketHistoryClient(session)

    with pytest.raises(ValueError):
        client.fetch_page(start=-1)

    with pytest.raises(ValueError):
        client.fetch_page(count=0)

    session.get.assert_not_called()


def test_http_error_wrapped():
    session = Mock(spec=requests.Session)
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError("401")
    session.get.return_value = response

    client = SteamMarketHistoryClient(session)

    with pytest.raises(RuntimeError, match="request failed"):
        client.fetch_page()


def test_invalid_json_rejected():
    session = Mock(spec=requests.Session)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.side_effect = ValueError("invalid")
    session.get.return_value = response

    client = SteamMarketHistoryClient(session)

    with pytest.raises(MarketHistoryParseError, match="JSON"):
        client.fetch_page()


def test_required_response_fields():
    parser = SteamMarketHistoryParser()

    with pytest.raises(MarketHistoryParseError, match="results_html"):
        parser.parse_response({"assets": {}})

    with pytest.raises(MarketHistoryParseError, match="assets"):
        parser.parse_response({"results_html": ""})


def test_asset_market_hash_name_is_required():
    response = make_response()
    del response["assets"]["753"]["6"]["19764829590"]["market_hash_name"]

    with pytest.raises(MarketHistoryParseError, match="market_hash_name"):
        SteamMarketHistoryParser().parse_response(response)
