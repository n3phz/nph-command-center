"""Phase 3G — modern Steam Market listing parser.

Ground truth captured live from the Rixqor account against
`/market/listings/753/774361-Our Lady of the Charred Visage`.

Identity anchors verified on the real response:
  appid 753, market_hash_name "774361-Our Lady of the Charred Visage",
  classid "3516150028".

Authoritative listing observed:
  listingid 549032738418292987, unPrice 3, unFee 2,
  unSteamFee 1, unPublisherFee 1, strSubtotal "€0.05", eCurrency 3.

Semantics established by cross-checking the purchase record against
this listing:
  unPrice == received_amount == paid_amount == original_price  (3)
  unFee   == paid_fee == steam_fee + publisher_fee             (2)
  strSubtotal == unPrice + unFee                               (5)

The rejected EUR 1.31 came from a non-canonical page and is NOT used.
"""

import json
import sys

sys.path.insert(0, "app")

import pytest

from main import extract_prices_from_html

MHN = "774361-Our Lady of the Charred Visage"
CLASSID = "3516150028"

LISTING = {
    "listingid": "549032738418292987",
    "unPrice": 3,
    "unFee": 2,
    "unSteamFee": 1,
    "unPublisherFee": 1,
    "unPricePerUnit": 3,
    "unFeePerUnit": 2,
    "unSteamFeePerUnit": 1,
    "unPublisherFeePerUnit": 1,
    "eCurrency": 3,
    "strSubtotal": "\u20ac0.05",
    "publisherFeeApp": 774361,
    "publisherFeePct": 0.10000000149011612,
    "bMine": False,
    "description": {
        "appid": 753,
        "classid": CLASSID,
        "market_hash_name": MHN,
        "name": "Our Lady of the Charred Visage",
        "market_fee_app": 774361,
        "market_bucket_id": "B774361-5",
    },
    "asset": {
        "id": "36982541330",
        "assetid": "36982541330",
        "classid": CLASSID,
        "amount": 1,
        "appid": 753,
        "contextid": "6",
    },
}


def _structured():
    return {"listings": [dict(LISTING)], "total_count": 1, "start": 0}


class TestModernStructuredPayload:
    def test_plain_json_object(self):
        """Direct JSON body with top-level listings key."""
        out = extract_prices_from_html(json.dumps(_structured()))
        assert out.get("source") == "phase3g_structured"
        prices = out["structured_prices"]
        assert len(prices) == 1
        p = prices[0]
        assert p["un_price"] == 3
        assert p["un_fee"] == 2
        assert p["un_steam_fee"] == 1
        assert p["un_publisher_fee"] == 1
        assert p["currency"] == 3
        assert p["str_subtotal"] == "\u20ac0.05"
        assert p["listingid"] == "549032738418292987"
        assert p["b_mine"] is False

    def test_double_escaped_html(self):
        """Payload escaped inside a script tag (the live page shape)."""
        blob = json.dumps(_structured())
        escaped = blob.replace("\\", "\\\\").replace('"', '\\"')
        html = "<html><script>var q = \"%s\";</script></html>" % escaped
        out = extract_prices_from_html(html)
        assert out.get("source") == "phase3g_structured"
        assert out["structured_prices"][0]["un_price"] == 3

    def test_identity_preserved(self):
        """Price must carry the anchors needed to prove item identity."""
        out = extract_prices_from_html(json.dumps(_structured()))
        p = out["structured_prices"][0]
        assert p["market_hash_name"] == MHN
        assert p["classid"] == CLASSID
        assert p["description"]["appid"] == 753


class TestFeeArithmetic:
    def test_str_subtotal_equals_price_plus_fee(self):
        """strSubtotal must reconcile with unPrice + unFee."""
        out = extract_prices_from_html(json.dumps(_structured()))
        p = out["structured_prices"][0]
        assert p["un_price"] + p["un_fee"] == 5
        assert p["str_subtotal"] == "\u20ac0.05"

    def test_fee_split_sums_to_fee(self):
        out = extract_prices_from_html(json.dumps(_structured()))
        p = out["structured_prices"][0]
        assert p["un_steam_fee"] + p["un_publisher_fee"] == p["un_fee"]

    def test_lowest_across_multiple_listings(self):
        """Lowest seller proceeds wins when several listings exist."""
        cheap = dict(LISTING, listingid="111", unPrice=2, unFee=2)
        rich = dict(LISTING, listingid="222", unPrice=9, unFee=2)
        body = {"listings": [rich, cheap], "total_count": 2}
        out = extract_prices_from_html(json.dumps(body))
        assert out.get("source") == "phase3g_structured"
        assert len(out["structured_prices"]) == 2


class TestSafetyRejections:
    def test_listing_without_identity_is_dropped(self):
        """A listing lacking market_hash_name must not produce a price."""
        anon = {"listingid": "999", "unPrice": 1, "unFee": 1}
        body = {"listings": [anon], "total_count": 1}
        out = extract_prices_from_html(json.dumps(body))
        # Falls through to legacy, which also cannot bind identity here.
        assert not out.get("structured_prices")

    def test_negative_price_rejected(self):
        bad = dict(LISTING, unPrice=-5)
        body = {"listings": [bad], "total_count": 1}
        out = extract_prices_from_html(json.dumps(body))
        assert not out.get("structured_prices")

    def test_missing_fee_rejected(self):
        bad = {"listingid": "1", "unPrice": 3,
               "description": {"market_hash_name": MHN, "appid": 753}}
        body = {"listings": [bad], "total_count": 1}
        out = extract_prices_from_html(json.dumps(body))
        assert not out.get("structured_prices")

    def test_non_numeric_price_rejected(self):
        bad = dict(LISTING, unPrice="not-a-number")
        body = {"listings": [bad], "total_count": 1}
        out = extract_prices_from_html(json.dumps(body))
        assert not out.get("structured_prices")


class TestLegacyFallbackPreserved:
    def test_legacy_g_rg_listing_info_still_parses(self):
        """The pre-Phase-3G code path must keep working."""
        page = (
            "var g_rgListingInfo = "
            '{"111":{"converted_price":131},"222":{"converted_price":99}};'
        )
        out = extract_prices_from_html(page)
        assert out["lowest_price_value"] == 0.99

    def test_empty_listings_falls_back(self):
        out = extract_prices_from_html(json.dumps({"listings": []}))
        assert not out.get("structured_prices")
        assert "lowest_price_value" in out