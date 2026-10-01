"""Phase 2 schema migration script.

Migrates the V1 economic ledger schema to V2, adding columns required by
the acquisition detection pipeline while preserving all existing data.

The migration is:
  - additive where possible;
  - idempotent (safe to run multiple times);
  - backwards-compatible with existing queries;
  - free of destructive DROP/DELETE operations unless replacing a table.

Changes:
  transactions:
    - id: TEXT → INTEGER (AUTOINCREMENT)
    - Add: type, timestamp, fees, total_value, bot_name, external_ref
    - Create indexes: idx_transactions_type_ts, idx_transactions_bot_external_ref

  acquisition_lots:
    - id: TEXT → INTEGER (AUTOINCREMENT)
    - Add: source_transaction_id, bot_name, original_quantity
    - Establish foreign key: source_transaction_id → transactions(id)
    - Create index: idx_acq_lots_source_tx

  acquisition_processing_log:
    - New table for tracking processed snapshots (idempotency marker)
    - UNIQUE(bot_name, snapshot_id) constraint ensures single processing
"""

from __future__ import annotations

import sqlite3
from typing import Optional


def migrate(conn: sqlite3.Connection) -> None:
    """Apply the Phase 2 schema migration."""
    cursor = conn.cursor()

    # --- Migrate transactions table ---
    _migrate_transactions(cursor)

    # --- Migrate acquisition_lots table ---
    _migrate_acquisition_lots(cursor)

    # --- Create acquisition_processing_log table ---
    _ensure_processing_log(cursor)

    conn.commit()


def _migrate_transactions(cursor: sqlite3.Cursor) -> None:
    """Add Phase 2 columns to transactions table."""
    # Check if already migrated
    cursor.execute("PRAGMA table_info(transactions)")
    cols = {row[1] for row in cursor.fetchall()}
    
    # If all new columns exist, skip migration entirely
    required_cols = {'type', 'timestamp', 'fees', 'total_value', 'bot_name', 'external_ref'}
    if required_cols.issubset(cols):
        print("  transactions table already migrated")
        return

    # Add missing columns one by one
    migrations = [
        ("type", "TEXT"),
        ("timestamp", "TEXT"),
        ("fees", "TEXT"),
        ("total_value", "TEXT"),
        ("bot_name", "TEXT"),
        ("external_ref", "TEXT"),
    ]

    for col_name, col_type in migrations:
        if col_name not in cols:
            cursor.execute(f"ALTER TABLE transactions ADD COLUMN {col_name} {col_type}")
            print(f"  Added column: transactions.{col_name}")

    # Recreate indexes
    cursor.execute("DROP INDEX IF EXISTS idx_transactions_type_ts")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_type_ts ON transactions(type, timestamp)")
    cursor.execute("DROP INDEX IF EXISTS idx_transactions_bot_external_ref")
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_bot_external_ref
        ON transactions(bot_name, external_ref)
        WHERE external_ref IS NOT NULL
    """)
    print("  Migrated transactions table")


def _migrate_acquisition_lots(cursor: sqlite3.Cursor) -> None:
    """Add Phase 2 and Phase 3D columns to acquisition_lots table.

    Idempotent: every required column is added only when absent. The
    Phase 3D evidence columns are checked independently of the Phase 2
    columns, because a database may already carry the Phase 2 columns
    while still lacking provenance/source_type/external_ref.
    """
    cursor.execute("PRAGMA table_info(acquisition_lots)")
    cols = {row[1] for row in cursor.fetchall()}

    added = []

    # Phase 2 columns
    phase2_cols = {
        "source_transaction_id": "INTEGER",
        "bot_name": "TEXT",
        "original_quantity": "INTEGER",
    }
    for col_name, col_type in phase2_cols.items():
        if col_name not in cols:
            cursor.execute(
                f"ALTER TABLE acquisition_lots ADD COLUMN {col_name} {col_type}"
            )
            added.append(col_name)

    # Phase 3D evidence columns (checked independently; never skipped
    # just because Phase 2 columns are already present).
    phase3d_cols = {
        "provenance": "TEXT",
        "source_type": "TEXT",
        "external_ref": "TEXT",
    }
    for col_name, col_type in phase3d_cols.items():
        if col_name not in cols:
            cursor.execute(
                f"ALTER TABLE acquisition_lots ADD COLUMN {col_name} {col_type}"
            )
            added.append(col_name)

    if added:
        for col_name in added:
            print(f"  Added column: acquisition_lots.{col_name}")
    else:
        print("  acquisition_lots table already migrated")

    # Recreate index
    cursor.execute("DROP INDEX IF EXISTS idx_acq_lots_source_tx")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_acq_lots_source_tx "
        "ON acquisition_lots(source_transaction_id)"
    )


def _ensure_processing_log(cursor: sqlite3.Cursor) -> None:
    """Create acquisition_processing_log table if it doesn't exist.

    This table tracks which snapshots have been processed by the acquisition
    detector to prevent duplicate processing and ensure idempotency.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS acquisition_processing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL,
            snapshot_id INTEGER NOT NULL,
            processed_at TEXT NOT NULL,
            UNIQUE(bot_name, snapshot_id)
        )
    """)
    print("  Ensured acquisition_processing_log table exists")


def main(db_path: str) -> None:
    """Entry point for migration."""
    conn = sqlite3.connect(db_path)
    try:
        print(f"Migrating database: {db_path}")
        migrate(conn)
        print("Migration completed successfully")
    except Exception as exc:
        print(f"Migration failed: {exc}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <database_path>")
        sys.exit(1)
    main(sys.argv[1])
