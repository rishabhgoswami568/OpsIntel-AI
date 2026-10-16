from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {
    "orders": {
        "order_id",
        "customer",
        "product_id",
        "quantity",
        "amount",
        "payment_status",
    },
    "inventory": {
        "product_id",
        "product_name",
        "available_stock",
    },
    "invoices": {
        "invoice_id",
        "order_id",
        "amount",
    },
    "shipments": {
        "order_id",
        "shipment_status",
    },
}

PRIORITY_SCORE = {
    "Critical": 4,
    "High": 3,
    "Medium": 2,
    "Low": 1,
}


def validate_data(data: dict[str, pd.DataFrame]) -> None:
    """Validate required datasets and columns.

    Empty datasets are allowed because a business may legitimately
    have no orders, invoices, or shipments at a given time.
    """
    for name, required in REQUIRED_COLUMNS.items():
        if name not in data:
            raise ValueError(f"Missing dataset: {name}")

        if not isinstance(data[name], pd.DataFrame):
            raise ValueError(
                f"{name} must be a pandas DataFrame."
            )

        missing = required - set(data[name].columns)

        if missing:
            raise ValueError(
                f"{name} is missing columns: "
                f"{', '.join(sorted(missing))}"
            )


def stable_id(kind: str, *parts: Any) -> str:
    """Generate a deterministic incident ID."""
    normalized_parts = sorted(str(part) for part in parts)
    raw = "|".join([kind, *normalized_parts])

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:12].upper()

    return f"EX-{digest}"


def as_number(value: Any) -> float | None:
    """Convert a value to a number, or return None if invalid."""
    try:
        result = float(value)

        if pd.isna(result):
            return None

        return result

    except (TypeError, ValueError, OverflowError):
        return None


