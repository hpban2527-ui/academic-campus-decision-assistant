"""Build a source-grounded AI draft review packet; never writes gold or runtime data.

Usage: python scripts/package_ai_review.py --work-dir artifacts/ai_review_20261118
Automatic policy routing is distinct from optional human review and independent gold.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jsonschema import Draft202012Validator
from sp1.activity_type import KEYWORDS
from sp1.acceptance import assess_activity, load_policy
from sp1.devdata import get_post, non_test_ids
from sp1.extract_v2 import extract_v2, FIELDS
from sp1.hybrid import merge
from sp1.llm_v2 import decide
from sp1.preprocess import preprocess

VERSION = "unilife-ai-assisted-review/1.0"
FIELDS_WITH_EMPTY = {"audience_scope", "completion_requirements"}


def present(value):
    return value not in (None, [], {}, "") and value != {"cohorts": [], "programs": []}


def redact_comparison(value):
    if isinstance(value, dict):
        return {key: redact_comparison(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_comparison(item) for item in value]
    if isinstance(value, str):
        value = preprocess(value).text
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email removed]", value)
        return re.sub(r"\(\d{2,3}\)[ .-]*\d(?:[ .-]?\d){6,8}", "[phone removed]", value)
    return value


def build(work_dir: Path):
    work_dir = work_dir.resolve()
    sources = json.loads((work_dir / "source_manifest.json").read_text(encoding="utf-8"))
    allowed = set(non_test_ids())
    source_by_id = {p["post_id"]: p for p in sources}
    if len(source_by_id) != 129 or set(source_by_id) != allowed or any(p["split"] == "test" for p in sources):
        raise ValueError("Packet must contain exactly the 129 non-test source IDs")
    schema = json.loads((ROOT / "schemas/layer_a_record_v2.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator({**schema["$defs"]["record"], "$defs": schema["$defs"]})
    types = {key for key, _ in KEYWORDS} | {"other"}
    annotations = {}
    for path in sorted((work_dir / "annotations").glob("batch_*.json")):
        for item in json.loads(path.read_text(encoding="utf-8-sig")):
            pid = item["post_id"]
            if pid not in allowed or pid in annotations:
                raise ValueError(f"Unknown or duplicate draft ID in {path.name}: {pid}")
            validator.validate(item["record"])
            if item.get("activity_type") not in types:
                raise ValueError(f"Invalid activity_type: {pid}")
            if set(item.get("unsure", [])) - set(FIELDS) - {"activity_type"}:
                raise ValueError(f"Unknown unsure field: {pid}")
            text = source_by_id[pid]["source_text"]
            evidence = item.get("evidence", {})
            for field, value in {**item["record"], "activity_type": item["activity_type"]}.items():
                quotes = evidence.get(field, [])
                if not isinstance(quotes, list) or any(not isinstance(q, str) or not q or q not in text for q in quotes):
                    raise ValueError(f"Evidence is not an exact source substring: {pid} / {field}")
                if present(value) and not quotes:
                    raise ValueError(f"Missing evidence for a proposed value: {pid} / {field}")
            annotations[pid] = item
    if set(annotations) != allowed:
        raise ValueError(f"Missing {len(allowed - annotations.keys())} non-test annotations")

    policy = json.loads((ROOT / "data/config/merge_policy.json").read_text(encoding="utf-8"))
    llm = {}
    llm_path = ROOT / "data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl"
    if llm_path.exists():
        for line in llm_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("post_id") in allowed:
                    llm[row["post_id"]] = row
    rows = []
    for source in sources:
        pid = source["post_id"]
        post = get_post(pid)
        fingerprint = hashlib.sha256(post["raw_content"].replace("\r\n", "\n").replace("\r", "\n").encode()).hexdigest()
        if fingerprint != source["source_sha256"]:
            raise ValueError(f"Source changed since annotation started: {pid}")
        annotation = annotations[pid]
        baseline = merge(extract_v2(post), decide(post, llm[pid]["replies"]) if pid in llm else None, policy)
        previous = redact_comparison(baseline["layer_a"]["record"])
        differences = [field for field in FIELDS if previous.get(field) != annotation["record"][field]]
        evidence = annotation.get("evidence", {})
        ai_record = {**deepcopy(annotation["record"]), "activity_type": annotation["activity_type"]}
        rows.append({
            **source,
            "ai_record": ai_record,
            "ai_evidence": deepcopy(evidence),
            "record": deepcopy(ai_record),
            "evidence": deepcopy(evidence),
            "evidence_spans": {field: [{"start": source["source_text"].index(q),
                "end": source["source_text"].index(q) + len(q), "text": q} for q in quotes]
                for field, quotes in evidence.items()},
            "year_inferred": annotation.get("year_inferred", []),
            "ai_unsure": annotation.get("unsure", []),
            "unsure": annotation.get("unsure", []),
            "field_notes": annotation.get("field_notes", {}),
            "notes_codes": annotation.get("notes_codes", []),
            "ai_notes": annotation.get("ai_notes", ""),
            "previous_record": {**previous, "activity_type": baseline["classification"]["activity_type"]},
            "changed_fields": differences + (["activity_type"] if annotation["activity_type"] != baseline["classification"]["activity_type"] else []),
            "review": {"status": "pending", "reviewer": None, "reviewed_at": None,
                       "checked_fields": [], "notes": "", "field_notes": {}, "provenance": {}},
        })
    acceptance_policy = load_policy()
    for row in rows:
        row["data_policy"] = assess_activity(row, acceptance_policy)
    status_counts = Counter(row["data_policy"]["status"] for row in rows)
    summary = {
        "posts": len(rows), "test_posts": 0, "approved": 0,
        "posts_with_uncertainty": sum(bool(r["unsure"]) for r in rows),
        "posts_with_proposed_changes": sum(bool(r["changed_fields"]) for r in rows),
        "proposed_field_changes": sum(len(r["changed_fields"]) for r in rows),
        "uncertain_fields": dict(Counter(f for r in rows for f in r["unsure"])),
        "split_counts": dict(Counter(r["split"] for r in rows)),
        "policy_status_counts": dict(status_counts),
        "ready_for_scheduling": sum(r["data_policy"]["ready_for_scheduling"] for r in rows),
        "not_ready_reasons": dict(Counter(reason for r in rows for reason in r["data_policy"]["reasons"])),
    }
    data = {"schema": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
            "label": "AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD", "human_approved": False,
            "description": "129 bài dev/pool được AI trích xuất, tự phân loại theo hợp đồng dữ liệu. Người dùng chỉ cần sửa ngoại lệ; không chứa 60 bài test.",
            "acceptance_policy": acceptance_policy,
            "summary": summary, "record_schema": schema["$defs"]["record"], "items": rows}
    data["packet_id"] = hashlib.sha256(json.dumps(
        [(r["post_id"], r["source_sha256"], r["ai_record"], r["ai_evidence"]) for r in rows],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    output = work_dir / "deliverables"
    output.mkdir(exist_ok=True)
    json_path = output / "unilife_ai_drafts_129.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    catalog = {"schema": "unilife-policy-catalog/1.0", "packet_id": data["packet_id"],
               "label": "AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD", "policy": acceptance_policy,
               "summary": summary, "scope": "129_non_test_posts_only",
               "items": [{"post_id": row["post_id"], "position": row["position"], "split": row["split"],
                          "source_url": row["source_url"], "source_sha256": row["source_sha256"],
                          "field_notes": row["field_notes"], "evidence": row["evidence"],
                          **row["data_policy"]} for row in rows]}
    (output / "unilife_policy_catalog_129.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    template = (ROOT / "scripts/review_ai_drafts.html").read_text(encoding="utf-8")
    template = template.replace("/*__ACCEPTANCE_JS__*/", (ROOT / "scripts/activity_acceptance.js").read_text(encoding="utf-8"))
    encoded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html_path = output / "unilife_review_129.html"
    html_path.write_text(template.replace("/*__REVIEW_DATA__*/null", encoded), encoding="utf-8")
    guide = """# Xử lý theo hợp đồng dữ liệu — 129 bài dev/pool

