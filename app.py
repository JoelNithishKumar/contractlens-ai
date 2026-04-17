from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.comparator import simple_rule_compare
from src.llm_client import compare_to_standard_cached, extract_contract_json_cached
from src.parsers import extract_text_from_bytes
from src.utils import file_fingerprint, safe_json_dump

st.set_page_config(page_title="ContractLens AI", layout="wide")

st.title("ContractLens AI")
st.caption("AI-assisted contract intake and document standardization for project management support")

if "results" not in st.session_state:
    st.session_state.results = []

if "standard_json" not in st.session_state:
    st.session_state.standard_json = None

if "debug_docs" not in st.session_state:
    st.session_state.debug_docs = []

if "standard_filename" not in st.session_state:
    st.session_state.standard_filename = None

uploaded_files = st.file_uploader(
    "Upload contract documents",
    type=["pdf", "docx", "txt"],
    accept_multiple_files=True,
)

selected_standard = None

if uploaded_files:
    st.subheader("Uploaded Files")
    uploaded_names = [f.name for f in uploaded_files]
    for name in uploaded_names:
        st.write(f"- {name}")

    selected_standard = st.selectbox(
        "Select the standard / benchmark document",
        options=uploaded_names,
        index=0,
    )

analyze_clicked = st.button("Analyze Documents", type="primary")

if analyze_clicked:
    if not uploaded_files:
        st.warning("Please upload at least one file.")
        st.stop()

    if len(uploaded_files) < 2:
        st.warning("Please upload at least 2 files.")
        st.stop()

    st.session_state.results = []
    st.session_state.standard_json = None
    st.session_state.debug_docs = []
    st.session_state.standard_filename = selected_standard

    extracted_docs: List[Dict[str, Any]] = []
    total_files = len(uploaded_files)

    progress_bar = st.progress(0)
    status_box = st.empty()

    for idx, file in enumerate(uploaded_files, start=1):
        status_box.info(f"Processing file {idx}/{total_files}: {file.name}")

        try:
            file_bytes = file.getvalue()
            fp = file_fingerprint(file.name, file_bytes)

            text = extract_text_from_bytes(file.name, file_bytes)

            if not text.strip():
                extracted_docs.append({
                    "filename": file.name,
                    "fingerprint": fp,
                    "text_preview": "",
                    "json": {"error": "No extractable text found"},
                    "status": "failed",
                })
            else:
                extracted_json = extract_contract_json_cached(text, file.name)
                extracted_docs.append({
                    "filename": file.name,
                    "fingerprint": fp,
                    "text_preview": text[:1000],
                    "json": extracted_json,
                    "status": "success",
                })

        except Exception as e:
            extracted_docs.append({
                "filename": file.name,
                "fingerprint": "unknown",
                "text_preview": "",
                "json": {"error": str(e)},
                "status": "failed",
            })

        progress_bar.progress(idx / total_files)

    st.session_state.debug_docs = extracted_docs

    standard_doc = next(
        (doc for doc in extracted_docs if doc["filename"] == st.session_state.standard_filename),
        None
    )

    if standard_doc is None:
        st.error("Could not find the selected standard document.")
        st.stop()

    st.session_state.standard_json = standard_doc["json"]

    if "error" in st.session_state.standard_json:
        st.error(f"Selected standard document failed: {st.session_state.standard_filename}")
        st.code(safe_json_dump(st.session_state.standard_json), language="json")
        st.stop()

    standard_json_str = safe_json_dump(st.session_state.standard_json)

    comparison_candidates = [
        doc for doc in extracted_docs
        if doc["filename"] != st.session_state.standard_filename
    ]

    if not comparison_candidates:
        st.warning("No comparison documents found.")
        st.stop()

    for idx, doc in enumerate(comparison_candidates, start=1):
        status_box.info(f"Comparing document {idx}/{len(comparison_candidates)}: {doc['filename']}")

        candidate_json = doc["json"]

        if "error" in candidate_json:
            result = {
                "filename": doc["filename"],
                "comparison": {"error": candidate_json["error"]},
                "candidate_json": candidate_json,
            }
        else:
            try:
                candidate_json_str = safe_json_dump(candidate_json)
                ai_comparison = compare_to_standard_cached(
                    standard_json_str,
                    candidate_json_str,
                )
            except Exception as e:
                fallback = simple_rule_compare(st.session_state.standard_json, candidate_json)
                fallback["comparison_note"] = f"AI comparison failed, used fallback rules: {str(e)}"
                ai_comparison = fallback

            result = {
                "filename": doc["filename"],
                "comparison": ai_comparison,
                "candidate_json": candidate_json,
            }

        st.session_state.results.append(result)

    status_box.success("Analysis complete.")

