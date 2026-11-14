"""Produce aggregate readiness and redacted outputs for the non-test corpus."""

import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.devdata import non_test_ids, get_post
from sp1.extract_v2 import run_pipeline
from sp1.extractor import extract_post
from sp1.normalize import load_config
from sp1.preprocess import preprocess, original_span


def redact(value):
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        pre = preprocess(value)
        for start, end, _ in reversed(pre.masked):
            left, right = original_span(pre, start, end)
            value = value[:left] + "[phone removed]" + value[right:]
        return re.sub(r"\(\d{2,3}\)[ .-]*\d(?:[ .-]?\d){6,8}", "[phone removed]", value)
    return value


def main():
    config = load_config()
    outputs = []
    metrics = {"v1": Counter(), "v2": Counter()}
    reasons = {"v1": Counter(), "v2": Counter()}
    for post_id in non_test_ids():
        post = get_post(post_id)
        output = run_pipeline(post, config)
        outputs.append(output)
        old = extract_post(post)["drafts"][0]
        old_record = old["record"]
        activity = output["activity"]
        for method, record, start, status, kind in (
            ("v2", activity, activity["window"]["open"], activity["meta"]["status"], activity["post_type"]),
            ("v1", old_record, old_record["start"], old["meta"]["status"],
             "activity" if old_record["drl_recognized"] is True else "unclassified"),
        ):
            day = date.fromisoformat(start[:10]) if start else None
            semester = next((key for left, right, key in config.semesters["standard"]
                             if day and left <= day <= right), "out_of_scope_semester" if day else "insufficient_data")
            failures = []
            for reason, fails in (("post_type", kind != "activity"), ("window_open", not start),
                                  ("mode", record["mode"] is None),
                                  ("semester", semester in ("insufficient_data", "out_of_scope_semester")),
                                  ("failed_status", status == "failed")):
                if fails:
                    failures.append(reason)
            reasons[method].update(failures)
            metric = metrics[method]
            metric["plannable"] += not failures
            metric["window_open"] += bool(start)
            metric["mode"] += record["mode"] is not None
            metric["registration_deadline"] += record["registration_deadline"] is not None
            metric["offline"] += record["mode"] == "offline"
            metric["offline_location"] += record["mode"] == "offline" and record["location"] is not None
            metric[f"post_type:{kind}"] += 1
            metric[f"status:{status}"] += 1
            metric[f"semester:{semester}"] += 1
        metrics["v2"][f"activity_type:{output['extraction']['classification']['activity_type']}"] += 1
    n = len(outputs)
    lines = ["# SP1 non-test readiness", "", f"Corpus size is {n} non-test posts.",
             "V1 has no post_type or activity_type. Its participation proxy is drl_recognized=true.",
             "Both versions use the same configured semester bounds and plannability conditions.",
             "Persisted evidence retains original offsets. Evidence text is phone-redacted on export.",
             "The in-memory extraction retains exact original evidence slices.", "",
             "| Metric | v1 count / denominator | v1 share | v2 count / denominator | v2 share |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for key in sorted(metrics["v1"].keys() | metrics["v2"].keys()):
        cells = []
        for method in ("v1", "v2"):
            if key.startswith("activity_type:") and method == "v1":
                cells.extend(("n/a", "n/a"))
                continue
            denominator = metrics[method]["offline"] if key == "offline_location" else n
            count = metrics[method][key]
            cells.extend((f"{count} / {denominator}", f"{count / denominator:.1%}" if denominator else "n/a"))
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    lines.extend(["", "## Reasons excluding a post", "", "Reasons may overlap.", "",
                  "| Method | Reason | Posts |", "| --- | --- | ---: |"])
    for method in ("v1", "v2"):
        lines.extend(f"| {method} | {reason} | {count} |" for reason, count in reasons[method].most_common())
    (ROOT / "reports/sp1_v2_readiness_non_test.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    (ROOT / "reports/sp1_v2_non_test_output.json").write_bytes(
        (json.dumps(redact(outputs), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(f"Readiness written for {n} non-test posts.")


if __name__ == "__main__":
    main()