1. Mở unilife_review_129.html bằng Chrome/Edge. Dữ liệu đã tự phân loại; không cần duyệt từng bài để được đưa vào nhóm đủ lịch.
2. Xem 'Đủ lịch, có cảnh báo' hoặc 'Chưa đủ lịch'. Thiếu dữ kiện BTC không phải nhiệm vụ bắt người duyệt phải bổ sung.
3. Lĩnh vực, chi phí và link chưa rõ được giữ cảnh báo. Chi phí không rõ không trở thành miễn phí và không bảo đảm ngân sách.
4. Buổi trực tiếp/live thiếu giờ không vào lịch. Quiz có cửa sổ rõ và thời lượng hợp lệ vẫn xếp linh hoạt được.
5. 'Xuất theo quy tắc' tải cả danh mục đã phân loại tự động, không mang nhãn người duyệt hay gold.
6. Nếu thấy sai, sửa giá trị/bằng chứng. Việc ghi nhận người đã kiểm tra là tùy chọn; chưa rõ vẫn được giữ để policy quyết định dùng hay loại.
7. Tiến độ JSON từ bản cũ vẫn nạp được qua 'Nạp tiến độ', nếu đúng các ID bài và fingerprint nguồn. Nhấn 'Lưu tiến độ' để giữ sửa đổi.