# Top executive summary
if st.session_state.results:
    valid_results = [
        r for r in st.session_state.results
        if "error" not in r["comparison"]
    ]

    if valid_results:
        high_risk = sum(1 for r in valid_results if r["comparison"].get("risk_level") == "Red")
        medium_risk = sum(1 for r in valid_results if r["comparison"].get("risk_level") == "Yellow")
        low_risk = sum(1 for r in valid_results if r["comparison"].get("risk_level") == "Green")
        total_missing = sum(len(r["comparison"].get("missing_items", [])) for r in valid_results)
        total_differences = sum(len(r["comparison"].get("differences", [])) for r in valid_results)

        st.subheader("Executive Summary")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Documents Analyzed", len(valid_results))
        c2.metric("High Risk", high_risk)
        c3.metric("Medium Risk", medium_risk)
        c4.metric("Missing Items", total_missing)
        c5.metric("Differences", total_differences)

if st.session_state.debug_docs:
    st.subheader("Document Processing Status")
    status_rows = []

    for doc in st.session_state.debug_docs:
        status_rows.append({
            "filename": doc["filename"],
            "status": doc["status"],
            "has_error": "error" in doc["json"],
        })

    st.dataframe(pd.DataFrame(status_rows), use_container_width=True)

if st.session_state.standard_json and "error" not in st.session_state.standard_json:
    st.subheader("Standard Document")
    st.write(f"Using standard: **{st.session_state.standard_filename}**")
    with st.expander("View extracted standard JSON"):
        st.code(safe_json_dump(st.session_state.standard_json), language="json")

if st.session_state.results:
    st.subheader("Comparison Results")
    summary_rows = []

    for result in st.session_state.results:
        filename = result["filename"]
        comparison = result["comparison"]
        candidate_json = result["candidate_json"]

        if "error" in comparison:
            st.error(f"{filename}: {comparison['error']}")
            continue

        risk_level = comparison.get("risk_level", "Unknown")

        summary_rows.append({
            "filename": filename,
            "risk_level": risk_level,
            "differences": len(comparison.get("differences", [])),
            "missing_items": len(comparison.get("missing_items", [])),
        })

        if risk_level == "Red":
            st.error(f"{filename} — Risk: {risk_level}")
        elif risk_level == "Yellow":
            st.warning(f"{filename} — Risk: {risk_level}")
        else:
            st.success(f"{filename} — Risk: {risk_level}")

        if comparison.get("comparison_note"):
            st.info(comparison["comparison_note"])

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**PM Summary**")
            st.write(comparison.get("pm_summary", "No summary available."))

            st.markdown("**Recommended Actions**")
            for item in comparison.get("recommended_actions", []):
                st.write(f"- {item}")

            st.markdown("**Missing Items**")
            for item in comparison.get("missing_items", []):
                st.write(f"- {item}")

        with col2:
            st.markdown("**Differences**")
            for item in comparison.get("differences", []):
                st.write(f"- {item}")

            st.markdown("**Matches**")
            for item in comparison.get("matches", []):
                st.write(f"- {item}")

        # Side-by-side comparison table
        field_comparison = comparison.get("field_comparison", [])
        if field_comparison:
            st.markdown("**Field-by-Field Comparison**")
            st.dataframe(pd.DataFrame(field_comparison), use_container_width=True)

        # Follow-up email draft
        follow_up_email = comparison.get("follow_up_email", "")
        if follow_up_email:
            st.markdown("**Draft Follow-Up Email**")
            st.text_area(
                f"Email draft for {filename}",
                value=follow_up_email,
                height=180,
                key=f"email_{filename}"
            )

        with st.expander(f"View extracted JSON — {filename}"):
            st.code(safe_json_dump(candidate_json), language="json")

    if summary_rows:
        st.subheader("Summary Table")
        df = pd.DataFrame(summary_rows)
        st.dataframe(df, use_container_width=True)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download summary CSV",
            data=csv_bytes,
            file_name="contractlens_summary.csv",
            mime="text/csv",
        )