"""Explicit per-field arbitration, with rules retained on unavailable LLM values."""

from copy import deepcopy

DECIDABLE_FIELDS = (
    "post_type", "activity_type", "domain", "mode", "title", "multi_session",
    "window_open", "window_close", "registration_deadline", "registration_url", "join_url",
)
POLICIES = {"rules", "llm", "llm_if_rules_null", "agree_else_review"}


def merge(rules_out: dict, llm_decision: dict | None, policy: dict) -> dict:
    output = deepcopy(rules_out)
    output["method"] = "hybrid_v2"
    output["field_methods"] = dict.fromkeys((*output["layer_a"]["record"], "activity_type"), "rules")
    layer = output["layer_a"]
    values = (llm_decision or {}).get("values", {})
    record = values.get("record", {})
    selected = set()
    for field in DECIDABLE_FIELDS:
        setting = policy.get(field, "rules")
        setting = setting.get("policy", "rules") if isinstance(setting, dict) else setting
        if setting not in POLICIES:
            raise ValueError(f"Invalid policy for {field}: {setting}")
        if setting == "rules":
            continue
        target = output["classification"] if field == "activity_type" else layer["record"]
        old = target.get(field)
        if field not in record:
            output["field_methods"][field] = "rules_fallback"
            continue
        new = record[field]
        if field == "mode" and not (llm_decision or {}).get("classify", {}).get("mode_evidence"):
            new = None
        if setting == "agree_else_review":
            if new == old:
                output["field_methods"][field] = "agree"
            else:
                layer["flags"].append(f"needs_review:{field}")
            continue
        if setting == "llm_if_rules_null" and old is not None:
            continue
        target[field] = deepcopy(new)
        output["field_methods"][field] = "llm"
        selected.add(field)
        if field == "activity_type":
            target["evidence"] = deepcopy(values.get("evidence", {}).get(field, []))
        else:
            layer["evidence"][field] = deepcopy(values.get("evidence", {}).get(field, []))
            layer["year_inferred"] = [key for key in layer["year_inferred"] if key != field]
            if field in values.get("year_inferred", []):
                layer["year_inferred"].append(field)
    for flag in values.get("flags", []):
        if not flag.startswith("needs_review:") or flag.split(":", 1)[1] in selected:
            layer["flags"].append(flag)
    # Opening and closing must come from the same schedule mention. When the opening was taken
    # from the LLM on a different day than the rules found, a rules closing came from another
    # line, so the closing follows the LLM as well (possibly null).
    rules_open = rules_out["layer_a"]["record"].get("window_open")
    if ("window_open" in selected and "window_close" not in selected and "window_close" in record
            and (rules_open or "")[:10] != (layer["record"].get("window_open") or "")[:10]):
        layer["record"]["window_close"] = deepcopy(record["window_close"])
        layer["evidence"]["window_close"] = deepcopy(values.get("evidence", {}).get("window_close", []))
        layer["year_inferred"] = [key for key in layer["year_inferred"] if key != "window_close"]
        if "window_close" in values.get("year_inferred", []):
            layer["year_inferred"].append("window_close")
        output["field_methods"]["window_close"] = "llm_consistency"
    # Keep rule-only fields intact, but surface cross-field disagreement to the normalizer/reviewer.
    if layer["record"].get("mode") == "online" and layer["record"].get("location"):
        layer["flags"].append("needs_review:location")
    left, right = layer["record"].get("window_open"), layer["record"].get("window_close")
    if left and right and right[:10] < left[:10]:
        layer["flags"].append("needs_review:window_close")
    layer["flags"] = list(dict.fromkeys(layer["flags"]))
    return output