def detect_incidents(
    data: dict[str, pd.DataFrame],
    mismatch_tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    """Detect operational exceptions in business datasets.

    Findings require human verification. They do not prove fraud
    or establish confirmed financial losses.
    """
    if mismatch_tolerance < 0:
        raise ValueError(
            "mismatch_tolerance cannot be negative."
        )

    validate_data(data)

    orders = data["orders"].copy()
    inventory = data["inventory"].copy()
    invoices = data["invoices"].copy()
    shipments = data["shipments"].copy()

    incidents: list[dict[str, Any]] = []

    def add(
        kind: str,
        severity: str,
        title: str,
        evidence: list[str],
        records: list[str],
        recommendation: str,
        amount: float = 0.0,
    ) -> None:
        """Add one evidence-linked incident."""
        records = sorted(set(records))

        incidents.append({
            "incident_id": stable_id(kind, *records),
            "type": kind,
            "severity": severity,
            "title": title,
            "evidence": evidence,
            "affected_records": records,
            "estimated_amount": round(
                max(amount, 0.0), 2
            ),
            "recommended_action": recommendation,
        })

    # 1. Detect duplicate invoice IDs.
    duplicate_rows = invoices[
        invoices["invoice_id"]
        .astype(str)
        .duplicated(keep=False)
    ]

    for invoice_id, group in duplicate_rows.groupby(
        "invoice_id", dropna=False
    ):
        order_refs = group["order_id"].astype(str).tolist()

        add(
            "Duplicate invoice",
            "High",
            f"Invoice {invoice_id} appears in multiple rows",
            [
                f"Invoice identifier: {invoice_id}",
                f"Number of matching rows: {len(group)}",
                (
                    "Verify whether these rows are duplicate "
                    "entries or legitimate revisions."
                ),
            ],
            [
                f"invoice:{invoice_id}",
                *[f"order:{ref}" for ref in order_refs],
            ],
            (
                "Compare invoice dates and line items, then "
                "confirm whether a duplicate exists."
            ),
            sum(
                as_number(value) or 0.0
                for value in group["amount"]
            ),
        )

    # 2. Prepare inventory lookup.
    # Products with duplicate IDs are excluded because their stock
    # quantity is ambiguous.
    stock = inventory.drop_duplicates(
        "product_id",
        keep=False,
    )

    stock_lookup = stock.set_index(
        "product_id",
        drop=False,
    )

    # 3. Detect unknown products, invalid quantities, and shortages.
    for _, order in orders.iterrows():
        order_id = str(order["order_id"])
        product_id = str(order["product_id"])

        quantity = as_number(order["quantity"])
        amount = as_number(order["amount"]) or 0.0

        if product_id not in stock_lookup.index:
            add(
                "Unknown product",
                "Medium",
                f"Product {product_id} is absent from inventory",
                [
                    f"Order {order_id} references product {product_id}.",
                    (
                        "No unique matching inventory record "
                        "was found."
                    ),
                ],
                [
                    f"order:{order_id}",
                    f"product:{product_id}",
                ],
                (
                    "Verify the product identifier and correct "
                    "the product catalog."
                ),
                amount,
            )
            continue

        stock_row = stock_lookup.loc[product_id]
        available = as_number(stock_row["available_stock"])

        if (
            quantity is None
            or available is None
            or quantity < 0
            or available < 0
        ):
            add(
                "Invalid quantity data",
                "Medium",
                f"Quantity data needs review for {order_id}",
                [
                    f"Order quantity: {order['quantity']}",
                    (
                        "Recorded available stock: "
                        f"{stock_row['available_stock']}"
                    ),
                    (
                        "A value is invalid, missing, or negative."
                    ),
                ],
                [
                    f"order:{order_id}",
                    f"product:{product_id}",
                ],
                (
                    "Correct the source data before evaluating "
                    "stock availability."
                ),
                amount,
            )

        elif quantity > available:
            add(
                "Stock shortage",
                "High",
                f"Order {order_id} exceeds recorded stock",
                [
                    f"Product: {product_id}",
                    f"Requested quantity: {quantity:g}",
                    f"Recorded available stock: {available:g}",
                    (
                        "Other orders and stock allocations have "
                        "not been accounted for."
                    ),
                ],
                [
                    f"order:{order_id}",
                    f"product:{product_id}",
                ],
                (
                    "Verify physical stock and review allocations "
                    "before promising fulfillment."
                ),
                amount,
            )

    # 4. Detect paid orders without a completed shipment.
    completed_statuses = {
        "shipped",
        "delivered",
        "complete",
        "completed",
    }

    shipment_status = (
        shipments["shipment_status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    completed_orders = set(
        shipments.loc[
            shipment_status.isin(completed_statuses),
            "order_id",
        ].astype(str)
    )

    paid_statuses = {
        "paid",
        "complete",
        "completed",
    }

    for _, order in orders.iterrows():
        order_id = str(order["order_id"])
        payment = (
            str(order["payment_status"])
            .strip()
            .lower()
        )

        if (
            payment in paid_statuses
            and order_id not in completed_orders
        ):
            add(
                "Paid but not shipped",
                "High",
                f"Paid order {order_id} has no completed shipment",
                [
                    f"Payment status: {payment}",
                    (
                        "No shipment record with a completed "
                        "status was found."
                    ),
                    (
                        "A missing or delayed status may differ "
                        "from an actual fulfillment failure."
                    ),
                ],
                [f"order:{order_id}"],
                (
                    "Check the fulfillment system and shipment "
                    "records before contacting the customer."
                ),
                as_number(order["amount"]) or 0.0,
            )

    # 5. Prepare order totals for invoice comparisons.
    # Conflicting or invalid order amounts cannot be compared reliably.
    order_groups = orders.groupby(
        "order_id",
        dropna=False,
    )

    order_lookup: dict[str, float | None] = {}

    for order_id, group in order_groups:
        values = [
            as_number(value)
            for value in group["amount"]
        ]

        unique_values = {
            value
            for value in values
            if value is not None
        }

        order_lookup[str(order_id)] = (
            next(iter(unique_values))
            if (
                len(unique_values) == 1
                and all(value is not None for value in values)
            )
            else None
        )

    # 6. Detect unmatched invoices, invalid amounts, and mismatches.
    for _, invoice in invoices.iterrows():
        invoice_id = str(invoice["invoice_id"])
        order_id = str(invoice["order_id"])

        invoice_amount = as_number(invoice["amount"])

        if order_id not in order_lookup:
            add(
                "Unmatched invoice",
                "Medium",
                (
                    f"Invoice {invoice_id} references "
                    f"unknown order {order_id}"
                ),
                [
                    f"Invoice amount: {invoice_amount}",
                    "No matching order was found.",
                ],
                [
                    f"invoice:{invoice_id}",
                    f"order:{order_id}",
                ],
                (
                    "Find the corresponding order or correct "
                    "the invoice reference."
                ),
                invoice_amount or 0.0,
            )
            continue

        order_amount = order_lookup[order_id]

        if (
            invoice_amount is None
            or invoice_amount < 0
            or order_amount is None
        ):
            add(
                "Invalid financial data",
                "Medium",
                f"Amount needs review for invoice {invoice_id}",
                [
                    f"Invoice amount: {invoice['amount']}",
                    f"Order amount: {order_amount}",
                    (
                        "A valid numerical comparison could not "
                        "be completed."
                    ),
                ],
                [
                    f"invoice:{invoice_id}",
                    f"order:{order_id}",
                ],
                (
                    "Correct invalid values or resolve conflicting "
                    "order records."
                ),
            )

        elif abs(invoice_amount - order_amount) > mismatch_tolerance:
            difference = abs(invoice_amount - order_amount)

            add(
                "Invoice mismatch",
                "Medium",
                (
                    "Invoice and order totals differ "
                    f"for {order_id}"
                ),
                [
                    f"Invoice amount: {invoice_amount:.2f}",
                    f"Order amount: {order_amount:.2f}",
                    f"Absolute difference: {difference:.2f}",
                    (
                        "Tax, shipping, discounts, or duplicate "
                        "entries may explain the difference."
                    ),
                ],
                [
                    f"invoice:{invoice_id}",
                    f"order:{order_id}",
                ],
                (
                    "Compare line items, taxes, discounts, "
                    "and shipping charges."
                ),
                difference,
            )

    # 7. Return all incidents, sorted by severity and then type.
    return sorted(
        incidents,
        key=lambda item: (
            -PRIORITY_SCORE[item["severity"]],
            item["type"],
            item["incident_id"],
        ),
    )


def investigate_incident(
    incident: dict[str, Any],
) -> dict[str, Any]:
    """Create a structured investigation summary."""
    return {
        "incident_id": incident["incident_id"],
        "finding": incident["title"],
        "confirmed_evidence": incident["evidence"],
        "cause_status": (
            "Unverified — further investigation required"
        ),
        "recommended_action": incident["recommended_action"],
        "requires_human_review": True,
    }