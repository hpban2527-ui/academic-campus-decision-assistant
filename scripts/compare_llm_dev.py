"""Replay recorded model replies, compare development outcomes and choose a policy."""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.devdata import dev_ids, get_post, load_split, non_test_ids
from sp1.evaluate import wilson
from sp1.evaluate_v2 import empty, legacy_fields, outcome
from sp1.extract_v2 import extract_v2
from sp1.hybrid import DECIDABLE_FIELDS, merge
from sp1.llm_v2 import PROMPT_VERSIONS, decide
from sp1.normalize import load_config, normalize


def load_gold():
    legacy = set(dev_ids(False))
    extra = set(dev_ids()) - legacy
    rows = []
    for entry in json.loads((ROOT / "data/gold/source_gold.json").read_bytes()):
        if entry["post_id"] in legacy:
            rows.append({"post_id": entry["post_id"], "record": legacy_fields(entry["activities"][0]),
                         "legacy": True, "group": "Gold v1"})
    for entry in json.loads((ROOT / "data/gold/dev_extra_gold_v2_TD.json").read_bytes()):
        if entry["post_id"] in extra and entry.get("labelled_at"):
            rows.append({"post_id": entry["post_id"], "record": entry["record"],
                         "legacy": False, "group": "Gold v2"})
    return rows


def load_outputs(directory, allowed_ids):
    models = defaultdict(dict)
    allowed = set(allowed_ids)
    paths = sorted(Path(directory).glob("*.jsonl"))
    if not paths:
        raise ValueError("No recorded model JSONL outputs found")
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("post_id") not in allowed:
                raise ValueError(f"Disallowed or unknown post at {path.name}:{number}")
            if row.get("prompt_versions") != PROMPT_VERSIONS:
                raise ValueError(f"Prompt version mismatch at {path.name}:{number}")
            model = row.get("model_id")
            if not isinstance(model, str) or not model:
                raise ValueError("Missing model_id")
            if row["post_id"] in models[model]:
                raise ValueError(f"Duplicate post for model {model}")
            if not isinstance(row.get("replies"), dict):
                raise ValueError("Missing replies object")
            models[model][row["post_id"]] = row
    return dict(models)


def seconds(row):
    value = row.get("seconds", 0)
    return sum(value.values()) if isinstance(value, dict) else value


def choose_model(scores):
    return sorted(scores, key=lambda model: (-scores[model]["correct"], scores[model]["fabricated"],
                                             scores[model]["seconds"], model))


def choose_policy(evidence):
    policy, counts = {}, {}
    for field in DECIDABLE_FIELDS:
        e = evidence.get(field, {})
        rules, llm = e.get("rules", {}), e.get("llm", {})
        n = sum(rules.values())
        rc, lc = rules.get("correct", 0), llm.get("correct", 0)
        safe = llm.get("fabricated", 0) <= rules.get("fabricated", 0)
        if n and lc >= rc + 2 and safe:
            setting = "llm"
        elif n and field in {"post_type", "mode"} and abs(lc - rc) < 2:
            setting = "agree_else_review"
        elif (n and e.get("wins", 0) > 0 and e.get("wins") == e.get("null_wins")
              and not e.get("null_losses", 0) and safe):
            setting = "llm_if_rules_null"
        else:
            setting = "rules"
        policy[field] = setting
        counts[field] = {"n": n, **e}
    policy["_evidence"] = counts
    return policy


