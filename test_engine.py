from engine import detect_incidents, stable_id
from sample_data import make_sample_data


def test_sample_data_detects_known_exceptions():
    incidents = detect_incidents(make_sample_data())
    types = {item["type"] for item in incidents}

    assert "Duplicate invoice" in types
    assert "Stock shortage" in types
    assert "Paid but not shipped" in types
    assert "Invoice mismatch" in types


def test_incident_ids_are_stable():
    first = stable_id("Stock shortage", "order:1", "product:A")
    second = stable_id("Stock shortage", "product:A", "order:1")

    assert first == second


def test_empty_orders_produce_no_order_incidents():
    data = make_sample_data()
    data["orders"] = data["orders"].iloc[0:0]

    incidents = detect_incidents(data)

    assert not any(
        item["type"] in {
            "Stock shortage",
            "Paid but not shipped",
            "Unknown product",
        }
        for item in incidents
    )