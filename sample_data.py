import pandas as pd


def make_sample_data():
    return {
        "orders": pd.DataFrame([
            {
                "order_id": "ORD-1001", "customer": "Asha",
                "product_id": "SKU-A", "quantity": 2,
                "amount": 2000, "payment_status": "paid",
            },
            {
                "order_id": "ORD-1002", "customer": "Rahul",
                "product_id": "SKU-B", "quantity": 3,
                "amount": 4500, "payment_status": "paid",
            },
            {
                "order_id": "ORD-1003", "customer": "Mira",
                "product_id": "SKU-A", "quantity": 1,
                "amount": 1000, "payment_status": "paid",
            },
            {
                "order_id": "ORD-1004", "customer": "Dev",
                "product_id": "SKU-C", "quantity": 1,
                "amount": 800, "payment_status": "pending",
            },
        ]),
        "inventory": pd.DataFrame([
            {"product_id": "SKU-A", "product_name": "Desk lamp",
             "available_stock": 2},
            {"product_id": "SKU-B", "product_name": "Office chair",
             "available_stock": 2},
            {"product_id": "SKU-C", "product_name": "Notebook",
             "available_stock": 20},
        ]),
        "invoices": pd.DataFrame([
            {"invoice_id": "INV-501", "order_id": "ORD-1001",
             "amount": 2000},
            {"invoice_id": "INV-502", "order_id": "ORD-1002",
             "amount": 4000},
            {"invoice_id": "INV-502", "order_id": "ORD-1002",
             "amount": 4000},
        ]),
        "shipments": pd.DataFrame([
            {"order_id": "ORD-1001", "shipment_status": "shipped"},
        ]),
    }