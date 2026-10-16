from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from database import (
    audit_history,
    initialize_database,
    latest_reviews,
    save_review,
)
from engine import REQUIRED_COLUMNS, detect_incidents, investigate_incident
from sample_data import make_sample_data


st.set_page_config(
    page_title="OpsPilot AI",
    page_icon="🔎",
    layout="wide",
)

initialize_database()

st.title("🔎 OpsPilot AI")
st.caption("Business Operations Intelligence · Detect. Investigate. Recommend.")

if "business_data" not in st.session_state:
    st.session_state.business_data = make_sample_data()

if "last_upload_error" not in st.session_state:
    st.session_state.last_upload_error = ""

with st.sidebar:
    st.header("Data workspace")
    st.caption("Start with demo data or upload your own CSV files.")

    if st.button("Restore sample data", use_container_width=True):
        st.session_state.business_data = make_sample_data()
        st.session_state.last_upload_error = ""
        st.rerun()

    upload_names = ["orders", "inventory", "invoices", "shipments"]
    uploaded = {}

    for name in upload_names:
        uploaded[name] = st.file_uploader(
            f"{name.title()} CSV",
            type=["csv"],
            key=f"upload_{name}",
        )

    if st.button("Load CSV files", use_container_width=True):
        try:
            updated = dict(st.session_state.business_data)

            for name, file in uploaded.items():
                if file is None:
                    continue

                frame = pd.read_csv(file)
                frame.columns = [
                    str(column).strip().lower()
                    for column in frame.columns
                ]

                missing = REQUIRED_COLUMNS[name] - set(frame.columns)
                if missing:
                    raise ValueError(
                        f"{name}.csv is missing: "
                        + ", ".join(sorted(missing))
                    )

                if frame.empty:
                    raise ValueError(f"{name}.csv contains no records.")

                updated[name] = frame

            # Validate all datasets together before changing active data.
            from engine import validate_data
            validate_data(updated)

            st.session_state.business_data = updated
            st.session_state.last_upload_error = ""
            st.rerun()

        except Exception as exc:
            st.session_state.last_upload_error = str(exc)

    if st.session_state.last_upload_error:
        st.error(st.session_state.last_upload_error)

    st.divider()
    st.caption("Demo mode uses synthetic data. Avoid uploading sensitive customer data to a public demo.")


data = st.session_state.business_data

try:
    raw_incidents = detect_incidents(data)
except (ValueError, KeyError, TypeError) as exc:
    st.error(f"Could not analyze the current datasets: {exc}")
    st.stop()

reviews = latest_reviews()

for incident in raw_incidents:
    review = reviews.get(incident["incident_id"])
    incident["review_status"] = review["decision"] if review else "Open"
    incident["review_note"] = review["note"] if review else ""
    incident["reviewed_at"] = review["created_at"] if review else ""

high_count = sum(
    incident["severity"] in {"High", "Critical"}
    and incident["review_status"] == "Open"
    for incident in raw_incidents
)
open_count = sum(
    incident["review_status"] == "Open"
    for incident in raw_incidents
)
total_exposure = sum(
    incident["estimated_amount"]
    for incident in raw_incidents
)

metric1, metric2, metric3 = st.columns(3)
metric1.metric("Exceptions detected", len(raw_incidents))
metric2.metric("Awaiting review", open_count)
metric3.metric("High-priority open", high_count)

overview_tab, investigate_tab, data_tab, audit_tab = st.tabs([
    "Overview",
    "Investigate",
    "Source data",
    "Audit history",
])

