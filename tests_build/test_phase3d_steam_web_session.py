#!/usr/bin/env python3
"""Phase 3D tests for the authenticated Steam Market History session layer.

Covers the security contract required by Phase 3:

- secret is loaded from a runtime file, not from code/env/Git
- authenticated request construction attaches cookies for the right domains
- missing / unreadable / malformed secret degrades safely (no exception)
- absent secret leaves the session anonymous so UNKNOWN remains reachable
- no secret material appears in logs, statuses, or exception messages
- normalization / matching / UNKNOWN fallback semantics are unchanged
- existing fixture-backed acquisition behaviour still holds
"""

import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import requests

from steam_web_session import (
    DEFAULT_SESSION_FILE,
    REQUIRED_COOKIE,
    SESSION_FILE_ENV,
    SteamWebSessionError,
    apply_steam_web_session,
    read_session_cookie_pairs,
    steam_web_session_authenticated,
)

from acquisition import Repository, record_acquisition
from acquisition_detector import (
    AcquisitionDetector,
    InventoryDelta,
    MarketHistoryPurchase,
)
from transactions import CostStatus, EvidenceType, Provenance, SourceType

SECRET_VALUE = "SUPERSECRETCOOKIEVALUE0123456789ABCDEF"


def _write_secret(body: str) -> str:
    fd, path = tempfile.mkstemp(prefix="steam_session_", suffix=".secret")
    os.write(fd, body.encode("utf-8"))
    os.close(fd)
    return path


class TestSecretLoading:
    def test_reads_single_cookie_line(self):
        path = _write_secret(f"{REQUIRED_COOKIE}={SECRET_VALUE}\n")
        try:
            pairs = read_session_cookie_pairs(path)
        finally:
            os.unlink(path)
        assert pairs == [(REQUIRED_COOKIE, SECRET_VALUE)]

    def test_reads_multiple_cookie_lines(self):
        path = _write_secret(
            f"{REQUIRED_COOKIE}={SECRET_VALUE}\nsessionid=sid-123\n"
            "steamMachineAuth=ma-456\n"
        )
        try:
            pairs = dict(read_session_cookie_pairs(path))
        finally:
            os.unlink(path)
        assert pairs[REQUIRED_COOKIE] == SECRET_VALUE
        assert pairs["sessionid"] == "sid-123"
        assert pairs["steamMachineAuth"] == "ma-456"

    def test_reads_cookie_header_blob(self):
        path = _write_secret(f"{REQUIRED_COOKIE}={SECRET_VALUE}; sessionid=sid-9")
        try:
            pairs = dict(read_session_cookie_pairs(path))
        finally:
            os.unlink(path)
        assert pairs[REQUIRED_COOKIE] == SECRET_VALUE
        assert pairs["sessionid"] == "sid-9"

    def test_ignores_comments_and_blank_lines(self):
        path = _write_secret(f"# comment\n\n  \n{REQUIRED_COOKIE}={SECRET_VALUE}\n")
        try:
            pairs = read_session_cookie_pairs(path)
        finally:
            os.unlink(path)
        assert pairs == [(REQUIRED_COOKIE, SECRET_VALUE)]

    def test_missing_file_returns_empty(self):
        assert read_session_cookie_pairs("/nonexistent/steam_session") == []

    def test_empty_file_returns_empty(self):
        path = _write_secret("   \n\n")
        try:
            assert read_session_cookie_pairs(path) == []
        finally:
            os.unlink(path)

    def test_default_path_is_secret_style(self):
        assert DEFAULT_SESSION_FILE == "/run/secrets/steam_market_session"
        assert SESSION_FILE_ENV == "STEAM_MARKET_SESSION_FILE"


class TestApplySession:
    def test_applies_cookies_to_steamcommunity_domains(self):
        path = _write_secret(f"{REQUIRED_COOKIE}={SECRET_VALUE}\nsessionid=sid-1\n")
        session = requests.Session()
        try:
            status = apply_steam_web_session(session, path)
            jar = session.cookies.get_dict()
        finally:
            os.unlink(path)

        assert status.authenticated is True
        assert status.missing_required_cookie is False
        assert set(status.applied_cookie_names) == {REQUIRED_COOKIE, "sessionid"}
        assert jar[REQUIRED_COOKIE] == SECRET_VALUE
        assert steam_web_session_authenticated(session) is True

    def test_missing_secret_leaves_session_anonymous(self):
        session = requests.Session()
        status = apply_steam_web_session(session, "/nonexistent/steam_session")

        assert status.authenticated is False
        assert session.cookies.get_dict() == {}
        assert steam_web_session_authenticated(session) is False

    def test_secret_without_required_cookie_is_not_authenticated(self):
        path = _write_secret("sessionid=sid-only\n")
        session = requests.Session()
        try:
            status = apply_steam_web_session(session, path)
        finally:
            os.unlink(path)

        assert status.authenticated is False
        assert status.missing_required_cookie is True

    def test_unreadable_secret_does_not_raise(self):
        session = requests.Session()
        # A directory is not a readable secret file: must not raise.
        with tempfile.TemporaryDirectory() as tmp:
            status = apply_steam_web_session(session, tmp)
        assert status.authenticated is False
        assert session.cookies.get_dict() == {}

    def test_error_message_never_contains_secret(self):
        secret_path = _write_secret(f"{REQUIRED_COOKIE}={SECRET_VALUE}\n")
        os.chmod(secret_path, 0o000)
        try:
            try:
                read_session_cookie_pairs(secret_path)
            except SteamWebSessionError as exc:
                assert SECRET_VALUE not in str(exc)
            except OSError:
                pass  # running as root can bypass mode bits
        finally:
            os.chmod(secret_path, 0o600)
            os.unlink(secret_path)