def evaluate_models(models, gold, post_loader=get_post):
    """Require common complete labelled coverage. Unlabelled fields never earn model-selection credit."""
    required = {row["post_id"] for row in gold}
    for model, rows in models.items():
        if required - rows.keys():
            raise ValueError(f"Incomplete gold coverage for {model}: {len(required - rows.keys())} missing")
    rules = {pid: extract_v2(post_loader(pid)) for pid in sorted(required)}
    decisions, evaluations, diagnostics, scores, policies = {}, {}, {}, {}, {}
    for model, rows in models.items():
        decisions[model] = {pid: decide(post_loader(pid), rows[pid]["replies"]) for pid in sorted(required)}
        evidence = {field: {"rules": Counter(), "llm": Counter(), "wins": 0, "null_wins": 0,
                            "null_losses": 0} for field in DECIDABLE_FIELDS}
        counts = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
        validity, retries, errors = Counter(), Counter(), Counter()
        for pid, decision in decisions[model].items():
            for kind in PROMPT_VERSIONS:
                validity[kind] += decision[kind] is not None
                retries[kind] += decision["attempts"].get(kind, 0) > 1
            errors.update(error["code"] for error in decision["errors"])
        for entry in gold:
            pid = entry["post_id"]
            rule = rules[pid]["layer_a"]["record"]
            llm = merge(rules[pid], decisions[model][pid], dict.fromkeys(DECIDABLE_FIELDS, "llm"))["layer_a"]["record"]
            for field, target in entry["record"].items():
                statuses = {}
                for method, prediction in (("rules", rule), ("llm", llm)):
                    status = outcome(field, prediction.get(field), target, entry["legacy"])
                    counts[entry["group"]][method][field][status] += 1
                    statuses[method] = status
                    if field in evidence:
                        evidence[field][method][status] += 1
                if field in evidence:
                    e = evidence[field]
                    win = statuses["llm"] == "correct" and statuses["rules"] != "correct"
                    e["wins"] += win
                    e["null_wins"] += win and empty(rule.get(field))
                    e["null_losses"] += (empty(rule.get(field)) and statuses["rules"] == "correct"
                                          and statuses["llm"] != "correct")
        policies[model] = choose_policy(evidence)
        timings = [seconds(rows[pid]) for pid in sorted(required)]
        total = sum((e["llm"] for e in evidence.values()), Counter())
        scores[model] = {"correct": total["correct"], "fabricated": total["fabricated"],
                         "seconds": statistics.mean(timings) if timings else 0}
        diagnostics[model] = {"n": len(required), "validity": validity, "retries": retries,
                              "errors": errors, "mean_seconds": scores[model]["seconds"],
                              "max_seconds": max(timings, default=0),
                              "peak_vram_gb": max((rows[pid].get("peak_vram_gb", 0) for pid in required), default=0)}
        evaluations[model] = counts
    ranked = choose_model(scores)
    chosen = ranked[0]
    policy = policies[chosen]
    policy["_model_id"] = chosen
    policy["_prompt_versions"] = PROMPT_VERSIONS
    for entry in gold:
        pid = entry["post_id"]
        hybrid = merge(rules[pid], decisions[chosen][pid], policy)["layer_a"]["record"]
        for field, target in entry["record"].items():
            status = outcome(field, hybrid.get(field), target, entry["legacy"])
            evaluations[chosen][entry["group"]]["hybrid"][field][status] += 1
    return {"ranked": ranked, "scores": scores, "diagnostics": diagnostics,
            "evaluations": evaluations, "policy": policy}


def render_report(result):
    ranked = result["ranked"]
    lines = ["# SP1 LLM development comparison", "",
             "Small development samples (16 gold v1 + 5 completed gold v2 in the current corpus).",
             "These are dev results used for policy selection, not a held-out test evaluation.",
             "LLM-only means LLM on decidable fields with mandatory rules fallback on invalid/missing decisions.",
             "Unlabelled activity_type has n=0 and cannot influence model selection or policy.",
             "Retry rates count recorded second replies only. Single notebook replies cannot reveal hypothetical retry success.",
             "Wilson field-trial intervals do not account for correlated errors within posts.", "",
             f"Chosen model: {ranked[0]}. Runner-up: {ranked[1] if len(ranked) > 1 else 'none'}.",
             "Selection: total correct on decidable labelled fields, then fewer fabricated, then mean seconds/post.", ""]
    for model in ranked:
        d = result["diagnostics"][model]
        lines += [f"## {model}", "", f"Labelled posts: {d['n']}. Mean/max seconds per post: "
                  f"{d['mean_seconds']:.3f}/{d['max_seconds']:.3f}. Peak VRAM: {d['peak_vram_gb']:.3f} GiB.",
                  f"Selection counts: {result['scores'][model]}", ""]
        for kind in PROMPT_VERSIONS:
            n = d["n"]
            lines.append(f"{kind}: valid {d['validity'][kind]}/{n} ({d['validity'][kind] / n:.1%}); recorded retry "
                         f"{d['retries'][kind]}/{n} ({d['retries'][kind] / n:.1%}).")
        lines += [f"Error codes: {dict(d['errors'])}", ""]
        for group, methods in result["evaluations"][model].items():
            lines += [f"### {group}", "", "| Method | Field | n | Correct | Wrong | Fabricated | Missed | 95% Wilson |",
                      "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"]
            for method, fields in methods.items():
                for field, c in (*fields.items(), ("TOTAL", sum(fields.values(), Counter()))):
                    n = sum(c.values())
                    low, high = wilson(c["correct"], n)
                    lines.append(f"| {method} | {field} | {n} | {c['correct']} | {c['wrong']} | "
                                 f"{c['fabricated']} | {c['missed']} | {low:.1%}-{high:.1%} |")
            lines.append("")
    lines += ["## Measured policy", "", "```json", json.dumps(result["policy"], indent=2), "```", ""]
    return "\n".join(lines)


