"""The pending_review ledger: the ONLY write the workflow performs.

SQLite, stdlib only. A resolution request is a row with status
``pending_review`` — nothing is ever issued, shipped, or refunded here.
The ledger is seeded from the shipped ``data/resolution_requests.csv``
on first creation, so the repo starts with one real prior row.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SEED_CSV = DATA_DIR / "resolution_requests.csv"
DEFAULT_DB = DATA_DIR / "resolution_requests.db"


@dataclass(frozen=True)
class LedgerRow:
    """One recorded resolution request."""

    request_id: str
    order_id: str
    customer_email: str
    issue_category: str
    requested_resolution: str
    status: str  # pending_review (the workflow only ever writes this)
    agent_note: str
    created_at: str  # ISO timestamp

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "order_id": self.order_id,
            "customer_email": self.customer_email,
            "issue_category": self.issue_category,
            "requested_resolution": self.requested_resolution,
            "status": self.status,
            "agent_note": self.agent_note,
            "created_at": self.created_at,
        }


class Ledger:
    """Append-only SQLite ledger of resolution requests."""

    def __init__(self, db_path: Path | str = DEFAULT_DB, seed_csv: Path | str | None = SEED_CSV):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS resolution_requests (
                request_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                issue_category TEXT NOT NULL,
                requested_resolution TEXT NOT NULL,
                status TEXT NOT NULL,
                agent_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )"""
        )
        self._conn.commit()
        # The duplicate guarantee is enforced at the DB level, not just by
        # the check-then-act in workflow.py: at most one pending row per
        # (order, resolution). A racing second insert fails with
        # IntegrityError, which the workflow reports as duplicate_pending.
        # A legacy DB that already holds duplicates cannot take the index;
        # in that case the workflow's check still guards, so init must not
        # crash here.
        try:
            self._conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_unique
                   ON resolution_requests(order_id, requested_resolution)
                   WHERE status = 'pending_review'"""
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            self._conn.rollback()
        if seed_csv is not None and self.count() == 0:
            self._seed_from_csv(Path(seed_csv))

    def _seed_from_csv(self, csv_path: Path) -> None:
        if not csv_path.exists():
            return
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                # Skip malformed seed rows instead of crashing Store load
                # on a missing column; the shipped CSV is well-formed.
                if not row.get("request_id") or not row.get("order_id"):
                    continue
                self._conn.execute(
                    "INSERT OR IGNORE INTO resolution_requests VALUES (?,?,?,?,?,?,?,?)",
                    (
                        row["request_id"],
                        row["order_id"],
                        row.get("customer_email", ""),
                        row.get("issue_category", ""),
                        row.get("requested_resolution", ""),
                        row.get("status", "pending_review"),
                        row.get("agent_note", ""),
                        row.get("created_at", ""),
                    ),
                )
        self._conn.commit()

    def next_request_id(self) -> str:
        """Next id in RR-0001 sequence, derived from the rows present."""
        cur = self._conn.execute("SELECT request_id FROM resolution_requests")
        nums = [
            int(r[0].split("-")[1])
            for r in cur.fetchall()
            if r[0].startswith("RR-") and r[0].split("-")[1].isdigit()
        ]
        return f"RR-{max(nums, default=0) + 1:04d}"

    def add(
        self,
        order_id: str,
        customer_email: str,
        issue_category: str,
        requested_resolution: str,
        agent_note: str,
        created_at: str,
    ) -> LedgerRow:
        """Append a pending_review row and return it."""
        row = LedgerRow(
            request_id=self.next_request_id(),
            order_id=order_id,
            customer_email=customer_email,
            issue_category=issue_category,
            requested_resolution=requested_resolution,
            status="pending_review",
            agent_note=agent_note,
            created_at=created_at,
        )
        self._conn.execute(
            "INSERT INTO resolution_requests VALUES (?,?,?,?,?,?,?,?)",
            (
                row.request_id,
                row.order_id,
                row.customer_email,
                row.issue_category,
                row.requested_resolution,
                row.status,
                row.agent_note,
                row.created_at,
            ),
        )
        self._conn.commit()
        return row

    def find_pending(self, order_id: str, requested_resolution: str) -> LedgerRow | None:
        """The pending request for this order + resolution, if one exists."""
        cur = self._conn.execute(
            "SELECT * FROM resolution_requests WHERE order_id = ? AND requested_resolution = ? AND status = 'pending_review'",
            (order_id.strip().upper(), requested_resolution.strip().lower()),
        )
        row = cur.fetchone()
        return LedgerRow(**dict(row)) if row else None

    def find_by_order(self, order_id: str) -> list[LedgerRow]:
        """Every request ever recorded for an order, oldest first."""
        cur = self._conn.execute(
            "SELECT * FROM resolution_requests WHERE order_id = ? ORDER BY request_id",
            (order_id.strip().upper(),),
        )
        return [LedgerRow(**dict(r)) for r in cur.fetchall()]

    def all(self) -> list[LedgerRow]:
        """Every row, oldest first."""
        cur = self._conn.execute("SELECT * FROM resolution_requests ORDER BY request_id")
        return [LedgerRow(**dict(r)) for r in cur.fetchall()]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM resolution_requests").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
