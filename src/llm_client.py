from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import streamlit as st
from openai import OpenAI

from src.config import OPENAI_API_KEY, OPENAI_MODEL
from src.prompts import EXTRACTION_PROMPT, COMPARISON_PROMPT
from src.rule_extractor import extract_rule_based_fields


@st.cache_resource
def get_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is missing. Check your .env file.")
    return OpenAI(api_key=OPENAI_API_KEY)


def _extract_text_output(response: Any) -> str:
    if hasattr(response, "output_text") and response.output_text:
        return response.output_text
    return str(response)


def _safe_json_load(raw: str) -> Dict[str, Any]:
    raw = raw.replace("```json", "").replace("```", "")
    raw = raw.strip()

    start = raw.find("{")
    end = raw.rfind("}") + 1

    if start != -1 and end != -1:
        raw = raw[start:end]

    return json.loads(raw)


def _collect_high_signal_lines(document_text: str) -> str:
    keywords = [
        "general contractor",
        "subcontract package",
        "project",
        "project location",
        "prime contract reference",
        "subcontract number",
        "contract type",
        "original contract value",
        "base price",
        "proposal no",
        "proposal validity",
        "lead time assumption",
        "exclusions",
        "scope narrative",
        "commercial conditions",
        "payment terms",
        "retainage",
        "retention",
        "schedule of values",
        "change orders",
        "change order",
        "warranty",
        "insurance",
        "commercial general liability",
        "automobile liability",
        "workers’ compensation",
        "workers' compensation",
        "umbrella",
        "excess liability",
        "indemnity",
        "termination",
        "additional insured",
        "primary & non-contributory",
        "primary and non-contributory",
        "supersedes",
        "verbal authorization",
        "written approval",
        "field-directed extra work",
        "owner-directed",
    ]

    lines = [line.strip() for line in document_text.splitlines()]
    filtered: List[str] = []

    for line in lines:
        if not line:
            continue

        low = line.lower()
        if any(k in low for k in keywords):
            filtered.append(line)
            continue

        if re.search(r"\$\s?\d[\d,]*(?:\.\d+)?", line):
            filtered.append(line)
            continue

        if re.search(r"\b(net\s*\d+|45 days|30 days|10%|5%|one-year|two-year)\b", low):
            filtered.append(line)
            continue

    seen = set()
    deduped = []
    for line in filtered:
        if line not in seen:
            deduped.append(line)
            seen.add(line)

    return "\n".join(deduped[:200])


@st.cache_data(show_spinner=False)
def extract_contract_json_cached(document_text: str, filename: str) -> Dict[str, Any]:
    client = get_openai_client()

    high_signal_lines = _collect_high_signal_lines(document_text)
    rule_based_json = extract_rule_based_fields(document_text, filename)

    prompt = f"""
Filename: {filename}

Below are three views of the same document.

====================
RULE-BASED PRE-EXTRACTION
====================
{json.dumps(rule_based_json, indent=2)}

====================
HIGH-SIGNAL LINES
====================
{high_signal_lines}

====================
FULL DOCUMENT TEXT
====================
{document_text}

Your task:
- Improve and complete the RULE-BASED PRE-EXTRACTION using the HIGH-SIGNAL LINES and FULL DOCUMENT TEXT.
- Keep correct values from the rule-based extraction when they are clearly supported.
- Replace "Not found" only when the document contains a real value.
- Correct any rule-based value if the document clearly shows a better one.
- Do not overwrite explicit rule-based values like project_name, contract_value, pricing_structure, payment_terms, insurance_requirements, change_order_process, warranty_terms, or scope_of_work with "Not found".
- If the document states a base price, proposal amount, original contract value, insurance limit, or proposal validity, extract it directly and do not list it as missing.
- Preserve concise factual extraction.
- Return the final JSON only.
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    raw = _extract_text_output(response)
    ai_json = _safe_json_load(raw)

    protected_fields = [
        "party_name",
        "project_name",
        "contract_value",
        "pricing_structure",
        "payment_terms",
        "insurance_requirements",
        "change_order_process",
        "warranty_terms",
        "scope_of_work",
    ]

    def _present(val: Any) -> bool:
        return str(val).strip() not in {"Not found", "", "None", "null"}

    for field in protected_fields:
        rule_val = rule_based_json.get(field, "Not found")
        ai_val = ai_json.get(field, "Not found")

        if _present(rule_val) and not _present(ai_val):
            ai_json[field] = rule_val

    if isinstance(ai_json.get("missing_items"), list):
        cleaned_missing = []
        for item in ai_json["missing_items"]:
            low = str(item).lower()

            if ("contract value" in low or "price" in low) and _present(ai_json.get("contract_value")):
                continue

            if ("insurance limit" in low or "insurance coverage" in low) and _present(ai_json.get("insurance_requirements")):
                continue

            if "proposal validity" in low:
                if any("proposal validity" in str(x).lower() for x in ai_json.get("key_obligations", [])):
                    continue

            cleaned_missing.append(item)

        ai_json["missing_items"] = cleaned_missing

    summary = str(ai_json.get("summary_for_pm", ""))
    if _present(ai_json.get("contract_value")):
        summary = summary.replace("No price", "Price is stated")
        summary = summary.replace("no price", "price is stated")

    if _present(ai_json.get("insurance_requirements")):
        summary = summary.replace("No price or insurance limits are stated", "Price and insurance information are stated")
        summary = summary.replace("no price or insurance limits are stated", "price and insurance information are stated")
        summary = summary.replace("no insurance limits are stated", "insurance information is stated")
        summary = summary.replace("No insurance limits are stated", "Insurance information is stated")

    ai_json["summary_for_pm"] = summary

    return ai_json


@st.cache_data(show_spinner=False)
def compare_to_standard_cached(
    standard_json_str: str,
    candidate_json_str: str,
) -> Dict[str, Any]:
    client = get_openai_client()

    prompt = f"""
GENERAL CONTRACTOR STANDARD JSON:
{standard_json_str}

COMPARISON DOCUMENT JSON:
{candidate_json_str}

Comparison instructions:
- Compare by business meaning, not exact wording.
- Treat same project names with minor formatting differences as Match.
- If one side is generic boilerplate scope and the other is specific trade scope, mark scope_of_work as Different.
- If insurance limits are stated on the candidate side but are lower or less complete than the standard, mark insurance_requirements as Different, not Missing.
- If the candidate states price or base price, do not mark contract_value as Missing.
- If the standard value is weakly extracted, do not blame the candidate for that alone.
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": COMPARISON_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    raw = _extract_text_output(response)
    return _safe_json_load(raw)