def readiness(models, policy):
    chosen = policy.get("_model_id")
    if not chosen or chosen not in models:
        raise ValueError("Readiness requires the chosen model from the measured dev policy")
    rows = models[chosen]
    ids = non_test_ids()
    if set(ids) != rows.keys():
        raise ValueError("Readiness requires every non-test post for the chosen model")
    config = load_config()
    metrics, reasons = {k: Counter() for k in ("rules", "hybrid")}, {k: Counter() for k in ("rules", "hybrid")}
    from datetime import date
    for pid in ids:
        post = get_post(pid)
        rule = extract_v2(post)
        hybrid = merge(rule, decide(post, rows[pid]["replies"]), policy)
        source = {key: post.get(key) for key in ("post_id", "publisher", "platform", "date_posted")}
        source["URL_post"] = post["url"]
        for method, output in (("rules", rule), ("hybrid", hybrid)):
            activity = normalize(output["layer_a"], source, config)
            start = activity["window"]["open"]
            day = date.fromisoformat(start[:10]) if start else None
            semester = next((key for left, right, key in config.semesters["standard"]
                             if day and left <= day <= right), "out_of_scope_semester" if day else "insufficient_data")
            fails = [key for key, fail in (("post_type", activity["post_type"] != "activity"),
                     ("window_open", not start), ("mode", activity["mode"] is None),
                     ("semester", semester in {"out_of_scope_semester", "insufficient_data"}),
                     ("failed_status", activity["meta"]["status"] == "failed")) if fail]
            reasons[method].update(fails)
            m = metrics[method]
            m["plannable"] += not fails
            m["window_open"] += bool(start)
            m["mode"] += activity["mode"] is not None
            m["registration_deadline"] += activity["registration_deadline"] is not None
            m["offline"] += activity["mode"] == "offline"
            m["offline_location"] += activity["mode"] == "offline" and activity["location"] is not None
            m[f"post_type:{activity['post_type']}"] += 1
            m[f"status:{activity['meta']['status']}"] += 1
            m[f"semester:{semester}"] += 1
            m[f"activity_type:{output['classification']['activity_type']}"] += 1
    lines = ["# SP1 hybrid non-test readiness", "", f"Model: {chosen}. Posts: {len(ids)}.",
             "Structural readiness, not gold accuracy. Reasons may overlap.", "",
             "| Metric | Rules count/n | Hybrid count/n |", "| --- | ---: | ---: |"]
    for key in sorted(metrics["rules"].keys() | metrics["hybrid"].keys()):
        cells = []
        for method in metrics:
            denominator = metrics[method]["offline"] if key == "offline_location" else len(ids)
            cells.append(f"{metrics[method][key]}/{denominator}")
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    lines += ["", "| Method | Exclusion reason | Posts |", "| --- | --- | ---: |"]
    for method, counts in reasons.items():
        lines.extend(f"| {method} | {reason} | {n} |" for reason, n in sorted(counts.items()))
    return "\n".join(lines) + "\n"


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--write-policy", type=Path)
    parser.add_argument("--policy", type=Path, default=ROOT / "data/config/merge_policy.json")
    parser.add_argument("--readiness", action="store_true")
    args = parser.parse_args(argv)
    models = load_outputs(args.outputs, non_test_ids() if args.readiness else dev_ids())
    if args.readiness:
        policy = json.loads(args.policy.read_bytes())
        report = readiness(models, policy)
        path = args.report or ROOT / "reports/sp1_hybrid_readiness_non_test.md"
    else:
        result = evaluate_models(models, load_gold())
        report = render_report(result)
        path = args.report or ROOT / "reports/sp1_llm_dev_compare.md"
        if args.write_policy:
            write(args.write_policy, json.dumps(result["policy"], indent=2) + "\n")
        print(f"Chosen model: {result['ranked'][0]}")
    write(path, report)
    print(f"Report written: {path}")


if __name__ == "__main__":
    main()
