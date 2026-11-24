"""Order data: the shipped CSV loads and lookups behave."""

from agent_resolution_workflow.orders import find_order, load_orders


def test_loads_all_shipped_orders():
    orders = load_orders()
    assert len(orders) == 10
    assert {o.order_id for o in orders} == {
        "CM-1042",
        "CM-1043",
        "CM-1044",
        "CM-1045",
        "CM-1046",
        "CM-1047",
        "CM-1048",
        "CM-1049",
        "CM-1050",
        "CM-1051",
    }


def test_find_cm1042_has_the_demo_facts():
    order = find_order("CM-1042")
    assert order is not None
    assert order.customer_name == "Maya Chen"
    assert order.customer_email == "maya.chen@example.com"
    assert order.item == "Ceramic Pour-Over Coffee Set"
    assert order.status == "delivered"
    assert order.delivered_date == "2026-11-10"


def test_find_is_case_insensitive_and_trims():
    assert find_order("cm-1042") is not None
    assert find_order("  CM-1042  ") is not None


def test_find_unknown_order_returns_none():
    assert find_order("CM-9999") is None


def test_to_dict_is_json_friendly():
    order = find_order("CM-1043")
    assert order is not None
    data = order.to_dict()
    assert data["order_id"] == "CM-1043"
    assert data["status"] == "delivered"
    assert data["promised_date"] == "2026-11-04"
    assert data["delivered_date"] == "2026-11-12"


def test_malformed_csv_row_raises_a_clear_error(tmp_path):
    """Review fix: a bad price or missing column used to raise a bare
    KeyError/ValueError with no file or row context."""
    import pytest
    from agent_resolution_workflow.orders import load_orders
    bad = tmp_path / "orders.csv"
    bad.write_text(
        "order_id,customer_name,customer_email,item,item_price,status,order_date,promised_date,delivered_date\n"
        "CM-9999,Test User,test@example.com,Widget,not-a-price,delivered,2026-11-01,2026-11-05,2026-11-05\n"
    )
    with pytest.raises(ValueError) as exc:
        load_orders(bad)
    assert "row 2" in str(exc.value)
    assert "orders.csv" in str(exc.value)
