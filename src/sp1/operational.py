"""Build the operational activity dataset that the running application reads (SP1 -> SP2 -> SP3 input).

One deterministic build accounts for every announcement of the operational corpus (the frozen 189 posts
plus admin updates, see sp1.operational_corpus) and writes a single versioned file,
data/operational/activity_dataset.json. The API and the planner read only that file.

Per post:

1. Extraction source, first match wins, each bound to the current text fingerprint:
   a. a genuinely human-reviewed export of the AI-assisted review (data/sp1_annotations/human_reviewed/),
   b. the AI-assisted annotation of 2026-11-18 (non-test posts only, data/sp1_annotations/),
   c. a recorded SP1 v2 model reply (Qwen/Qwen3.5-4B) whose prompt digest matches the current prompts,
      replayed through the rules + hybrid merge,
   d. otherwise EXTRACTION_PENDING: no record is invented; the post is listed with the reason.
   Held-out test posts never use (a)/(b); they use only frozen model outputs (c) under the access log.
2. Genuine human decisions from data/review/decisions.csv are applied last (same fingerprint rule).
3. The user-agreed acceptance policy (sp1.acceptance, activity-acceptance/1.x) decides data readiness
   and the schedule. Missing organizer facts stay null; nothing is defaulted into a time, deadline,
   cost or point value. Team defaults (end = start + 120/30 minutes) are labelled as assumptions.
4. Duplicates of the same activity are merged; members keep their sources as aliases.
5. SP2 binding (rule matcher + activity-type agreement, or a reviewed rule) and personalization
   features are computed for data-ready canonical activities only.
6. The SP3 activity (contract sp3-activity/0.3: nullable fee, no invented deadline) and the schedule
   evidence are produced for data-ready canonical activities.

Data readiness, student eligibility, score binding, human approval and official recognition are kept
as separate dimensions. Nothing here is gold or an official DRL decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from . import audience as audience_rules
from .acceptance import assess_activity, load_policy
from .activity_type import KEYWORDS
from .dedup_v2 import group_duplicates
from .devdata import ROOT
from .extract_v2 import FIELDS, extract_v2
from .features import features as feature_values
from .hybrid import merge
from .llm_cache import load_replies, lookup, prompts_for
from .llm_v2 import PROMPT_VERSIONS, decide
from .normalize import load_config, normalize
from .pipeline_v2 import post_source, redact as _redact_text
from .preprocess import preprocess
from .review import apply_decision, text_fingerprint

DATASET_SCHEMA = "unilife-operational-dataset/1.0"
ACTIVITY_CONTRACT = "sp3-activity/0.3"
DATASET_PATH = ROOT / "data/operational/activity_dataset.json"
ANNOTATIONS_PATH = ROOT / "data/sp1_annotations/ai_annotations_20261118.json"
HUMAN_REVIEWED_DIR = ROOT / "data/sp1_annotations/human_reviewed"
DECISIONS_PATH = ROOT / "data/review/decisions.csv"
MERGE_POLICY_PATH = ROOT / "data/config/merge_policy.json"
RULES_PATH = ROOT / "data/drl_rules.json"
LLM_DIRS = (ROOT / "data/llm_outputs/final", ROOT / "data/llm_outputs/operational")

AI_LABEL = "AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD"
MODEL_LABEL = "MODEL_EXTRACTED_POLICY_CHECKED_NOT_GOLD"
HUMAN_EXPORT_LABEL = "HUMAN_REVIEWED_AI_ASSISTED_NOT_BLIND_GOLD"
READY_STATUSES = {"READY", "READY_WITH_WARNINGS"}
STATUSES = ("READY", "READY_WITH_WARNINGS", "NOT_SCHEDULABLE", "NOT_AN_ACTIVITY", "DUPLICATE", "EXTRACTION_PENDING")
SP3_FIELDS = ("activity_id", "source", "title", "domain", "start", "end", "registration_deadline", "mode",
              "location", "points", "mandatory", "audience", "fee", "completion_requirements")
DOMAINS = {"academic", "volunteer", "culture_sports", "skills", "career", "other"}
NOT_STATED = "NOT_STATED"
# Layer-A flags that make a field uncertain (the model or the rules could not settle it).
_UNSURE_FLAG = re.compile(r"^(?:needs_review|invalid_value):(\w+)")
_BLOCKING_FLAG = re.compile(r"^(?:injection_suspected|candidates_truncated)")
ACTIVITY_TYPES = {(k[0] if isinstance(k, tuple) else k) for k in KEYWORDS} | {"other"}


# Identifiers, hashes and links are not free text: masking a digit run inside them would corrupt them.
_KEEP_KEYS = re.compile(r"(sha256|_id$|^post_id$|^url$|^share_url$|^URL_|_url$|^binding_ref$|^duplicate_of$|"
                        r"^packet_id$|^dataset_version$|^file$|^field$)")


def redact(value, key: str = ""):
    """Mask phone and account numbers in free text only (see sp1.pipeline_v2.redact)."""
    if isinstance(value, dict):
        return {k: (v if _KEEP_KEYS.search(k) else redact(v, k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if isinstance(value, str) and not value.startswith(("http://", "https://")):
        return _redact_text(value)
    return value


def sha256_file(path: Path) -> str | None:
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _http(value) -> bool:
    return isinstance(value, str) and re.match(r"^https?://[^\s/]+", value) is not None


# ---------------------------------------------------------------- inputs

def load_annotations(path: Path | None = None) -> dict:
    path = ANNOTATIONS_PATH if path is None else Path(path)
    if not path.exists():
        return {"packet_id": None, "items": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "unilife-ai-annotations/1.0" or data.get("label") != AI_LABEL:
        raise ValueError(f"{path.name}: not an AI annotation file with label {AI_LABEL}")
    items = {}
    for item in data["items"]:
        if item.get("split") == "test":
            raise ValueError(f"{path.name}: test post {item['post_id']} must not have an AI annotation")
        items[item["post_id"]] = item
    return {"packet_id": data.get("packet_id"), "items": items, "sha256": sha256_file(path)}


def load_human_reviewed(directory: Path | None = None) -> dict:
    """Validated human-approved exports of the AI-assisted review viewer, keyed by post_id."""
    directory = HUMAN_REVIEWED_DIR if directory is None else Path(directory)
    rows = {}
    if not directory.exists():
        return rows
    import importlib.util
    spec = importlib.util.spec_from_file_location("validate_ai_review_export", ROOT / "scripts/validate_ai_review_export.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for path in sorted(directory.glob("*.json")):
        module.validate_export(path)          # raises on anything that is not a complete human approval
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        for row in data["items"]:
            if row["post_id"] in rows:
                raise ValueError(f"{path.name}: post {row['post_id']} is approved in two export files")
            rows[row["post_id"]] = {**row, "_file": path.name}
    return rows


def default_llm_files() -> list[Path]:
    files = []
    for directory in LLM_DIRS:
        if directory.exists():
            files += sorted(directory.glob("*.jsonl"))
    return files


# ---------------------------------------------------------------- per post

def _layer_a_from_annotation(item: dict) -> tuple[dict, str | None, list[str]]:
    record = deepcopy(item["record"])
    activity_type = record.pop("activity_type", None)
    layer_a = {"record": record, "year_inferred": list(item.get("year_inferred", [])), "flags": [],
               "evidence": deepcopy(item.get("evidence_spans", {}))}
    return layer_a, activity_type, sorted(set(item.get("unsure", [])))


def _grounding_problems(layer_a: dict, text: str, skip=("activity_type",)) -> list[str]:
    """Fields whose value has no evidence span, or whose span text is not at its offsets in the text."""
    problems = []
    for field, value in layer_a["record"].items():
        if field in skip or value in (None, [], "", False) or value == {"cohorts": [], "programs": []}:
            continue
        spans = layer_a["evidence"].get(field) or []
        if not spans or any(text[s["start"]:s["end"]] != s["text"] for s in spans):
            problems.append(field)
    return problems


def _extract(post: dict, ctx: dict) -> dict:
    """Choose the extraction source. Returns layer_a (or None), activity_type, unsure, method and notes."""
    pid, fingerprint = post["post_id"], text_fingerprint(post["raw_content"])
    notes, is_test = [], post["split"] == "test"
    human = ctx["human_reviewed"].get(pid)
    if human is not None and not is_test:
        if human["source_sha256"] == fingerprint:
            layer_a, activity_type, _ = _layer_a_from_annotation(human)
            return {"layer_a": layer_a, "activity_type": activity_type, "unsure": [], "state": "EXTRACTED",
                    "method": "human_reviewed_ai_assisted", "label": HUMAN_EXPORT_LABEL,
                    "provenance": {"file": human["_file"], "reviewer": human["review"]["reviewer"],
                                   "reviewed_at": human["review"]["reviewed_at"]}, "notes": notes}
        notes.append("human_reviewed_export_stale")
    item = ctx["annotations"]["items"].get(pid)
    if item is not None and not is_test:
        if item["source_sha256"] == fingerprint:
            layer_a, activity_type, unsure = _layer_a_from_annotation(item)
            return {"layer_a": layer_a, "activity_type": activity_type, "unsure": unsure, "state": "EXTRACTED",
                    "method": "ai_annotation", "label": AI_LABEL,
                    "provenance": {"packet_id": ctx["annotations"]["packet_id"],
                                   "annotation_sha256": ctx["annotations"]["sha256"],
                                   "ai_crosscheck_changed_fields": item.get("changed_fields", [])},
                    "notes": notes}
        notes.append("ai_annotation_stale")
    prompts = prompts_for(post)
    row, state, digest = lookup(ctx["replies"], post, prompts)
    provenance = {"model_id": ctx["model_id"], "prompt_versions": dict(PROMPT_VERSIONS), "input_sha256": digest}
    if row is None:
        reason = "model_output_stale" if state == "stale" else "model_output_missing"
        return {"layer_a": None, "activity_type": None, "unsure": [], "state": "EXTRACTION_PENDING",
                "method": None, "label": None, "provenance": provenance, "notes": notes, "pending_reason": reason,
                "prompts": prompts}
    decision = decide(post, row["replies"])
    hybrid = merge(extract_v2(post), decision, ctx["merge_policy"])
    layer_a = hybrid["layer_a"]
    unsure = sorted({m.group(1) for flag in layer_a["flags"] if (m := _UNSURE_FLAG.match(flag))})
    if decision["errors"]:
        notes.append("model_reply_partly_unusable")
    provenance.update(file=row["_file"], field_methods=hybrid.get("field_methods", {}),
                      reply_errors=decision["errors"])
    return {"layer_a": layer_a, "activity_type": hybrid["classification"]["activity_type"], "unsure": unsure,
            "state": "EXTRACTED", "method": "sp1_v2_model_replay", "label": MODEL_LABEL,
            "provenance": provenance, "notes": notes}


def _fee(fee) -> tuple[int | float | None, str]:
    """(per-person amount for budget checks, or None; basis)."""
    if fee is None:
        return None, "unknown"
    if isinstance(fee, bool):
        return None, "invalid"
    if isinstance(fee, (int, float)):
        return fee, "stated"
    if isinstance(fee, dict):
        if fee.get("per") == "person" and not fee.get("deposit") and isinstance(fee.get("amount_vnd"), (int, float)):
            return fee["amount_vnd"], "stated_per_person"
        return None, "not_per_person_or_deposit"
    return None, "invalid"


def project_sp3(post: dict, accepted: dict, schedule: dict, normalized: dict, audience: dict) -> tuple[dict, dict]:
    """The 14-field SP3 activity (sp3-activity/0.3) and the labelled conventions used to build it."""
    derived = {}
    if schedule["type"] == "FIXED":
        start, end = schedule["start"], schedule["end"]
        if schedule["duration_source"] == "team_default":
            derived["end"] = "team_default:start_plus_default_duration"
    else:
        start, end = schedule["window_start"], schedule["window_end"]
        derived["start_end"] = "flexible_window_bounds"
    deadline = normalized["registration_deadline"] if accepted.get("registration_deadline") else None
    if deadline and "registration_deadline" in normalized["meta"]["time_defaults"]:
        derived["registration_deadline"] = "rule:date_only_end_of_day"
    fee, fee_basis = _fee(accepted.get("fee"))
    if fee_basis != "stated":
        derived["fee"] = f"budget_basis:{fee_basis}"
    mandatory = accepted.get("mandatory_stated") is True
    if accepted.get("mandatory_stated") is None:
        derived["mandatory"] = "team_default:mandatory_false_when_unstated"
    registration_url = accepted.get("registration_url")
    completion = accepted.get("completion_requirements") or []
    if not completion:
        derived["completion_requirements"] = "marker:not_stated"
    domain = accepted.get("domain")
    activity = {
        "activity_id": post["post_id"],
        "source": {"publisher": post["publisher"], "platform": post["platform"], "URL_post": post["url"],
                   "URL_registration": registration_url if _http(registration_url) else None},
        "title": accepted["title"],
        "domain": domain if domain in DOMAINS else None,
        "start": start, "end": end, "registration_deadline": deadline,
        "mode": accepted["mode"],
        "location": None if accepted["mode"] == "online" else accepted.get("location"),
        "points": accepted.get("points_stated") if isinstance(accepted.get("points_stated"), (int, float)) else None,
        "mandatory": mandatory,
        "audience": audience["lines"] or None,
        "fee": fee,
        "completion_requirements": json.dumps(completion, ensure_ascii=False, sort_keys=True) if completion else NOT_STATED,
    }
    return activity, derived


def sp3_contract_problems(activity: dict) -> list[str]:
    """Validator for sp3-activity/0.3 (the v0.2 contract with a nullable fee)."""
    problems = []
    if tuple(sorted(activity)) != tuple(sorted(SP3_FIELDS)):
        return ["fields"]
    source = activity["source"]
    if set(source) != {"publisher", "platform", "URL_post", "URL_registration"}:
        return ["source.fields"]
    for key in ("publisher", "platform"):
        if not isinstance(source[key], str) or not source[key].strip():
            problems.append("source." + key)
    if not _http(source["URL_post"]):
        problems.append("source.URL_post")
    if source["URL_registration"] is not None and not _http(source["URL_registration"]):
        problems.append("source.URL_registration")
    for key in ("activity_id", "title", "completion_requirements"):
        if not isinstance(activity[key], str) or not activity[key].strip():
            problems.append(key)
    for key in ("start", "end", "registration_deadline"):
        value = activity[key]
        if value is None and key != "registration_deadline":
            problems.append(key)
        elif value is not None:
            try:
                if datetime.fromisoformat(value).utcoffset() is None:
                    problems.append(key)
            except (TypeError, ValueError):
                problems.append(key)
    if activity["start"] and activity["end"] and not problems and activity["end"] <= activity["start"]:
        problems.append("end_before_start")
    if activity["mode"] not in {"online", "offline", "hybrid"}:
        problems.append("mode")
    if activity["mode"] == "online" and activity["location"] is not None:
        problems.append("location")
    for key in ("points", "fee"):
        value = activity[key]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            problems.append(key)
    if not isinstance(activity["mandatory"], bool):
        problems.append("mandatory")
    if activity["audience"] is not None and not all(isinstance(x, str) for x in activity["audience"]):
        problems.append("audience")
    return problems


def sp3_schedule_evidence(schedule: dict) -> dict:
    if schedule["type"] == "FIXED":
        return {"type": "FIXED", "fixed_blocks": [{"start": schedule["start"], "end": schedule["end"]}]}
    return {"type": "FLEXIBLE_WINDOW", "duration_minutes": schedule["duration_minutes"]}


def process_post(post: dict, ctx: dict) -> dict:
    pid = post["post_id"]
    raw = post["raw_content"]
    fingerprint = text_fingerprint(raw)
    pre = preprocess(raw)
    extraction = _extract(post, ctx)
    base = {
        "post_id": pid, "position": post["position"], "split": post["split"], "corpus": post["corpus"],
        "revision": post.get("revision"),
        "source": {"publisher": post["publisher"], "platform": post["platform"], "url": post["url"],
                   "share_url": post.get("share_url"), "date_posted": post.get("date_posted"),
                   "text_sha256": fingerprint},
        "extraction": {k: extraction[k] for k in ("state", "method", "label", "provenance", "notes")},
        "human_decision": None, "duplicate_of": None, "aliases": [], "possible_duplicates": [],
        "activity_type": None, "acceptance": None, "audience": None, "normalized": None,
        "sp3_activity": None, "sp3_derived": None, "sp3_schedule": None,
        "binding": None, "binding_decision": None, "features": None,
    }
    if extraction["state"] == "EXTRACTION_PENDING":
        base.update(status="EXTRACTION_PENDING", ready_for_scheduling=False,
                    reasons=[extraction["pending_reason"]], warnings=[])
        base["extraction"]["pending_reason"] = extraction["pending_reason"]
        base["dimensions"] = _dimensions(base)
        return base

    layer_a, activity_type, unsure = extraction["layer_a"], extraction["activity_type"], set(extraction["unsure"])
    blocking = {flag.split(":")[0] for flag in layer_a["flags"] if _BLOCKING_FLAG.match(flag)}
    if any(flag.startswith("injection_suspected") for flag in pre.flags):
        blocking.add("injection_suspected")
    if extraction["method"] in ("ai_annotation", "human_reviewed_ai_assisted"):
        for field in _grounding_problems(layer_a, pre.text):
            unsure.add(field)
            extraction["notes"].append(f"evidence_not_grounded:{field}")
    review = apply_decision(layer_a, ctx["decisions"].get(pid), raw)
    if review and not review["stale"]:
        unsure -= set(review["fields_set"])
        if review["activity_type"]:
            activity_type = review["activity_type"]
    base["human_decision"] = review
    if activity_type not in ACTIVITY_TYPES:
        activity_type = None
    row = {"record": {**layer_a["record"], "activity_type": activity_type}, "unsure": sorted(unsure),
           "source_text": pre.text, "review": {}}
    assessed = assess_activity(row, ctx["policy"])
    reasons, warnings = list(assessed["reasons"]), list(assessed["warnings"])
    if blocking:
        reasons = list(dict.fromkeys(reasons + sorted(blocking)))
    accepted = assessed["accepted_record"]
    activity_type = accepted.get("activity_type")
    base["activity_type"] = activity_type
    accepted_layer = {"record": {k: v for k, v in accepted.items() if k != "activity_type"},
                      "year_inferred": layer_a["year_inferred"], "flags": [], "evidence": layer_a["evidence"]}
    normalized = normalize(accepted_layer, post_source(post), ctx["config"])
    aud = audience_rules.classify(accepted.get("audience_text"), accepted.get("audience_scope"))
    base["audience"] = {**aud, "cohorts": (accepted.get("audience_scope") or {}).get("cohorts", []),
                        "programs": (accepted.get("audience_scope") or {}).get("programs", [])}
    if aud["basis"] == audience_rules.BASIS_NOT_STATED:
        warnings.append("audience_not_stated")
    elif aud["basis"] in (audience_rules.BASIS_FREE_TEXT, audience_rules.BASIS_UNCLEAR):
        warnings.append("audience_restriction_unresolved")
    if activity_type is None:
        warnings.append("activity_type_unknown")
    schedule = assessed["schedule"] if not reasons else None
    status = assessed["status"]
    if reasons and status in READY_STATUSES:
        status = "NOT_SCHEDULABLE"
    if status in READY_STATUSES:
        status = "READY_WITH_WARNINGS" if warnings else "READY"
    base.update(
        status=status, ready_for_scheduling=status in READY_STATUSES, reasons=reasons,
        warnings=list(dict.fromkeys(warnings)),
        acceptance={"policy_version": assessed["policy_version"], "schedule": schedule,
                    "uncertain_fields": assessed["uncertain_fields"], "budget_known": assessed["budget_known"],
                    "accepted_record": accepted, "evidence": layer_a["evidence"],
                    "year_inferred": layer_a["year_inferred"]},
        normalized={"campus": normalized["campus"], "location": normalized["location"],
                    "semester_by_program": normalized["semester_by_program"],
                    "window": normalized["window"], "registration_deadline": normalized["registration_deadline"],
                    "time_defaults": normalized["meta"]["time_defaults"]},
    )
    base["_normalized_activity"] = normalized
    if status in READY_STATUSES:
        activity, derived = project_sp3(post, accepted, schedule, normalized, base["audience"])
        problems = sp3_contract_problems(activity)
        if problems:
            base.update(status="NOT_SCHEDULABLE", ready_for_scheduling=False,
                        reasons=reasons + [f"contract:{p}" for p in problems])
        else:
            base.update(sp3_activity=activity, sp3_derived=derived, sp3_schedule=sp3_schedule_evidence(schedule))
    if accepted.get("mandatory_stated") is True and not base["ready_for_scheduling"] \
            and "mandatory_unscheduled" not in base["warnings"] and status != "NOT_AN_ACTIVITY":
        base["warnings"].append("mandatory_unscheduled")
    return base


def _dimensions(record: dict) -> dict:
    review = record.get("human_decision") or {}
    return {
        "data_ready_for_scheduling": record["ready_for_scheduling"] and record["duplicate_of"] is None,
        "score_binding_supported": record.get("binding") is not None,
        "student_eligibility_basis": (record.get("audience") or {}).get("basis"),
        "human_reviewed": bool(review and not review.get("stale")) or
                          record["extraction"]["method"] == "human_reviewed_ai_assisted",
        "official_award_verified": False,
    }


# ---------------------------------------------------------------- whole corpus

def _apply_duplicates(records: list[dict], texts: dict[str, str]) -> None:
    store = [{"activity": r["_normalized_activity"]} for r in records if r.get("_normalized_activity")
             and r["status"] != "NOT_AN_ACTIVITY"]
    result = group_duplicates(store, texts)
    by_id = {r["post_id"]: r for r in records}
    for group in result["groups"]:
        members = sorted((by_id[pid] for pid in group),
                         key=lambda r: (not r["ready_for_scheduling"], len(r["reasons"]), len(r["warnings"]),
                                        r["source"]["date_posted"] or "9999", r["post_id"]))
        canonical = members[0]
        for member in members[1:]:
            member["duplicate_of"] = canonical["post_id"]
            member["status"] = "DUPLICATE"
            member["ready_for_scheduling"] = False
            member["reasons"] = ["duplicate_of:" + canonical["post_id"]]
            member["sp3_activity"] = member["sp3_schedule"] = member["sp3_derived"] = None
            canonical["aliases"].append({"post_id": member["post_id"], "url": member["source"]["url"],
                                         "publisher": member["source"]["publisher"],
                                         "date_posted": member["source"]["date_posted"]})
    for left, right, reason in result["possible"]:
        # The text similarity in the reason is a MinHash estimate whose digits depend on the datasketch
        # version; keep only the exact title similarity so the dataset version is machine-independent.
        reason = re.sub(r"_text_[0-9.]+$", "", reason)
        by_id[left]["possible_duplicates"].append({"post_id": right, "reason": reason})
        by_id[right]["possible_duplicates"].append({"post_id": left, "reason": reason})


def _bind(records: list[dict], texts: dict[str, str], ctx: dict) -> None:
    import importlib
    matcher = importlib.import_module("sp2.rule_matcher")
    from sp2.binding import propose_binding
    rules_config = ctx["rules_config"]
    rules = {r["rule_id"]: r for r in rules_config["rules"]}
    for record in records:
        if record["sp3_activity"] is None:
            record["binding_decision"] = {"reason": "not_data_ready" if record["status"] != "DUPLICATE"
                                          else "duplicate_uses_canonical"}
            continue
        review = record["human_decision"] or {}
        reviewed_rule = review.get("rule_id") if not review.get("stale") else None
        match = matcher.match_activity_to_rule(record["sp3_activity"], texts[record["post_id"]], rules_config).as_dict()
        result = propose_binding(record["post_id"], record["activity_type"], match, rules, reviewed_rule=reviewed_rule)
        record["binding"] = result["binding"]
        record["binding_decision"] = {k: result.get(k) for k in ("reason", "label", "matcher_rule", "matcher_method",
                                                                 "category_id", "points_from_rules")}
        if result["binding"] is None:
            record["warnings"].append("score_binding_unsupported")


def _features(records: list[dict]) -> None:
    for record in records:
        if record["sp3_activity"] is None:
            continue
        activity = deepcopy(record["_normalized_activity"])
        if record["sp3_schedule"]["type"] == "FLEXIBLE_WINDOW":
            activity["meta"]["time_defaults"] = {**activity["meta"]["time_defaults"], "window_open": "flexible"}
        record["features"] = feature_values(activity, record["activity_type"])


def summarize(records: list[dict]) -> dict:
    from collections import Counter
    count = Counter(r["status"] for r in records)
    ready = [r for r in records if r["status"] in READY_STATUSES]
    return {
        "posts": len(records),
        "by_status": {status: count.get(status, 0) for status in STATUSES},
        "by_split": dict(sorted(Counter(r["split"] for r in records).items())),
        "by_extraction_method": dict(sorted(Counter(str(r["extraction"]["method"]) for r in records).items())),
        "schedulable_canonical": len(ready),
        "schedule_types": dict(sorted(Counter(r["sp3_schedule"]["type"] for r in ready).items())),
        "with_supported_score_binding": sum(r["binding"] is not None for r in ready),
        "bindings_by_rule": dict(sorted(Counter(r["binding"]["rule_id"] for r in ready if r["binding"]).items())),
        "eligibility_basis_of_schedulable": dict(sorted(Counter(r["audience"]["basis"] for r in ready).items())),
        "not_schedulable_reasons": dict(sorted(Counter(reason for r in records
                                                       if r["status"] in {"NOT_SCHEDULABLE", "EXTRACTION_PENDING"}
                                                       for reason in r["reasons"]).items())),
        "warnings_on_schedulable": dict(sorted(Counter(w for r in ready for w in r["warnings"]).items())),
        "human_decisions_applied": sum(bool(r["human_decision"]) and not r["human_decision"]["stale"] for r in records),
        "human_decisions_stale": sum(bool(r["human_decision"]) and r["human_decision"]["stale"] for r in records),
        "duplicate_groups": len({r["duplicate_of"] for r in records if r["duplicate_of"]}),
        "mandatory_unscheduled": sum("mandatory_unscheduled" in r["warnings"] for r in records),
    }


def build_dataset(posts: list[dict], *, annotations_path=None, human_dir=None, decisions_path=None,
                  llm_files=None, rules_path=None, merge_policy_path=None, overlay_sha256=None) -> dict:
    """Pure build: returns the dataset dict for the given posts (nothing is written)."""
    from .review import load_decisions
    merge_policy = json.loads(Path(merge_policy_path or MERGE_POLICY_PATH).read_text(encoding="utf-8"))
    model_id = merge_policy["_model_id"]
    rules_path = Path(rules_path or RULES_PATH)
    rules_config = json.loads(rules_path.read_text(encoding="utf-8"))
    verified = {r["rule_id"] for r in rules_config["rules"] if r.get("status") == "verified"}
    decisions, decision_problems = load_decisions(Path(decisions_path or DECISIONS_PATH), ACTIVITY_TYPES, verified)
    llm_files = [Path(p) for p in (llm_files if llm_files is not None else default_llm_files())]
    ctx = {"annotations": load_annotations(annotations_path), "human_reviewed": load_human_reviewed(human_dir),
           "decisions": decisions, "replies": load_replies(llm_files, model_id), "model_id": model_id,
           "merge_policy": merge_policy, "policy": load_policy(), "config": load_config(),
           "rules_config": rules_config}
    ids = [p["post_id"] for p in posts]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate post_id in the corpus")
    texts = {p["post_id"]: p["raw_content"] for p in posts}
    records = [process_post(post, ctx) for post in posts]
    _apply_duplicates(records, texts)
    _bind(records, texts, ctx)
    _features(records)
    pending_prompts = {}
    for record, post in zip(records, posts):
        record.pop("_normalized_activity", None)
        record["warnings"] = list(dict.fromkeys(record["warnings"]))
        record["dimensions"] = _dimensions(record)
        if record["status"] == "EXTRACTION_PENDING":
            pending_prompts[record["post_id"]] = post["position"]
    unknown_decisions = sorted(set(decisions) - set(ids))
    inputs = {
        "source_json_sha256": sha256_file(ROOT / "data/raw/source.json"),
        "operational_updates_sha256": overlay_sha256,
        "split_sha256": sha256_file(ROOT / "data/gold/split_v2.json"),
        "ai_annotations": {"path": "data/sp1_annotations/ai_annotations_20261118.json",
                           "sha256": ctx["annotations"].get("sha256"), "packet_id": ctx["annotations"]["packet_id"]},
        "human_reviewed_exports": sorted({r["_file"] for r in ctx["human_reviewed"].values()}),
        "decisions_sha256": sha256_file(Path(decisions_path or DECISIONS_PATH)),
        "model_id": model_id, "prompt_versions": dict(PROMPT_VERSIONS),
        "llm_files": [{"path": str(p.relative_to(ROOT)) if p.is_absolute() and ROOT in p.parents else str(p),
                       "sha256": sha256_file(p)} for p in llm_files],
        "rules_sha256": sha256_file(rules_path), "merge_policy_sha256": sha256_file(Path(merge_policy_path or MERGE_POLICY_PATH)),
        "acceptance_policy": ctx["policy"]["version"],
        "decision_problems": decision_problems + [{"post_id": pid, "problem": "unknown post_id"}
                                                  for pid in unknown_decisions],
    }
    records = redact(records)
    body = {"schema": DATASET_SCHEMA, "activity_contract": ACTIVITY_CONTRACT, "inputs": inputs,
            "summary": summarize(records), "records": records}
    version = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return {"schema": DATASET_SCHEMA, "dataset_version": version,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label": "DEMO_ONLY: data readiness and proposed bindings; not gold, not an official DRL decision",
            **{k: v for k, v in body.items() if k != "schema"}}


# ---------------------------------------------------------------- validation and publication

class DatasetInvalid(ValueError):
    """A built dataset violates the operational contract; it must not be published."""


def validate_dataset(dataset: dict, corpus_ids: list[str] | None = None) -> list[str]:
    problems = []
    records = dataset.get("records", [])
    ids = [r["post_id"] for r in records]
    if len(ids) != len(set(ids)):
        problems.append("duplicate post_id")
    if corpus_ids is not None and ids != list(corpus_ids):
        problems.append("records do not match the corpus (every post exactly once, in corpus order)")
    by_id = {r["post_id"]: r for r in records}
    for r in records:
        pid = r["post_id"]
        if r["status"] not in STATUSES:
            problems.append(f"{pid}: unknown status")
        ready = r["status"] in READY_STATUSES
        if ready != (r["sp3_activity"] is not None) or ready != r["ready_for_scheduling"]:
            problems.append(f"{pid}: status and SP3 activity disagree")
        if not ready and (r["binding"] is not None or r["features"] is not None or r["sp3_schedule"] is not None):
            problems.append(f"{pid}: non-schedulable record carries a binding, features or schedule")
        if r["status"] in {"NOT_SCHEDULABLE", "EXTRACTION_PENDING", "DUPLICATE"} and not r["reasons"]:
            problems.append(f"{pid}: excluded without a reason")
        if r["duplicate_of"] is not None and by_id.get(r["duplicate_of"], {}).get("duplicate_of") is not None:
            problems.append(f"{pid}: duplicate of a duplicate")
        if r["dimensions"]["official_award_verified"] is not False:
            problems.append(f"{pid}: official verification claimed")
        if r["extraction"]["label"] and "GOLD" in r["extraction"]["label"] and "NOT" not in r["extraction"]["label"]:
            problems.append(f"{pid}: extraction labelled as gold")
        if ready:
            a = r["sp3_activity"]
            problems += [f"{pid}: contract {p}" for p in sp3_contract_problems(a)]
            if a["activity_id"] != pid:
                problems.append(f"{pid}: activity id is not the post id")
            accepted = r["acceptance"]["accepted_record"]
            if a["registration_deadline"] is not None and not accepted.get("registration_deadline"):
                problems.append(f"{pid}: deadline without a stated deadline")
            if a["fee"] is not None and _fee(accepted.get("fee"))[0] != a["fee"]:
                problems.append(f"{pid}: fee not from a stated per-person amount")
            if r["sp3_schedule"]["type"] == "FIXED":
                start = accepted.get("window_open") or ""
                if "T" not in start:
                    problems.append(f"{pid}: fixed schedule without a stated start time")
            if r["binding"] is not None and r["binding"]["activity_id"] != pid:
                problems.append(f"{pid}: binding for another activity")
    summary = summarize(records)
    if summary != dataset.get("summary"):
        problems.append("summary does not match the records")
    return problems


def publish(dataset: dict, path: Path | None = None, corpus_ids: list[str] | None = None) -> Path:
    """Validate, write to a staging file next to the target, then atomically replace the target."""
    import os
    problems = validate_dataset(dataset, corpus_ids)
    if problems:
        raise DatasetInvalid("; ".join(problems[:20]))
    path = DATASET_PATH if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.staging-{os.getpid()}")
    staging.write_bytes((json.dumps(dataset, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    reread = json.loads(staging.read_text(encoding="utf-8"))
    if reread["dataset_version"] != dataset["dataset_version"] or validate_dataset(reread, corpus_ids):
        staging.unlink()
        raise DatasetInvalid("staged file does not re-validate")
    os.replace(staging, path)
    return path


def load_dataset(path: Path | None = None) -> dict:
    return json.loads(Path(path or DATASET_PATH).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- messages for the UI

EXTRA_MESSAGES = {
    "audience_not_stated": "Bài không nêu đối tượng; không có giới hạn nào được nêu.",
    "audience_restriction_unresolved": "Đối tượng bị giới hạn bằng mô tả tự do (khoa, ngành, đội...); "
                                       "chưa xác minh được sinh viên có đủ điều kiện nên không tự xếp lịch.",
    "activity_type_unknown": "Chưa rõ loại hoạt động; không tự gán quy tắc tính điểm.",
    "score_binding_unsupported": "Chưa có quy tắc tính điểm được hỗ trợ; hoạt động không được tính vào mục tiêu điểm.",
    "missing_fixed_start_time": "Bài chỉ nêu ngày, không nêu giờ bắt đầu; không tự xếp lịch.",
    "missing_activity_date": "Bài không nêu ngày diễn ra; không tự xếp lịch.",
    "missing_mode": "Bài không nêu hình thức (online/offline); không tự xếp lịch.",
    "missing_quiz_window_end": "Quiz không nêu thời điểm đóng; không tự xếp lịch.",
    "missing_first_session_end_time": "Buổi đầu kéo dài nhiều ngày nhưng không nêu giờ kết thúc.",
    "missing_duration": "Không xác định được thời lượng.",
    "not_an_activity": "Bài chỉ cung cấp thông tin, không phải hoạt động.",
    "insufficient_activity_information": "Bài không đủ thông tin để xác định là một hoạt động.",
    "model_output_missing": "Chưa có kết quả trích xuất của mô hình cho nội dung này; chờ đợt chạy offline.",
    "model_output_stale": "Kết quả mô hình cũ không khớp nội dung/prompt hiện tại; chờ chạy lại offline.",
    "injection_suspected": "Bài có dấu hiệu chèn lệnh; giữ làm dữ liệu, không tự dùng.",
    "candidates_truncated": "Bài quá dài để trích xuất đầy đủ; không tự dùng.",
    "invalid_schedule_value": "Giá trị thời gian không hợp lệ.",
    "end_before_start": "Giờ kết thúc trước giờ bắt đầu.",
}


def message(code: str, policy: dict | None = None) -> str:
    policy = policy or load_policy()
    base = code.split(":")[0]
    if code.startswith("uncertain_soft:"):
        return f"Trường {code.split(':', 1)[1]} chưa chắc chắn; giữ giá trị chưa biết."
    if code.startswith("uncertain:"):
        return f"Trường cốt lõi {code.split(':', 1)[1]} chưa chắc chắn; không tự xếp lịch."
    if code.startswith("duplicate_of:"):
        return "Trùng hoạt động với bài " + code.split(":", 1)[1] + "; dùng bản chính, giữ nguồn làm bí danh."
    if code.startswith("contract:"):
        return "Không đạt hợp đồng hoạt động SP3: " + code.split(":", 1)[1]
    return policy["warnings"].get(base) or EXTRA_MESSAGES.get(base, code)