class TestNoSecretLeakage:
    def test_log_message_contains_names_not_values(self):
        path = _write_secret(f"{REQUIRED_COOKIE}={SECRET_VALUE}\n")
        session = requests.Session()
        try:
            status = apply_steam_web_session(session, path)
            message = status.as_log_message()
        finally:
            os.unlink(path)

        assert REQUIRED_COOKIE in message
        assert SECRET_VALUE not in message

    def test_status_repr_does_not_leak(self):
        path = _write_secret(f"{REQUIRED_COOKIE}={SECRET_VALUE}\n")
        session = requests.Session()
        try:
            status = apply_steam_web_session(session, path)
        finally:
            os.unlink(path)

        assert SECRET_VALUE not in repr(status)
        assert SECRET_VALUE not in str(status)

    def test_module_source_contains_no_hardcoded_secret(self):
        here = os.path.dirname(os.path.abspath(__file__))
        source_path = os.path.join(here, "..", "app", "steam_web_session.py")
        with open(source_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        assert SECRET_VALUE not in source
        # No production secret material is embedded; only names/constants.
        assert "steamLoginSecure" in source


class TestSemanticsUnchanged:
    """Existing acquisition semantics must be untouched by the auth layer."""

    def _schema(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                market_hash_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price TEXT NOT NULL,
                fees TEXT NOT NULL DEFAULT '0',
                total_value TEXT NOT NULL DEFAULT '0',
                timestamp TEXT NOT NULL,
                bot_name TEXT NOT NULL,
                external_ref TEXT
            );
            CREATE TABLE acquisition_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_transaction_id INTEGER NOT NULL,
                market_hash_name TEXT NOT NULL,
                bot_name TEXT NOT NULL,
                original_quantity INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                unit_cost TEXT,
                acquired_at TEXT NOT NULL,
                cost_status TEXT NOT NULL,
                provenance TEXT,
                source_type TEXT,
                external_ref TEXT
            );
            """
        )
        conn.commit()
        return conn

    def test_tracked_requires_provenance_and_is_persisted(self):
        conn = self._schema()
        try:
            repo = Repository(conn)
            provenance = Provenance(
                evidence_type=EvidenceType.STEAM_MARKET_HISTORY,
                evidence_id="purchaseid-abc",
                evidence_data={"listingid": "L1", "paid_amount_cents": 7},
            )
            record = record_acquisition(
                repository=repo,
                bot_name="Rixqor",
                market_hash_name="774361-Our Lady of the Charred Visage",
                quantity=1,
                acquired_at=date(2026, 10, 1),
                unit_cost=Decimal("0.07"),
                currency="EUR",
                source_type=SourceType.STEAM_MARKET_PURCHASE,
                provenance=provenance,
                external_reference="L1:P1",
                entered_at="2026-10-01T08:00:00+00:00",
            )
            conn.commit()

            assert record.lot.cost_status is CostStatus.TRACKED
            assert record.lot.unit_cost == Decimal("0.07")
            assert record.lot.provenance is not None
            assert record.lot.provenance.evidence_id == "purchaseid-abc"
            assert record.lot.provenance.evidence_type is EvidenceType.STEAM_MARKET_HISTORY
            assert record.lot.source_type is SourceType.STEAM_MARKET_PURCHASE
        finally:
            conn.close()

    def test_unknown_lot_still_has_no_cost_and_no_provenance(self):
        conn = self._schema()
        try:
            repo = Repository(conn)
            record = record_acquisition(
                repository=repo,
                bot_name="Rixqor",
                market_hash_name="Some Card (Trading Card)",
                quantity=1,
                acquired_at=date(2026, 10, 1),
                unit_cost=None,
                currency=None,
                source_type=None,
                provenance=None,
                external_reference="unknown:Rixqor:Some Card (Trading Card):2026-10-01:1",
                entered_at="2026-10-01T08:00:00+00:00",
            )
            conn.commit()

            assert record.lot.cost_status is CostStatus.UNKNOWN
            assert record.lot.unit_cost is None
            assert record.lot.provenance is None
            assert record.lot.source_type is None
        finally:
            conn.close()

    def test_exact_quantity_match_required(self):
        conn = self._schema()
        try:
            detector = AcquisitionDetector(Repository(conn), "Rixqor")
            delta = InventoryDelta(
                bot_name="Rixqor",
                market_hash_name="Some Card (Trading Card)",
                quantity_change=1,
                previous_quantity=0,
                current_quantity=1,
                detected_at=date(2026, 10, 1),
            )

            exact = MarketHistoryPurchase(
                listingid="L1",
                purchaseid="P1",
                market_hash_name="Some Card (Trading Card)",
                quantity=1,
                paid_amount_cents=7,
                currencyid=3,
                time_event_unix=int(
                    datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc).timestamp()
                ),
                external_ref="L1:P1",
            )
            mismatch = MarketHistoryPurchase(
                listingid="L2",
                purchaseid="P2",
                market_hash_name="Some Card (Trading Card)",
                quantity=2,
                paid_amount_cents=14,
                currencyid=3,
                time_event_unix=exact.time_event_unix,
                external_ref="L2:P2",
            )

            assert detector.find_matching_purchase(delta, [exact]) is exact
            assert detector.find_matching_purchase(delta, [mismatch]) is None
            assert detector.find_matching_purchase(delta, []) is None
            # Ambiguity resolves to UNKNOWN, never a guess.
            twin = MarketHistoryPurchase(
                listingid="L3",
                purchaseid="P3",
                market_hash_name="Some Card (Trading Card)",
                quantity=1,
                paid_amount_cents=9,
                currencyid=3,
                time_event_unix=exact.time_event_unix,
                external_ref="L3:P3",
            )
            assert detector.find_matching_purchase(delta, [exact, twin]) is None
        finally:
            conn.close()

    def test_idempotent_reprocess_creates_no_duplicate(self):
        conn = self._schema()
        try:
            repo = Repository(conn)
            kwargs = dict(
                repository=repo,
                bot_name="Rixqor",
                market_hash_name="Some Card (Trading Card)",
                quantity=1,
                acquired_at=date(2026, 10, 1),
                unit_cost=Decimal("0.07"),
                currency="EUR",
                source_type=SourceType.STEAM_MARKET_PURCHASE,
                provenance=Provenance(
                    evidence_type=EvidenceType.STEAM_MARKET_HISTORY,
                    evidence_id="P1",
                    evidence_data={"listingid": "L1"},
                ),
                external_reference="L1:P1",
                entered_at="2026-10-01T08:00:00+00:00",
            )
            first = record_acquisition(**kwargs)
            second = record_acquisition(**kwargs)
            conn.commit()

            assert first.created is True
            assert second.created is False
            assert first.lot.lot_id == second.lot.lot_id
            assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 1
        finally:
            conn.close()

    def test_detector_uses_authenticated_session_for_market_history(self):
        """The detector must consume the very session that was authenticated."""
        path = _write_secret(f"{REQUIRED_COOKIE}={SECRET_VALUE}\n")
        session = requests.Session()
        try:
            apply_steam_web_session(session, path)

            captured = {}

            def fake_get(url, params=None, timeout=None):
                captured["url"] = url
                captured["cookies"] = session.cookies.get_dict()
                response = Mock()
                response.json.return_value = {
                    "success": True,
                    "total_count": 0,
                    "assets": [],
                }
                return response

            session.get = fake_get

            conn = sqlite3.connect(":memory:")
            conn.executescript(
                """
                CREATE TABLE acquisition_processing_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_name TEXT NOT NULL,
                    snapshot_id INTEGER NOT NULL,
                    processed_at TEXT NOT NULL,
                    UNIQUE(bot_name, snapshot_id)
                );
                """
            )
            conn.commit()
            try:
                detector = AcquisitionDetector(Repository(conn), "Rixqor")
                purchases = detector.fetch_market_history_for_item(
                    "Some Card (Trading Card)", date(2026, 10, 1), session
                )
            finally:
                conn.close()
        finally:
            os.unlink(path)

        assert captured["url"].endswith("/market/myhistory/render/")
        assert captured["cookies"][REQUIRED_COOKIE] == SECRET_VALUE
        # No matching purchase evidence -> empty, so UNKNOWN remains reachable.
        assert purchases == []


if __name__ == "__main__":
    import unittest

    unittest.main(verbosity=2)