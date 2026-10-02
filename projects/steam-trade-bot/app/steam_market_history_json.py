"""Pure JSON adapter for authenticated Steam Market History responses.

Accepts a decoded JSON dictionary returned by
GET /market/myhistory/render/?start=<start>&count=<count>&norender=1

This module is completely self-contained: it validates the response
shape, resolves events through purchases/listings/assets, and produces
normalized result records without any HTTP, HTML parsing, database
writes, or external state.

It does NOT:
- make network requests
- fabricate timestamps, fees, or exchange rates
- assume monetary values are EUR cents
- create acquisition lots or modify production data
- depend on the existing importer or parser

It DOES:
- validate the response envelope
- resolve event -> purchase via listingid + purchaseid
- resolve event/listing -> asset via the nested assets map
- resolve asset -> market_hash_name from the Steam asset hierarchy
- preserve all monetary values as raw integers (no conversion)
- classify BUY / UNKNOWN using an explicit account SteamID
- produce immutable dataclass results
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Tuple


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class MarketHistoryJSONError(ValueError):
    """Raised when the JSON response cannot be validated safely."""


class AssetMetadata(NamedTuple):
    appid: str
    contextid: str
    assetid: str
    classid: str
    instanceid: str
    amount: str
    new_id: str
    new_contextid: str


@dataclass(frozen=True)
class NormalizedEvent:
    """Immutable, pure result of adapting a single Steam market event.

    All monetary fields are preserved as raw integers supplied by Steam
    (no currency conversion, no EUR-cents assumption).

    If any required resolution fails, the factory returns None so the
    caller can decide whether to emit UNKNOWN or skip.
    """

    event_type: str            # "BUY" | "UNKNOWN"
    steamid_actor: str
    steamid_purchaser: str
    time_event: Optional[str]
    time_sold: Optional[str]
    listingid: str
    purchaseid: str
    market_hash_name: Optional[str]

    # Monetary fields — raw integers as received from Steam
    paid_amount: int
    paid_fee: int
    steam_fee: int
    publisher_fee: int
    publisher_fee_percent: Optional[str]
    publisher_fee_app: Optional[int]
    funds_returned: int
    received_amount: int
    currencyid: int
    received_currencyid: int
    added_tax: int

    # True only when Steam actually supplied a paid_fee field on this
    # purchase. Distinguishes a genuine zero fee from a field Steam did
    # not report, so accounting enrichment never writes a fabricated 0.
    paid_fee_present: bool = False

    # V0.5.9 normalization fields
    cost_status: str = "UNKNOWN"
    unit_cost: Optional[int] = None

    # Resolved asset metadata (all-empty strings if unresolved)
    asset_appid: str = ""
    asset_contextid: str = ""
    asset_id: str = ""
    asset_classid: str = ""
    asset_instanceid: str = ""
    asset_amount: str = ""
    asset_new_id: str = ""
    asset_new_contextid: str = ""

    # Original event_type integer when present (for extensibility)
    event_type_raw: Optional[int] = None


# ---------------------------------------------------------------------------
# Step 1 — top-level validation
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = ("success", "pagesize", "total_count", "start", "assets", "events", "purchases", "listings")


def validate_response(data: Mapping[str, Any]) -> None:
    """Validate the top-level Steam Market History JSON response."""
    if not isinstance(data, Mapping):
        raise MarketHistoryJSONError("response must be a JSON object (mapping)")

    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise MarketHistoryJSONError(f"missing required key(s): {', '.join(repr(k) for k in missing)}")

    if not isinstance(data["success"], bool):
        raise MarketHistoryJSONError("key 'success' must be bool")

    for key in ("pagesize", "total_count", "start"):
        val = data[key]
        if not isinstance(val, int) or val < 0:
            raise MarketHistoryJSONError(f"key '{key}' must be a non-negative integer")

    if data["pagesize"] == 0:
        raise MarketHistoryJSONError("key 'pagesize' must be a positive integer")

    if not isinstance(data["assets"], Mapping):
        raise MarketHistoryJSONError("key 'assets' must be a mapping")

    if not isinstance(data["events"], list):
        raise MarketHistoryJSONError("key 'events' must be a list")

    if not isinstance(data["purchases"], Mapping):
        raise MarketHistoryJSONError("key 'purchases' must be a mapping")

    if not isinstance(data["listings"], Mapping):
        raise MarketHistoryJSONError("key 'listings' must be a mapping")


# ---------------------------------------------------------------------------
# Step 2 — asset resolution
# ---------------------------------------------------------------------------

def resolve_asset_metadata(
    assets: Mapping[str, Any],
    asset_id: str,
) -> Optional[AssetMetadata]:
    """Resolve asset metadata from the nested *assets* structure.

    Steam structures it as assets[appid][contextid][assetid] -> leaf.
    Returns None when any level is missing (never fabricates).
    """
    if not isinstance(assets, Mapping) or not isinstance(asset_id, str) or not asset_id:
        return None

    for appid, ctx_map in assets.items():
        if not isinstance(ctx_map, Mapping):
            continue
        for contextid, asset_map in ctx_map.items():
            if not isinstance(asset_map, Mapping):
                continue
            leaf = asset_map.get(asset_id)
            if not isinstance(leaf, Mapping):
                continue
            return AssetMetadata(
                appid=str(appid),
                contextid=str(contextid),
                assetid=asset_id,
                classid=str(leaf.get("classid", "")),
                instanceid=str(leaf.get("instanceid", "")),
                amount=str(leaf.get("amount", "")),
                new_id=str(leaf.get("new_id", "")),
                new_contextid=str(leaf.get("new_contextid", "")),
            )
    return None


def resolve_market_hash_name(
    assets: Mapping[str, Any],
    asset_id: str,
) -> Optional[str]:
    """Look up market_hash_name from the nested assets structure."""
    meta = resolve_asset_metadata(assets, asset_id)
    if meta is None:
        return None
    for appid, ctx_map in assets.items():
        if not isinstance(ctx_map, Mapping):
            continue
        for contextid, asset_map in ctx_map.items():
            if not isinstance(asset_map, Mapping):
                continue
            leaf = asset_map.get(meta.assetid)
            if isinstance(leaf, Mapping):
                mhn = leaf.get("market_hash_name")
                if isinstance(mhn, str) and mhn.strip():
                    return mhn.strip()
    return None


# ---------------------------------------------------------------------------
# Step 3 — resolve listing -> asset id
# ---------------------------------------------------------------------------

def _resolve_listing_asset(
    listing: Mapping[str, Any],
) -> Tuple[str, Mapping[str, Any]]:
    """Return (asset_id, asset_leaf) for a listing.

    The listing may carry a nested 'asset' dict or flat appid/contextid/assetid.
    """
    asset_ref = listing.get("asset")
    if isinstance(asset_ref, Mapping):
        aid = asset_ref.get("assetid") or asset_ref.get("id")
        return str(aid) if aid else "", asset_ref

    # Flat fields
    aid = listing.get("assetid", "")
    if aid:
        return str(aid), listing

    # Try other common keys
    for key in ("id", "asset_id", "id_asset"):
        val = listing.get(key)
        if isinstance(val, str) and val:
            return val, listing

    return "", {}


# ---------------------------------------------------------------------------
# Step 4 — classifier
# ---------------------------------------------------------------------------

def classify_event(
    *,
    event_type_raw: Optional[int],
    steamid_actor: str,
    steamid_purchaser: str,
    listing: Mapping[str, Any],
    purchase: Mapping[str, Any],
    account_steamid: str,
) -> str:
    """Classify a single event as BUY or UNKNOWN.

    The classifier receives the *account* SteamID as an explicit argument
    and uses the complete event/purchase/listing context rather than
    event_type alone.

    Rules (explicit and testable, V0.5.8):

    BUY — all of the following are true:
          event_type == 4
          steamid_actor == account_steamid
          steamid_purchaser == account_steamid
          matching purchase exists (non-empty)
          matching listing exists (non-empty)
          purchase.failed == 0
          purchase.needs_rollback == 0

    UNKNOWN — insufficient evidence per the above, or the evidence
              does not cleanly match the BUY rule.

    We do NOT hard-code any other event_type as SELL.  The validated
    evidence is insufficient to establish a SELL classification rule.
    """
    actor = (steamid_actor or "").strip()
    purchaser = (steamid_purchaser or "").strip()
    acct = (account_steamid or "").strip()
    listing_has_content = bool(listing)
    purchase_has_content = bool(purchase)

    # Rule 1: BUY — validated authenticated evidence
    if (
        event_type_raw == 4
        and actor == acct
        and purchaser == acct
        and acct
        and listing_has_content
        and purchase_has_content
        and int(purchase.get("failed", 0)) == 0
        and int(purchase.get("needs_rollback", 0)) == 0
    ):
        return "BUY"

    # Rule 2: UNKNOWN — insufficient evidence
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Step 5 — single-event normalizer
# ---------------------------------------------------------------------------

def normalize_event(
    raw: Mapping[str, Any],
    purchases: Mapping[str, Any],
    listings: Mapping[str, Any],
    assets: Mapping[str, Any],
    account_steamid: str,
) -> Optional[NormalizedEvent]:
    """Convert a raw event dict into a normalized result.

    Returns None when evidence is insufficient (caller should then emit
    UNKNOWN or skip).
    """
    # Basic event fields
    listingid = raw.get("listingid")
    purchaseid = raw.get("purchaseid")
    event_type_raw = raw.get("event_type")
    steamid_actor = raw.get("steamid_actor")
    steamid_purchaser = raw.get("steamid_purchaser")
    time_event = raw.get("time_event")
    time_sold = raw.get("time_sold")

    # Normalize integer epoch timestamps to ISO-8601 strings (V0.5.9 compatibility)
    if isinstance(time_event, (int, float)) and not isinstance(time_event, bool):
        try:
            from datetime import datetime, timezone
            time_event = datetime.fromtimestamp(float(time_event), tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            time_event = None
    if isinstance(time_sold, (int, float)) and not isinstance(time_sold, bool):
        try:
            from datetime import datetime, timezone
            time_sold = datetime.fromtimestamp(float(time_sold), tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            time_sold = None

    if not isinstance(listingid, str) or not listingid.strip():
        return None
    if not isinstance(purchaseid, str) or not purchaseid.strip():
        return None
    if not isinstance(steamid_actor, str) or not steamid_actor.strip():
        return None

    # Resolve listing
    listing = listings.get(listingid) if isinstance(listings, Mapping) else None
    if listing is None or not isinstance(listing, Mapping):
        listing = {}

    # Resolve purchase
    purchase_key = str(listingid) + "_" + str(purchaseid)
    purchase = purchases.get(purchase_key) if isinstance(purchases, Mapping) else None
    if purchase is None or not isinstance(purchase, Mapping):
        return None

    # Fall back to purchase record for steamid_purchaser (captured pages place it there)
    if not steamid_purchaser:
        steamid_purchaser = purchase.get("steamid_purchaser") or ""
    if not isinstance(steamid_purchaser, str) or not steamid_purchaser.strip():
        return None

    # Resolve asset_id: prefer purchase's asset, fallback to listing's asset
    asset_id = None
    asset_leaf = None
    purchase_asset_amount = None  # Capture purchase.asset.amount as authoritative quantity
    # Try purchase's asset
    if isinstance(purchase, Mapping):
        purchase_asset = purchase.get("asset")
        if isinstance(purchase_asset, Mapping):
            asset_id = purchase_asset.get("assetid") or purchase_asset.get("id")
            asset_leaf = purchase_asset
            # Capture the purchase asset's amount - this is the authoritative item quantity
            purchase_asset_amount = purchase_asset.get("amount")

    # Fallback to listing's asset
    if not asset_id:
        asset_id, asset_leaf = _resolve_listing_asset(listing)

    # Resolve market_hash_name and asset metadata from asset_id
    market_hash_name: Optional[str] = None
    asset_meta: Optional[AssetMetadata] = None
    if asset_id:
        market_hash_name = resolve_market_hash_name(assets, asset_id)
        asset_meta = resolve_asset_metadata(assets, asset_id)

    # Fallback: purchase.asset.id may reference an inventory asset absent from
    # the assets map while the listing asset references the market asset that
    # carries the market_hash_name. Only use listing asset when it differs and
    # resolves deterministically.
    if market_hash_name is None and asset_id:
        _listing_asset_id, _listing_leaf = _resolve_listing_asset(listing) if listing else ("", {})
        if _listing_asset_id and _listing_asset_id != asset_id:
            _mhn = resolve_market_hash_name(assets, _listing_asset_id)
            if _mhn is not None:
                market_hash_name = _mhn
                if asset_meta is None:
                    _meta = resolve_asset_metadata(assets, _listing_asset_id)
                    if _meta is not None:
                        asset_meta = _meta

    # If the asset itself carries flat asset fields (from leaf), merge into meta
    if asset_meta is None and asset_leaf:
        asset_meta = AssetMetadata(
            appid=str(asset_leaf.get("appid", "")),
            contextid=str(asset_leaf.get("contextid", "")),
            assetid=str(asset_leaf.get("assetid") or asset_leaf.get("id") or ""),
            classid=str(asset_leaf.get("classid", "")),
            instanceid=str(asset_leaf.get("instanceid", "")),
            amount=str(asset_leaf.get("amount", "")),
            new_id=str(asset_leaf.get("new_id", "")),
            new_contextid=str(asset_leaf.get("new_contextid", "")),
        )

    # Override asset_meta.amount with purchase.asset.amount if available.
    # The purchase.asset.amount represents the actual item quantity received,
    # while the global assets map may contain the listing asset (amount=0).
    if purchase_asset_amount is not None and asset_meta is not None:
        asset_meta = AssetMetadata(
            appid=asset_meta.appid,
            contextid=asset_meta.contextid,
            assetid=asset_meta.assetid,
            classid=asset_meta.classid,
            instanceid=asset_meta.instanceid,
            amount=str(purchase_asset_amount),
            new_id=asset_meta.new_id,
            new_contextid=asset_meta.new_contextid,
        )

    # Classify
    classification = classify_event(
        event_type_raw=event_type_raw,
        steamid_actor=steamid_actor,
        steamid_purchaser=steamid_purchaser,
        listing=listing,
        purchase=purchase,
        account_steamid=account_steamid,
    )

    # Monetary fields as raw integers (no conversion, no EUR-cent assumption)
    def safe_int(value: Any, default: int = 0) -> int:
        try:
            iv = int(value)
            if iv < 0:
                return default
            return iv
        except (TypeError, ValueError):
            return default

    def safe_str(value: Any) -> str:
        if isinstance(value, str):
            return value
        return ""

    meta_appid = asset_meta.appid if asset_meta else ""
    meta_contextid = asset_meta.contextid if asset_meta else ""
    meta_assetid = asset_meta.assetid if asset_meta else ""
    meta_classid = asset_meta.classid if asset_meta else ""
    meta_instanceid = asset_meta.instanceid if asset_meta else ""
    meta_amount = asset_meta.amount if asset_meta else ""
    meta_new_id = asset_meta.new_id if asset_meta else ""
    meta_new_contextid = asset_meta.new_contextid if asset_meta else ""

    return NormalizedEvent(
        event_type=classification,
        steamid_actor=steamid_actor,
        steamid_purchaser=steamid_purchaser,
        time_event=time_event if isinstance(time_event, str) and time_event.strip() else None,
        time_sold=time_sold if isinstance(time_sold, str) and time_sold.strip() else None,
        listingid=listingid,
        purchaseid=purchaseid,
        market_hash_name=market_hash_name,
        paid_amount=safe_int(purchase.get("paid_amount")),
        paid_fee=safe_int(purchase.get("paid_fee")),
        steam_fee=safe_int(purchase.get("steam_fee")),
        publisher_fee=safe_int(purchase.get("publisher_fee")),
        publisher_fee_percent=purchase.get("publisher_fee_percent"),
        publisher_fee_app=purchase.get("publisher_fee_app"),
        funds_returned=safe_int(purchase.get("funds_returned")),
        received_amount=safe_int(purchase.get("received_amount")),
        currencyid=safe_int(purchase.get("currencyid")),
        received_currencyid=safe_int(purchase.get("received_currencyid")),
        added_tax=safe_int(purchase.get("added_tax")),
        paid_fee_present=("paid_fee" in purchase),
        asset_appid=meta_appid,
        asset_contextid=meta_contextid,
        asset_id=meta_assetid,
        asset_classid=meta_classid,
        asset_instanceid=meta_instanceid,
        asset_amount=meta_amount,
        asset_new_id=meta_new_id,
        asset_new_contextid=meta_new_contextid,
        event_type_raw=event_type_raw if isinstance(event_type_raw, int) else None,
    )


# ---------------------------------------------------------------------------
# Step 6 — bulk adaptation
# ---------------------------------------------------------------------------

def adapt_response(
    data: Mapping[str, Any],
    account_steamid: str,
) -> Tuple[List[NormalizedEvent], List[str]]:
    """Adapt a full Steam Market History JSON response.

    Returns (normalized_events, errors).  Errors describe validation
    or resolution problems but never crash on missing records.
    """
    validate_response(data)

    purchases = data.get("purchases", {})
    listings = data.get("listings", {})
    assets = data.get("assets", {})
    events = data.get("events", [])

    if not isinstance(events, list):
        events = []

    normalized: List[NormalizedEvent] = []
    errors: List[str] = []

    for idx, raw in enumerate(events):
        if not isinstance(raw, Mapping):
            errors.append(f"event[{idx}] is not a mapping; skipping")
            continue

        ne = normalize_event(
            raw=raw,
            purchases=purchases,
            listings=listings,
            assets=assets,
            account_steamid=account_steamid,
        )
        if ne is None:
            errors.append(f"event[{idx}]: could not normalize (insufficient evidence)")
            continue
        normalized.append(ne)

    return normalized, errors


__all__ = [
    "MarketHistoryJSONError",
    "validate_response",
    "AssetMetadata",
    "resolve_asset_metadata",
    "resolve_market_hash_name",
    "NormalizedEvent",
    "normalize_event",
    "classify_event",
    "adapt_response",
]
