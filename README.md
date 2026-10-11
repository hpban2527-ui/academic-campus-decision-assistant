# Academic & Campus Decision Assistant

Project E — Computational Thinking.

## Problem

Sinh viên gặp khó khăn khi đưa ra các quyết định về học tập và lịch trình vì thông tin về môn học, prerequisite, thời khóa biểu và quy định học vụ nằm rải rác, đồng thời phải tự đối chiếu nhiều điều kiện với nhau.

## Product direction

```text
Student
→ Natural language / UI
→ AI language layer
→ Structured intent / DSL
→ Computational engine
→ Verified result
→ Explanation / visualization / source
```

AI dùng để hiểu ngôn ngữ và hỗ trợ diễn giải. Phần tính toán chính được thực hiện bởi các module có thể kiểm chứng như graph, rules, constraints, planning và simulation.

## 8-week plan

- Phase 1 — W1–W2: Discovery, pre-processing & design
- Phase 2 — W3–W5: Core implementation & integration
- Phase 3 — W6–W8: Validation, testing & finalization

## Working rule

Không push trực tiếp lên `main`.

Mỗi task:
1. tạo branch riêng;
2. commit + push branch;
3. mở Pull Request vào `main`;
4. cần ít nhất 1 người khác review/approve;
5. reviewer hoặc leader merge.

Chi tiết: [docs/WORKFLOW.md](docs/WORKFLOW.md)
