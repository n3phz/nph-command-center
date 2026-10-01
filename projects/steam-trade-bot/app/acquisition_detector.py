"""Acquisition event detection and reconciliation service.

Cross-references inventory snapshots against Steam Market History to
determine whether inventory increases represent verified acquisitions
(TRACKED) or unverified observations (UNKNOWN).

Architecture:
  Inventory Snapshot Polling
        ↓
  Delta Detection (compare snapshots)
        ↓
  Market History Enrichment (query Steam)
        ↓
  Acquisition Recording (TRACKED or UNKNOWN)

Phase 1 invariants preserved:
  - TRACKED requires provenance
  - UNKNOWN has unit_cost=None
  - No cost fabrication
  - Idempotent via source_key
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, Sequence

from acquisition import record_acquisition, RecordedAcquisition, AcquisitionError, Repository, _serialize_provenance
from transactions import CostStatus, SourceType, Provenance, EvidenceType


class AcquisitionDetectionError(ValueError):
    """Raised when acquisition detection cannot proceed safely."""


@dataclass(frozen=True)
class InventorySnapshot:
    """Immutable snapshot of inventory state at a point in time."""

    snapshot_id: int
    bot_name: str
    captured_at: str
    items: dict[str, int]  # market_hash_name -> quantity


@dataclass(frozen=True)
class InventoryDelta:
    """Difference between two inventory snapshots."""

    bot_name: str
    market_hash_name: str
    quantity_change: int  # positive = increase, negative = decrease
    previous_quantity: int
    current_quantity: int
    detected_at: date


@dataclass(frozen=True)
class MarketHistoryPurchase:
    """Normalized Market History purchase event with verified cost."""

    listingid: str
    purchaseid: str
    market_hash_name: str
    quantity: int
    paid_amount_cents: int
    currencyid: int
    time_event_unix: int
    external_ref: str  # "listingid:purchaseid"


@dataclass(frozen=True)
class AcquisitionResult:
    """Result of an acquisition detection attempt."""

    bot_name: str
    market_hash_name: str
    quantity: int
    cost_status: CostStatus
    source_type: Optional[SourceType]
    provenance: Optional[Provenance]
    created: bool  # True if new lot created, False if idempotent resolve
    lot_id: Optional[str]
    transaction_id: Optional[str]
    error: Optional[str] = None


class AcquisitionDetector:
    """Detects acquisitions by cross-referencing inventory with Market History.

    The detector maintains state about which snapshots have been processed
    to avoid duplicate detection on repeated polling.
    """

    # Time window for Market History matching (hours)
    # Purchases within ±24 hours of inventory observation are candidates
    MATCHING_TIME_WINDOW_HOURS = 24

    # Currency ID to ISO code mapping (Steam-specific)
    CURRENCY_MAP = {
        1: "USD",
        2: "GBP",
        3: "EUR",
        5: "CHF",
        8: "AUD",
        9: "BRL",
        10: "JPY",
        11: "KRW",
        12: "NOK",
        13: "IDR",
        14: "MYR",
        16: "PHP",
        17: "RUB",
        18: "SGD",
        19: "THB",
        20: "TWD",
        22: "ZAR",
        24: "CAD",
        25: "MXN",
        26: "VND",
        27: "PLN",
        28: "CZK",
        29: "HUF",
        30: "CLP",
        31: "PEN",
        32: "ARS",
        34: "INR",
        35: "TRY",
        36: "AED",
        37: "RON",
        38: "BGN",
        39: "HRK",
        40: "DKK",
        41: "ISK",
        42: "NZD",
        43: "UAH",
        44: "QAR",
        45: "EGP",
        46: "ILS",
        47: "KWD",
        48: "BHD",
        49: "OMR",
        50: "JOD",
    }

    def __init__(
        self,
        repository: Repository,
        bot_name: str,
        account_steamid: str = "",
    ):
        """Initialize detector for a specific bot.

        Args:
            repository: Database repository with inventory snapshot access.
            bot_name: Bot name to detect acquisitions for.
            account_steamid: SteamID64 of the account that owns ``bot_name``.
                Required for the Market History classifier to attribute a BUY.
                Left empty, events classify as UNKNOWN and acquisitions stay
                UNKNOWN, which is the safe fallback.
        """
        self.repository = repository
        self.bot_name = bot_name
        self.account_steamid = (account_steamid or "").strip()
        self._processed_snapshot_ids: set[int] = set()

    def load_processed_snapshots(self) -> set[int]:
        """Load already-processed snapshot IDs from database.

        Returns:
            Set of snapshot IDs that have already been analyzed.
        """
        try:
            conn = self.repository.connection
            rows = conn.execute(
                """
                SELECT DISTINCT snapshot_id
                FROM acquisition_processing_log
                WHERE bot_name = ?
                """,
                (self.bot_name,),
            ).fetchall()
            return {row[0] for row in rows}
        except Exception:
            # Table may not exist yet — return empty set
            return set()

    def get_latest_snapshot(self) -> Optional[InventorySnapshot]:
        """Get the most recent inventory snapshot for this bot.

        Returns:
            InventorySnapshot if exists, None otherwise.
        """
        conn = self.repository.connection
        row = conn.execute(
            """
            SELECT id, captured_at, item_count
            FROM inventory_snapshots
            WHERE bot_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (self.bot_name,),
        ).fetchone()

        if row is None:
            return None

        snapshot_id, captured_at, _ = row

        # Load items for this snapshot
        items_rows = conn.execute(
            """
            SELECT market_hash_name, SUM(amount) as total_amount
            FROM inventory_items
            WHERE snapshot_id = ?
            GROUP BY market_hash_name
            """,
            (snapshot_id,),
        ).fetchall()

        items = {row[0]: int(row[1]) for row in items_rows}

        return InventorySnapshot(
            snapshot_id=snapshot_id,
            bot_name=self.bot_name,
            captured_at=captured_at,
            items=items,
        )

    def get_previous_snapshot(self, current_snapshot: InventorySnapshot) -> Optional[InventorySnapshot]:
        """Get the snapshot immediately preceding the current one.

        Args:
            current_snapshot: The current snapshot to find predecessor for.

        Returns:
            Previous InventorySnapshot or None if this is the first.
        """
        conn = self.repository.connection
        row = conn.execute(
            """
            SELECT id, captured_at, item_count
            FROM inventory_snapshots
            WHERE bot_name = ? AND id < ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (self.bot_name, current_snapshot.snapshot_id),
        ).fetchone()

        if row is None:
            return None

        snapshot_id, captured_at, _ = row

        items_rows = conn.execute(
            """
            SELECT market_hash_name, SUM(amount) as total_amount
            FROM inventory_items
            WHERE snapshot_id = ?
            GROUP BY market_hash_name
            """,
            (snapshot_id,),
        ).fetchall()

        items = {row[0]: int(row[1]) for row in items_rows}

        return InventorySnapshot(
            snapshot_id=snapshot_id,
            bot_name=self.bot_name,
            captured_at=captured_at,
            items=items,
        )

    def calculate_deltas(self, previous: Optional[InventorySnapshot], current: InventorySnapshot) -> list[InventoryDelta]:
        """Calculate inventory deltas between two snapshots.

        Args:
            previous: Previous snapshot (None for first observation).
            current: Current snapshot.

        Returns:
            List of InventoryDelta objects for positive changes (acquisitions).
        """
        if previous is None:
            # First snapshot — establish baseline, do NOT create acquisition candidates.
            # No previous inventory to compare against, so no delta can be computed.
            return []

        deltas = []
        all_items = set(previous.items.keys()) | set(current.items.keys())

        for mhn in all_items:
            prev_qty = previous.items.get(mhn, 0)
            curr_qty = current.items.get(mhn, 0)
            change = curr_qty - prev_qty

            if change > 0:
                deltas.append(InventoryDelta(
                    bot_name=current.bot_name,
                    market_hash_name=mhn,
                    quantity_change=change,
                    previous_quantity=prev_qty,
                    current_quantity=curr_qty,
                    detected_at=self._parse_date(current.captured_at),
                ))

        return deltas

    def _parse_date(self, iso_string: str) -> date:
        """Parse ISO date string to date object."""
        try:
            dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
            return dt.date()
        except (ValueError, AttributeError):
            return date.today()

    def fetch_market_history_for_item(
        self,
        market_hash_name: str,
        detected_at: date,
        session,
    ) -> list[MarketHistoryPurchase]:
        """Fetch Market History purchases matching an item around detection time.

        Args:
            market_hash_name: Item to search for.
            detected_at: Date of inventory observation.
            session: Authenticated requests session for Steam API.

        Returns:
            List of MarketHistoryPurchase objects within time window.
        """
        # Calculate time window
        start_date = detected_at - timedelta(days=7)  # Look back 7 days
        end_date = detected_at + timedelta(hours=1)  # Allow 1 hour forward

        # Fetch Market History pages until we find matches or exhaust
        all_purchases = []
        start = 0
        count = 100

        while start < 500:  # Safety limit
            try:
                raw_data = session.get(
                    f"https://steamcommunity.com/market/myhistory/render/",
                    params={"start": start, "count": count, "norender": 1},
                    timeout=30,
                ).json()

                if not raw_data.get("success"):
                    break

                # Parse events using existing parser.
                # The account SteamID must be the real owner: the BUY
                # classifier requires actor == purchaser == account_steamid
                # and refuses to classify when it is empty, which would
                # silently drop every genuine purchase back to UNKNOWN.
                from steam_market_history_json import adapt_response
                normalized_events, errors = adapt_response(
                    raw_data,
                    account_steamid=self.account_steamid,
                )

                for event in normalized_events:
                    if event.event_type != "BUY":
                        continue
                    if event.market_hash_name != market_hash_name:
                        continue
                    if event.time_event is None:
                        continue

                    try:
                        event_date = datetime.fromisoformat(event.time_event).date()
                    except (ValueError, AttributeError):
                        continue

                    if start_date <= event_date <= end_date:
                        # Convert paid_amount from cents to Decimal
                        paid_decimal = Decimal(event.paid_amount) / Decimal(100)

                        all_purchases.append(MarketHistoryPurchase(
                            listingid=event.listingid,
                            purchaseid=event.purchaseid,
                            market_hash_name=event.market_hash_name,
                            quantity=int(event.asset_amount) if event.asset_amount else 1,
                            paid_amount_cents=event.paid_amount,
                            currencyid=event.currencyid,
                            time_event_unix=self._iso_to_unix(event.time_event),
                            external_ref=f"{event.listingid}:{event.purchaseid}",
                        ))

                # Check if we've fetched all available history
                total_count = raw_data.get("total_count", 0)
                if start + count >= total_count:
                    break
                start += count

            except Exception:
                break

        return all_purchases

    def _iso_to_unix(self, iso_string: str) -> int:
        """Convert ISO timestamp to Unix timestamp."""
        try:
            dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except (ValueError, AttributeError):
            return 0

    def find_matching_purchase(
        self,
        delta: InventoryDelta,
        purchases: list[MarketHistoryPurchase],
    ) -> Optional[MarketHistoryPurchase]:
        """Find the best matching purchase for an inventory delta.

        Matching criteria:
        1. Same market_hash_name (already filtered)
        2. EXACT quantity match (purchase qty == delta qty)
        3. Within time window (already filtered)
        4. Unique match (no ambiguity)

        Args:
            delta: Inventory change to match.
            purchases: Candidate purchases from Market History.

        Returns:
            Best matching purchase or None if ambiguous/unmatched.
        """
        # Filter to purchases with EXACT quantity match
        candidates = [
            p for p in purchases
            if p.market_hash_name == delta.market_hash_name
            and p.quantity == delta.quantity_change
        ]

        if len(candidates) == 0:
            return None

        if len(candidates) == 1:
            return candidates[0]

        # Multiple exact quantity matches — ambiguous
        return None

    def detect_acquisition(
        self,
        session,
        process_new_snapshots: bool = True,
    ) -> list[AcquisitionResult]:
        """Main detection workflow.

        1. Get current and previous snapshots
        2. Calculate deltas
        3. For each positive delta, query Market History
        4. Match purchase if found
        5. Record TRACKED or UNKNOWN lot atomically with processed marker

        Args:
            session: Authenticated Steam session.
            process_new_snapshots: If True, only process unprocessed snapshots.

        Returns:
            List of AcquisitionResult objects.
        """
        results = []

        # Load already-processed snapshots
        self._processed_snapshot_ids = self.load_processed_snapshots()

        # Get latest snapshot
        current = self.get_latest_snapshot()
        if current is None:
            return results

        # Check if already processed
        if process_new_snapshots and current.snapshot_id in self._processed_snapshot_ids:
            return results

        # Get previous snapshot
        previous = self.get_previous_snapshot(current)

        # Calculate deltas
        deltas = self.calculate_deltas(previous, current)

        # Filter to only positive deltas
        positive_deltas = [d for d in deltas if d.quantity_change > 0]
        if not positive_deltas:
            # No acquisitions to record, but mark snapshot as processed.
            # Must run inside its own BEGIN/COMMIT transaction because
            # _mark_snapshot_processed_atomic() does NOT commit — it relies
            # on the caller owning an active transaction. Without a commit
            # here, the INSERT into acquisition_processing_log stays in an
            # open SQLite write transaction, which blocks the next bot's
            # database write with "database is locked".
            if process_new_snapshots:
                self._mark_snapshot_processed_committed(current.snapshot_id)
            return results

        # Process each positive delta within a single transaction
        # that includes both acquisition persistence and processed marker
        conn = self.repository.connection
        try:
            conn.execute("BEGIN")

            for delta in positive_deltas:
                result = self._process_delta(delta, session)
                results.append(result)

            # Mark snapshot as processed within the same transaction
            if process_new_snapshots:
                self._mark_snapshot_processed_atomic(current.snapshot_id, [])

            conn.commit()

        except Exception:
            conn.rollback()
            # Re-raise to surface the error
            raise

        return results

    def _process_delta(
        self,
        delta: InventoryDelta,
        session,
    ) -> AcquisitionResult:
        """Process a single inventory delta.

        Args:
            delta: Inventory change to process.
            session: Authenticated Steam session.

        Returns:
            AcquisitionResult indicating outcome.

        Raises:
            Exception: Unexpected errors (Market History API failures, etc.)
                are re-raised to trigger transaction rollback.
        """
        # Fetch Market History for this item
        purchases = self.fetch_market_history_for_item(
            delta.market_hash_name,
            delta.detected_at,
            session,
        )

        # Find matching purchase
        matching_purchase = self.find_matching_purchase(delta, purchases)

        if matching_purchase is not None:
            # Verified acquisition — create TRACKED lot
            return self._record_tracked(delta, matching_purchase)
        else:
            # No verified evidence — create UNKNOWN lot
            return self._record_unknown(delta)

    def _record_tracked(
        self,
        delta: InventoryDelta,
        purchase: MarketHistoryPurchase,
    ) -> AcquisitionResult:
        """Record a verified TRACKED acquisition.

        Args:
            delta: Inventory change observed.
            purchase: Matching Market History purchase.

        Returns:
            AcquisitionResult with TRACKED status.

        Note on paid_amount interpretation:
        Steam Market History 'paid_amount' for BUY events represents the
        TOTAL amount the buyer paid (including Steam fees + publisher fees).
        This is the correct acquisition cost.
        
        For a BUY event:
          paid_amount = buyer's total spend (what we paid)
          received_amount = seller's net (after fees)
          steam_fee + publisher_fee = fees taken by Steam/publisher
          paid_amount = received_amount + steam_fee + publisher_fee
        
        Since we are the buyer, paid_amount is our acquisition cost.
        No fee subtraction is needed or correct.
        """
        # Convert cents to Decimal, divided by quantity for unit cost
        # paid_amount_cents is TOTAL cents paid for the entire purchase
        # (includes all fees - this is the buyer's actual cost)
        unit_cost = Decimal(purchase.paid_amount_cents) / Decimal(100) / Decimal(purchase.quantity)

        # Get currency code
        currency = self.CURRENCY_MAP.get(purchase.currencyid, "EUR")

        # Create provenance
        provenance = Provenance(
            evidence_type=EvidenceType.STEAM_MARKET_HISTORY,
            evidence_id=purchase.purchaseid,
            evidence_data={
                "listingid": purchase.listingid,
                "paid_amount_cents": purchase.paid_amount_cents,
                "currencyid": purchase.currencyid,
                "timestamp_iso": datetime.fromtimestamp(
                    purchase.time_event_unix, tz=timezone.utc
                ).isoformat(),
            },
        )

        # Record through canonical Phase 1 path
        result = record_acquisition(
            repository=self.repository,
            bot_name=delta.bot_name,
            market_hash_name=delta.market_hash_name,
            quantity=delta.quantity_change,
            acquired_at=self._unix_to_date(purchase.time_event_unix),
            unit_cost=unit_cost,
            currency=currency,
            source_type=SourceType.STEAM_MARKET_PURCHASE,
            provenance=provenance,
            external_reference=purchase.external_ref,
            entered_at=datetime.now(timezone.utc).isoformat(),
        )

        return AcquisitionResult(
            bot_name=delta.bot_name,
            market_hash_name=delta.market_hash_name,
            quantity=delta.quantity_change,
            cost_status=result.lot.cost_status,
            source_type=result.lot.source_type,
            provenance=result.lot.provenance,
            created=result.created,
            lot_id=result.lot.lot_id,
            transaction_id=result.transaction.transaction_id if result.transaction else None,
        )

    def _record_unknown(
        self,
        delta: InventoryDelta,
    ) -> AcquisitionResult:
        """Record an UNKNOWN acquisition (no verified evidence).

        Args:
            delta: Inventory change observed.

        Returns:
            AcquisitionResult with UNKNOWN status.
        """
        # For UNKNOWN, we need a unique external_reference for idempotency.
        # Use bot_name + market_hash_name + detected_at + quantity as a key.
        external_ref = f"unknown:{delta.bot_name}:{delta.market_hash_name}:{delta.detected_at}:{delta.quantity_change}"
        try:
            result = record_acquisition(
                repository=self.repository,
                bot_name=delta.bot_name,
                market_hash_name=delta.market_hash_name,
                quantity=delta.quantity_change,
                acquired_at=delta.detected_at,
                unit_cost=None,  # UNKNOWN
                currency=None,
                source_type=None,
                provenance=None,
                external_reference=external_ref,
                entered_at=datetime.now(timezone.utc).isoformat(),
            )

            return AcquisitionResult(
                bot_name=delta.bot_name,
                market_hash_name=delta.market_hash_name,
                quantity=delta.quantity_change,
                cost_status=result.lot.cost_status,
                source_type=result.lot.source_type,
                provenance=result.lot.provenance,
                created=result.created,
                lot_id=result.lot.lot_id,
                transaction_id=result.transaction.transaction_id if result.transaction else None,
            )

        except AcquisitionError as exc:
            return AcquisitionResult(
                bot_name=delta.bot_name,
                market_hash_name=delta.market_hash_name,
                quantity=delta.quantity_change,
                cost_status=CostStatus.UNKNOWN,
                source_type=None,
                provenance=None,
                created=False,
                lot_id=None,
                transaction_id=None,
                error=str(exc),
            )

    def _unix_to_date(self, unix_timestamp: int) -> date:
        """Convert Unix timestamp to date."""
        try:
            return datetime.fromtimestamp(unix_timestamp, tz=timezone.utc).date()
        except (OSError, ValueError, OverflowError):
            return date.today()

    def _mark_snapshot_processed_atomic(self, snapshot_id: int, _unused=None) -> None:
        """Mark a snapshot as processed within the caller's transaction.

        Creates the processing log table if it doesn't exist.
        Does NOT commit or rollback — caller manages the transaction.

        This method is intended for use inside an explicit BEGIN/COMMIT
        block where the caller owns the transaction lifecycle. It performs
        no commit so that the caller can include additional writes (e.g.
        acquisition persistence) in the same atomic transaction.
        """
        conn = self.repository.connection
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS acquisition_processing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                snapshot_id INTEGER NOT NULL,
                processed_at TEXT NOT NULL,
                UNIQUE(bot_name, snapshot_id)
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO acquisition_processing_log
                (bot_name, snapshot_id, processed_at)
            VALUES (?, ?, ?)
            """,
            (self.bot_name, snapshot_id, datetime.now(timezone.utc).isoformat()),
        )
        # NO commit — caller manages transaction

    def _mark_snapshot_processed_committed(self, snapshot_id: int) -> None:
        """Mark a snapshot as processed and commit immediately.

        Opens its own BEGIN/COMMIT transaction so that the processing
        marker is persisted atomically and the SQLite connection is
        released before the next database write. This is the correct
        entry point for the zero-positive-delta path where there is no
        surrounding acquisition-persistence transaction.

        Raises:
            Exception: Re-rolled-back and re-raised if the write fails.
        """
        conn = self.repository.connection
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS acquisition_processing_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_name TEXT NOT NULL,
                    snapshot_id INTEGER NOT NULL,
                    processed_at TEXT NOT NULL,
                    UNIQUE(bot_name, snapshot_id)
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO acquisition_processing_log
                    (bot_name, snapshot_id, processed_at)
                VALUES (?, ?, ?)
                """,
                (self.bot_name, snapshot_id, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def reconcile_delayed_evidence(
        self,
        session,
        lookback_days: int = 30,
    ) -> list[AcquisitionResult]:
        """Reconcile existing UNKNOWN lots with later-found evidence.

        For each UNKNOWN lot that now has matching Market History evidence,
        UPDATE the existing lot to TRACKED status with provenance populated.
        This avoids creating duplicate economic positions.

        Args:
            session: Authenticated Steam session.
            lookback_days: How far back to look for evidence.

        Returns:
            List of AcquisitionResult objects for reconciled lots.
        """
        results = []

        # Without a session there is nothing to enrich with. Exiting early
        # keeps the anonymous case cheap and leaves every lot UNKNOWN.
        if session is None:
            return results

        # Find UNKNOWN lots without provenance
        conn = self.repository.connection
        unknown_lots = conn.execute(
            """
            SELECT al.id, al.source_transaction_id, al.market_hash_name,
                   al.original_quantity, al.acquired_at, al.external_ref
            FROM acquisition_lots al
            WHERE al.cost_status = 'UNKNOWN'
              AND (al.external_ref IS NULL OR al.external_ref LIKE 'unknown:%')
              AND al.bot_name = ?
            ORDER BY al.acquired_at DESC
            LIMIT 100
            """,
            (self.bot_name,),
        ).fetchall()

        for lot_row in unknown_lots:
            lot_id, source_tx_id, mhn, qty, acquired_at, _ = lot_row

            try:
                acquired_date = self._parse_date(acquired_at)
                purchases = self.fetch_market_history_for_item(
                    mhn,
                    acquired_date,
                    session,
                )

                if not purchases:
                    # No evidence for this lot yet — stays UNKNOWN.
                    continue

                # Create synthetic delta for matching
                delta = InventoryDelta(
                    bot_name=self.bot_name,
                    market_hash_name=mhn,
                    quantity_change=qty,
                    previous_quantity=0,
                    current_quantity=qty,
                    detected_at=acquired_date,
                )

                matching = self.find_matching_purchase(delta, purchases)
                if matching is None:
                    # Absent or ambiguous evidence — never guess, stays UNKNOWN.
                    continue

                # Update the existing UNKNOWN lot to TRACKED. The lot row and
                # its source transaction are written in ONE explicit
                # transaction so a partial write can never be persisted, and
                # the write lock is released before the next bot reads or
                # writes (the 63a84b6 regression).
                conn.execute("BEGIN")
                try:
                    result = self._update_tracked(
                        lot_id, source_tx_id, delta, matching
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

                results.append(result)

            except Exception:
                # Skip lots we can't process; the lot remains UNKNOWN.
                continue

        return results

    def _update_tracked(
        self,
        lot_id: int,
        source_tx_id: int,
        delta: InventoryDelta,
        purchase: MarketHistoryPurchase,
    ) -> AcquisitionResult:
        """Update an existing UNKNOWN lot to TRACKED status.

        This preserves the original lot record while adding provenance
        and cost basis from the matched Market History purchase.

        Args:
            lot_id: ID of the UNKNOWN lot to update.
            source_tx_id: Source transaction ID.
            delta: Inventory delta for context.
            purchase: Matching Market History purchase.

        Returns:
            AcquisitionResult with updated TRACKED status.
        """
        # Convert cents to Decimal, divided by quantity for unit cost
        unit_cost = Decimal(purchase.paid_amount_cents) / Decimal(100) / Decimal(purchase.quantity)

        # Get currency code
        currency = self.CURRENCY_MAP.get(purchase.currencyid, "EUR")

        # Create provenance
        provenance = Provenance(
            evidence_type=EvidenceType.STEAM_MARKET_HISTORY,
            evidence_id=purchase.purchaseid,
            evidence_data={
                "listingid": purchase.listingid,
                "paid_amount_cents": purchase.paid_amount_cents,
                "currencyid": purchase.currencyid,
                "timestamp_iso": datetime.fromtimestamp(
                    purchase.time_event_unix, tz=timezone.utc
                ).isoformat(),
            },
        )

        # Update the existing lot
        conn = self.repository.connection
        conn.execute(
            """
            UPDATE acquisition_lots
            SET cost_status = 'TRACKED',
                unit_cost = ?,
                source_type = ?,
                external_ref = ?,
                provenance = ?
            WHERE id = ?
            """,
            (
                str(unit_cost),
                SourceType.STEAM_MARKET_PURCHASE.value,
                purchase.external_ref,
                _serialize_provenance(provenance),
                lot_id,
            ),
        )

        # Also update the source transaction with cost info
        conn.execute(
            """
            UPDATE transactions
            SET unit_price = ?,
                fees = ?,
                total_value = ?,
                timestamp = ?
            WHERE id = ?
            """,
            (
                str(unit_cost),
                "0",
                str(unit_cost * delta.quantity_change),
                datetime.fromtimestamp(
                    purchase.time_event_unix, tz=timezone.utc
                ).isoformat(),
                source_tx_id,
            ),
        )

        return AcquisitionResult(
            bot_name=delta.bot_name,
            market_hash_name=delta.market_hash_name,
            quantity=delta.quantity_change,
            cost_status=CostStatus.TRACKED,
            source_type=SourceType.STEAM_MARKET_PURCHASE,
            provenance=provenance,
            created=False,  # Updated existing, not new
            lot_id=lot_id,
            transaction_id=source_tx_id,
        )


__all__ = [
    "AcquisitionDetector",
    "AcquisitionDetectionError",
    "AcquisitionResult",
    "InventorySnapshot",
    "InventoryDelta",
    "MarketHistoryPurchase",
]
