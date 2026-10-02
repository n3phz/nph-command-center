# Steam Tradebot - Accounting Semantics

## Core Principle

All monetary values are stored in **minor units** (cents for EUR) as integers to avoid floating-point precision issues. Decimal is used only for display/arithmetic.

## Field Semantics

### Acquisition Side (BUY)

| Field | Meaning | Source | Units |
|-------|---------|--------|-------|
| `paid_amount` | **Price excluding fees** = seller-side amount | Steam Market History `paid_amount` | minor units (cents) |
| `paid_fee` | Total fees charged on top of the price | Steam Market History `paid_fee` | minor units |
| `steam_fee` | Steam platform fee component | Steam Market History `steam_fee` | minor units |
| `publisher_fee` | Publisher/game fee component | Steam Market History `publisher_fee` | minor units |
| `received_amount` | Seller-side amount (same basis as `paid_amount`) | Steam Market History `received_amount` | minor units |

**Relationships:**
- `buyer_total = paid_amount + paid_fee` (what the buyer actually outlays)
- `paid_fee = steam_fee + publisher_fee`
- `paid_amount == received_amount` on Steam (both are the price-excluding-fees basis)

**Evidence for the `paid_amount` semantics** (Rixqor purchase vs current listing, both verified):

| | purchase | current listing | match |
|---|---|---|---|
| price excl. fees | `paid_amount=3` | `unPrice=3` | equal |
| total fees | `paid_fee=2` | `unFee=2` | equal |
| steam / publisher split | `1` / `1` | `unSteamFee=1` / `unPublisherFee=1` | equal |
| buyer-facing total | `3+2=5` (`0,05€` in Market History cell) | `strSubtotal="€0.05"` | equal |

The Market History price cell rendered `0,05€` while `paid_amount=3`, which is
only consistent if `paid_amount` excludes fees and the buyer total is
`paid_amount + paid_fee`. `original_price=3` on the purchase listing record
independently confirms the 3-cent price basis.

### Current Schema Mapping (Pre-Change)

| DB Field | Current Value | Issue |
|----------|---------------|-------|
| `transactions.unit_price` | `seller_received` (€0.03) | Should be buyer-facing |
| `transactions.fees` | Always 0 for BUY | Missing fees |
| `transactions.total_value` | `seller_received * qty` | Should be `paid_amount * qty` |
| `acquisition_lots.unit_cost` | `seller_received / qty` (€0.03) | Should represent all-in cost |
| `acquisition_lots.provenance.evidence_data` | `paid_amount_cents`, `currencyid` | Missing `paid_fee`, `steam_fee`, `publisher_fee` |

### Proposed New Semantics

#### Transaction (BUY)
- `unit_price` = **buyer-facing total** = `paid_amount` / quantity (in minor units)
- `fees` = `paid_fee` (total fees buyer paid)
- `total_value` = `paid_amount` (buyer-facing total)

#### Acquisition Lot
- `unit_cost` = **seller-side amount per unit** = `seller_received` / quantity (preserved as-is for backward compatibility)
- **NEW** `acquisition_fee` = `paid_fee` / quantity (acquisition fees per unit)
- **NEW** `all_in_cost` = `paid_amount` / quantity = `unit_cost + acquisition_fee` (all-in economic cost)

#### Provenance Evidence Data (Extended)
```json
{
  "listingid": "...",
  "purchaseid": "...",
  "paid_amount_cents": 5,
  "paid_fee_cents": 2,
  "steam_fee_cents": 1,
  "publisher_fee_cents": 1,
  "currencyid": 2003,
  "timestamp_iso": "..."
}
```

### Sale Side (SELL)

| Field | Meaning | Source | Units |
|-------|---------|--------|-------|
| `unPrice` | Seller proceeds (what seller receives) | Steam Market listing `unPrice` | minor units |
| `unFee` | Total buyer fees | Steam Market listing `unFee` | minor units |
| `unSteamFee` | Steam platform fee | Steam Market listing `unSteamFee` | minor units |
| `unPublisherFee` | Publisher fee | Steam Market listing `unPublisherFee` | minor units |
| `strSubtotal` | Buyer-facing total (display) | Steam Market listing `strSubtotal` | string (e.g., "€0.05") |
| `eCurrency` | Currency ID | Steam Market listing `eCurrency` | Steam currency ID |

**Relationships:**
- `unPrice + unFee = strSubtotal (in minor units)`
- `unSteamFee + unPublisherFee = unFee`
- `unPrice = seller_proceeds`

### P&L Calculation

For a given quantity:
```
all_in_acquisition_cost = paid_amount (total buyer outlay)
seller_proceeds = unPrice * quantity_sold (seller receives)
total_sale_fees = unFee * quantity_sold
gross_sale_price = strSubtotal (buyer pays)

P&L = seller_proceeds - all_in_acquisition_cost
```

NOT: `seller_proceeds - seller_received` (which would be €0.00 and wrong)

### Economic Cost Basis for Rixqor Item

| Concept | Value |
|---------|-------|
| `seller_received` | 3 cents |
| `paid_fee` | 2 cents |
| `paid_amount` (all-in) | 5 cents |
| `unit_cost` (current, preserved) | 3 cents |
| `acquisition_fee` (new) | 2 cents |
| `all_in_cost` (new) | 5 cents |

### Inventory Valuation

For current positions:
- Use `unPrice` from market listings as `seller_proceeds`
- Use `all_in_cost` from acquisition lot as `acquisition_cost`
- `projected_pnl = seller_proceeds * qty - all_in_cost * qty`
- `projected_roi = projected_pnl / (all_in_cost * qty)`

### Implementation Notes

1. **Preserve backward compatibility**: `unit_cost` remains `seller_received / qty`
2. **Additive fields**: Add `acquisition_fee`, `all_in_cost` columns
4. **Migration**: Backfill from provenance for existing records where possible
5. **Provenance**: Extend evidence_data with full fee breakdown
6. **Parser**: Add support for modern `unPrice`/`unFee`/`strSubtotal` fields