Tệp unilife_policy_catalog_129.json là dữ liệu theo hợp đồng mới: accepted_record giữ phí null, metadata có lịch, cảnh báo ngân sách và khả năng lập lịch. Đây không phải dữ liệu SP3 14 trường cũ: không được ép phí null thành 0 để lách hợp đồng cũ.
Đủ dữ kiện lịch chưa xác minh số điểm, điều kiện của một sinh viên, thời hạn hiện tại hoặc công nhận chính thức. Các bước đó vẫn thuộc SP2/SP3.
Các bài bắt buộc nhưng chưa đủ lịch được giữ cảnh báo. Hạn đăng ký thiếu không được tự biến thành giờ bắt đầu.
60 bài test được giữ riêng. Không đổi nhãn tự động thành bộ gold hoặc kết quả người duyệt.
"""
    (output / "HUONG_DAN_DUYET.md").write_text(guide, encoding="utf-8")
    (output / "HOP_DONG_DU_LIEU_V1.md").write_text(
        (ROOT / "docs/ACTIVITY_DATA_ACCEPTANCE_V1.md").read_text(encoding="utf-8"), encoding="utf-8")
    (output / "activity_acceptance_v1.json").write_text(
        json.dumps(acceptance_policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = ["# Kết quả tự phân loại 129 bài", "",
              f"- Đủ dữ kiện tạo lịch: {summary['ready_for_scheduling']}/129.",
              f"- Chưa đủ dữ kiện lịch: {status_counts['NOT_SCHEDULABLE']}.",
              f"- Chỉ cung cấp thông tin: {status_counts['NOT_AN_ACTIVITY']}.",
              "- Không có bài nào tự mang nhãn người đã duyệt hoặc gold.", "",
              "Đây là mức sẵn sàng dữ liệu, không phải kết quả đo độ đúng NLP, khả năng tham gia hiện tại hoặc số điểm.",
              "", "## Bài chưa xếp được lịch", ""]
    for row in rows:
        a = row["data_policy"]
        if a["status"] == "NOT_SCHEDULABLE":
            title = (row["record"]["title"] or "Chưa có tên").replace("\n", " ")
            report.append(f"- #{row['position']} — {title}: {', '.join(a['reasons'])}.")
    (output / "TONG_HOP_PHAN_LOAI.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zip_path = work_dir / "unilife_review_129.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            archive.write(path, path.name)
    return summary, zip_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "artifacts/ai_review_20261118")
    args = parser.parse_args()
    summary, path = build(args.work_dir)
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    print(path)