with overview_tab:
    st.subheader("Operations overview")

    if not raw_incidents:
        st.success("No exceptions were detected in the current datasets.")
    else:
        overview = pd.DataFrame([
            {
                "Incident": item["incident_id"],
                "Priority": item["severity"],
                "Type": item["type"],
                "Finding": item["title"],
                "Amount for review": item["estimated_amount"],
                "Review status": item["review_status"],
            }
            for item in raw_incidents
        ])

        priority_filter = st.multiselect(
            "Filter by priority",
            ["Critical", "High", "Medium", "Low"],
            default=["Critical", "High", "Medium", "Low"],
        )
        status_filter = st.multiselect(
            "Filter by status",
            ["Open", "Approved", "Rejected", "Needs review"],
            default=["Open", "Approved", "Rejected", "Needs review"],
        )

        filtered = overview[
            overview["Priority"].isin(priority_filter)
            & overview["Review status"].isin(status_filter)
        ]

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True,
        )

        if not filtered.empty:
            chart = filtered["Type"].value_counts()
            st.bar_chart(chart)

        st.download_button(
            "Download incident report",
            data=overview.to_csv(index=False).encode("utf-8"),
            file_name="opspilot_incidents.csv",
            mime="text/csv",
        )

    st.caption(
        "Amounts are indicators requiring investigation, not confirmed losses. "
        "Amounts across different incident types may overlap."
    )

with investigate_tab:
    st.subheader("Incident investigation")

    if not raw_incidents:
        st.info("There are no incidents to investigate.")
    else:
        incident_map = {
            item["incident_id"]: item for item in raw_incidents
        }

        selected_id = st.selectbox(
            "Select an incident",
            list(incident_map),
            format_func=lambda incident_id: (
                f"{incident_map[incident_id]['severity']} · "
                f"{incident_map[incident_id]['title']}"
            ),
        )

        item = incident_map[selected_id]
        investigation = investigate_incident(item)

        left, right = st.columns([2, 1])
        with left:
            st.markdown(f"### {item['title']}")
            st.write(f"**Incident ID:** `{item['incident_id']}`")
            st.write(f"**Category:** {item['type']}")
            st.write(f"**Priority:** {item['severity']}")
            st.write("**Evidence**")
            for evidence in item["evidence"]:
                st.markdown(f"- {evidence}")

        with right:
            st.metric("Amount for review", f"{item['estimated_amount']:,.2f}")
            st.write("**Review status**")
            st.write(item["review_status"])
            st.write("**Affected records**")
            for record in item["affected_records"]:
                st.code(record, language=None)

        st.markdown("#### Investigation result")
        st.write(investigation["cause_status"])
        st.write("**Recommended next step**")
        st.info(item["recommended_action"])

        st.warning(
            "Review decisions are recorded for traceability. "
            "Approving a recommendation does not execute an external action."
        )

        with st.expander("View structured investigation output"):
            st.code(
                json.dumps(investigation, indent=2),
                language="json",
            )

        note = st.text_area(
            "Reviewer note (optional)",
            key=f"note_{selected_id}",
            placeholder="Explain the decision or record what needs checking...",
        )

        a, b, c = st.columns(3)

        if a.button("Approve recommendation", use_container_width=True):
            save_review(selected_id, "Approved", note)
            st.rerun()

        if b.button("Reject recommendation", use_container_width=True):
            save_review(selected_id, "Rejected", note)
            st.rerun()

        if c.button("Needs more review", use_container_width=True):
            save_review(selected_id, "Needs review", note)
            st.rerun()

        if item["review_note"]:
            st.caption(f"Latest note: {item['review_note']}")

with data_tab:
    st.subheader("Source data")
    for name, frame in data.items():
        with st.expander(f"{name.title()} · {len(frame)} rows"):
            st.dataframe(frame, use_container_width=True, hide_index=True)
            st.download_button(
                f"Download {name}.csv",
                frame.to_csv(index=False).encode("utf-8"),
                file_name=f"{name}.csv",
                mime="text/csv",
                key=f"download_{name}",
            )

with audit_tab:
    st.subheader("Audit history")
    history = audit_history()

    if not history:
        st.info("No review decisions have been recorded yet.")
    else:
        audit_frame = pd.DataFrame(history)
        st.dataframe(
            audit_frame,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Download audit history",
            audit_frame.to_csv(index=False).encode("utf-8"),
            file_name="opspilot_audit_history.csv",
            mime="text/csv",
        )

st.divider()
st.caption(
    "OpsPilot AI · Local-first MVP · Human-reviewed recommendations · "
    "No automatic changes to external business systems"
)