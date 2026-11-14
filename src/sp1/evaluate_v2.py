"""Reproducible development evaluation against independently versioned gold."""

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from .devdata import dev_ids, get_post, load_split
from .extract_v2 import extract_v2, FIELDS
from .extractor import extract_post
from .evaluate import wilson
from .preprocess import preprocess
from .regex_baseline import strip_scheme

ROOT = Path(__file__).resolve().parents[2]
MAPPING = {
    "title": "title", "start": "window_open", "end": "window_close",
    "registration_deadline": "registration_deadline", "mode": "mode", "location": "location",
    "fee": "fee", "URL_registration": "registration_url", "mandatory": "mandatory_stated", "domain": "domain",
}


def canonical(value):
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold().strip(' "\'“”.,;:')


def empty(value):
    return value is None or value == "" or value == [] or value == {} or value == {"cohorts": [], "programs": []}


def equal(field, predicted, gold, legacy=False):
    if empty(predicted) or empty(gold):
        return empty(predicted) and empty(gold)
    if field in ("window_open", "window_close", "registration_deadline"):
        precision = 10 if len(gold) == 10 else 16
        if legacy and (gold[10:] in ("T00:00:00+07:00", "T23:59:00+07:00")):
            precision = 10
        return predicted[:precision] == gold[:precision]
    if field == "audience_scope":
        return all(set(predicted.get(key, [])) == set(gold.get(key, [])) for key in ("cohorts", "programs"))
    if field == "completion_requirements":
        def items(values):
            return Counter((v["type"], v["threshold"], v["unit"]) for v in values)
        return items(predicted) == items(gold)
    if field == "fee":
        if legacy and isinstance(gold, (int, float)) and isinstance(predicted, dict):
            return predicted["amount_vnd"] == gold
        return predicted == gold and type(predicted) is type(gold)
    if legacy and field == "registration_url":
        return strip_scheme(predicted) == strip_scheme(gold)
    if isinstance(predicted, str) and isinstance(gold, str):
        return canonical(predicted) == canonical(gold)
    if isinstance(predicted, bool) != isinstance(gold, bool):
        return False
    return predicted == gold


def outcome(field, predicted, gold, legacy=False):
    if equal(field, predicted, gold, legacy):
        return "correct"
    if empty(gold):
        return "fabricated"
    if empty(predicted):
        return "missed"
    return "wrong"


def legacy_fields(record):
    result = {target: record.get(source) for source, target in MAPPING.items()}
    result["registration_url"] = record.get("source", {}).get("URL_registration")
    return result


def safe_value(value):
    text = json.dumps(value, ensure_ascii=False)
    text = preprocess(text).text
    # The old N0 phone regex excludes parenthesised area codes.
    text = re.sub(r"\(\d{2,3}\)[ .-]*\d(?:[ .-]?\d){6,8}", "[phone removed]", text)
    return text[:80].replace("|", r"\|").replace("\n", " ")


def evaluate_dev():
    positions = {row["post_id"]: row["position"] for row in load_split()["posts"]}
    legacy_ids = set(dev_ids(False))
    allowed = set(dev_ids()) - legacy_ids
    gold_v1 = [row for row in json.loads((ROOT / "data/gold/source_gold.json").read_bytes())
               if row["post_id"] in legacy_ids]
    gold_v2 = [row for row in json.loads((ROOT / "data/gold/dev_extra_gold_v2_TD.json").read_bytes())
               if row["post_id"] in allowed and row.get("labelled_at")]
    results = []
    for label, gold, methods, legacy in (
        ("Gold v1", gold_v1, ("v1", "v2"), True), ("Gold v2", gold_v2, ("v2",), False),
    ):
        fields = list(MAPPING.values()) if legacy else list(FIELDS)
        counts = {method: {field: Counter() for field in fields} for method in methods}
        errors = []
        for entry in gold:
            post = get_post(entry["post_id"])
            expected = legacy_fields(entry["activities"][0]) if legacy else entry["record"]
            predictions = {"v2": extract_v2(post)["layer_a"]["record"]}
            if legacy:
                predictions["v1"] = legacy_fields(extract_post(post)["drafts"][0]["record"])
            for method in methods:
                for field in fields:
                    if not legacy and field not in expected:
                        continue
                    predicted, target = predictions[method].get(field), expected.get(field)
                    status = outcome(field, predicted, target, legacy)
                    counts[method][field][status] += 1
                    if status != "correct":
                        errors.append((positions[entry["post_id"]], method, field, status, predicted, target))
        results.append((label, len(gold), counts, errors))
    return results


def render_report(results):
    lines = ["# SP1 v2 development evaluation", "",
             "These are development results on small samples. Held-out test evaluation remains pending.", ""]
    for label, size, methods, errors in results:
        lines.extend([f"## {label} ({size} posts)", "",
                      "| Method | Field | n | Correct | Wrong | Fabricated | Missed | Accuracy | 95% Wilson |",
                      "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"])
        for method, fields in methods.items():
            total = sum(fields.values(), Counter())
            for field, counts in (*fields.items(), ("TOTAL", total)):
                n = sum(counts.values())
                correct = counts["correct"]
                low, high = wilson(correct, n)
                accuracy = f"{correct / n:.1%}" if n else "n/a"
                lines.append(f"| {method} | {field} | {n} | {correct} | {counts['wrong']} | "
                             f"{counts['fabricated']} | {counts['missed']} | {accuracy} | {low:.1%}–{high:.1%} |")
        lines.extend(["", "| Position | Method | Field | Outcome | Predicted | Gold |",
                      "| ---: | --- | --- | --- | --- | --- |"])
        lines.extend(f"| {pos} | {method} | {field} | {status} | {safe_value(pred)} | {safe_value(gold)} |"
                     for pos, method, field, status, pred, gold in errors)
        lines.append("")
    return "\n".join(lines)


def main():
    report = render_report(evaluate_dev())
    (ROOT / "reports/sp1_v2_dev_eval.md").write_bytes((report + "\n").encode("utf-8"))
    print("Development evaluation written.")


if __name__ == "__main__":
    main()
