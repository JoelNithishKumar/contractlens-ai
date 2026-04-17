from __future__ import annotations

import re
from typing import Any, Dict, List


def _normalize(value: Any) -> str:
    if value is None:
        return "not found"
    return str(value).strip().lower()


def _is_not_found(value: Any) -> bool:
    return _normalize(value) in {"not found", "", "none", "null"}


def _clean_display(value: Any) -> str:
    if value is None:
        return "Not found"
    text = str(value).strip()
    return text if text else "Not found"


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _is_close_match(a: str, b: str, threshold: float = 0.75) -> bool:
    a_tokens = _tokenize(a)
    b_tokens = _tokenize(b)

    if not a_tokens or not b_tokens:
        return False

    overlap = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    score = overlap / union if union else 0
    return score >= threshold


def _compare_field(field: str, std_val: str, cand_val: str) -> str:
    std_nf = _is_not_found(std_val)
    cand_nf = _is_not_found(cand_val)

    if not std_nf and cand_nf:
        return "Missing"

    if std_nf and cand_nf:
        return "Missing"

    if std_nf and not cand_nf:
        # Don't punish candidate just because standard extraction is weak
        return "Different"

    std_norm = _normalize(std_val)
    cand_norm = _normalize(cand_val)

    if field == "project_name":
        return "Match" if _is_close_match(std_norm, cand_norm, threshold=0.8) else "Different"

    if field == "scope_of_work":
        # Scope should be stricter than project name
        return "Match" if _is_close_match(std_norm, cand_norm, threshold=0.9) else "Different"

    if std_norm == cand_norm:
        return "Match"

    return "Different"


def simple_rule_compare(standard: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    differences: List[str] = []
    missing_items: List[str] = []
    matches: List[str] = []
    field_comparison: List[Dict[str, str]] = []

    fields_to_check = [
        "project_name",
        "scope_of_work",
        "contract_value",
        "pricing_structure",
        "payment_terms",
        "insurance_requirements",
        "change_order_process",
        "warranty_terms",
        "termination_clause",
    ]

    for field in fields_to_check:
        std_val = _clean_display(standard.get(field, "Not found"))
        cand_val = _clean_display(candidate.get(field, "Not found"))

        status = _compare_field(field, std_val, cand_val)

        if status == "Missing":
            missing_items.append(f"{field} missing or not clearly stated")
        elif status == "Match":
            matches.append(f"{field} aligns with standard")
        else:
            differences.append(f"{field} differs from standard")

        field_comparison.append(
            {
                "field": field,
                "standard_value": std_val,
                "candidate_value": cand_val,
                "status": status,
            }
        )

    # Additional business logic risk checks
    candidate_text = " ".join(
        [
            _clean_display(candidate.get("payment_terms")),
            _clean_display(candidate.get("insurance_requirements")),
            _clean_display(candidate.get("change_order_process")),
            _clean_display(candidate.get("warranty_terms")),
            " ".join(candidate.get("unusual_risk_flags", [])) if isinstance(candidate.get("unusual_risk_flags"), list) else "",
        ]
    ).lower()

    if "verbal authorization" in candidate_text and "change_order_process differs from standard" not in differences:
        differences.append("change_order_process differs from standard")

    if "one-year" in candidate_text and "warranty_terms differs from standard" not in differences:
        differences.append("warranty_terms differs from standard")

    if "supersede" in candidate_text or "supersedes" in candidate_text:
        differences.append("terms precedence differs from standard")

    # Deduplicate lists
    differences = list(dict.fromkeys(differences))
    missing_items = list(dict.fromkeys(missing_items))
    matches = list(dict.fromkeys(matches))

    risk_level = "Green"
    if len(differences) >= 2 or len(missing_items) >= 2:
        risk_level = "Yellow"
    if len(differences) >= 4 or "terms precedence differs from standard" in differences:
        risk_level = "Red"

    recommended_actions = []
    if missing_items:
        recommended_actions.append("Request missing contractual or compliance details.")
    if differences:
        recommended_actions.append("Review non-standard terms before approval.")
    if any("insurance_requirements" in item for item in missing_items + differences):
        recommended_actions.append("Verify insurance limits, endorsements, and compliance gaps.")
    if any("change_order_process" in item for item in differences):
        recommended_actions.append("Require written change-order approval language before authorizing extra work.")
    if any("warranty_terms" in item for item in differences):
        recommended_actions.append("Confirm warranty obligations and align duration with subcontract standard.")

    pm_summary = (
        f"Found {len(matches)} aligned fields, {len(differences)} differences, "
        f"and {len(missing_items)} missing or unclear items. Risk level: {risk_level}."
    )

    follow_up_email = (
        "Hello,\n\n"
        "Thank you for sending over the document. During our review, we identified a few items "
        "that need clarification or revision before we can proceed. Please review the noted differences "
        "and any missing items, and send back the updated information at your earliest convenience.\n\n"
        "Best regards,\n"
        "Project Team"
    )

    return {
        "matches": matches,
        "differences": differences,
        "missing_items": missing_items,
        "risk_level": risk_level,
        "recommended_actions": recommended_actions,
        "pm_summary": pm_summary,
        "field_comparison": field_comparison,
        "follow_up_email": follow_up_email,
    }