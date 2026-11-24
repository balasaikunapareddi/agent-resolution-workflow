"""Customer order data: read-only lookup over the shipped CSV."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ORDERS_CSV = DATA_DIR / "customer_orders.csv"


@dataclass(frozen=True)
class Order:
    """One Northstar Goods order, exactly as stored in the CSV."""

    order_id: str
    customer_name: str
    customer_email: str
    item: str
    item_price: float
    status: str  # delivered | in_transit | cancelled
    order_date: str  # YYYY-MM-DD
    promised_date: str  # YYYY-MM-DD, "" if none
    delivered_date: str  # YYYY-MM-DD, "" if not delivered

    def to_dict(self) -> dict:
        """JSON-friendly form, as returned to the agent."""
        return {
            "order_id": self.order_id,
            "customer_name": self.customer_name,
            "customer_email": self.customer_email,
            "item": self.item,
            "item_price": self.item_price,
            "status": self.status,
            "order_date": self.order_date,
            "promised_date": self.promised_date,
            "delivered_date": self.delivered_date,
        }


def load_orders(csv_path: Path | str = ORDERS_CSV) -> list[Order]:
    """Load every order from the CSV. Raises FileNotFoundError if missing.

    A malformed row (missing column, bad price) raises a ValueError naming
    the file and row instead of a bare KeyError/ValueError from the csv
    module — a bad data file should fail loudly and precisely.
    """
    orders: list[Order] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for n, row in enumerate(reader, start=2):  # header is row 1
            try:
                orders.append(
                    Order(
                        order_id=row["order_id"].strip(),
                        customer_name=row["customer_name"].strip(),
                        customer_email=row["customer_email"].strip(),
                        item=row["item"].strip(),
                        item_price=float(row["item_price"]),
                        status=row["status"].strip(),
                        order_date=row["order_date"].strip(),
                        promised_date=(row.get("promised_date") or "").strip(),
                        delivered_date=(row.get("delivered_date") or "").strip(),
                    )
                )
            except (KeyError, ValueError, AttributeError) as e:
                raise ValueError(
                    f"{csv_path}: row {n} is malformed ({e}); "
                    "expected order_id, customer_name, customer_email, item, "
                    "item_price, status, order_date, promised_date, delivered_date"
                ) from e
    return orders


def find_order(order_id: str, orders: list[Order] | None = None) -> Order | None:
    """Find one order by id (case-insensitive, whitespace-tolerant)."""
    wanted = order_id.strip().upper()
    for order in orders if orders is not None else load_orders():
        if order.order_id.upper() == wanted:
            return order
    return None
