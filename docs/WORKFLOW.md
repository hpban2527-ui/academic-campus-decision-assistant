# Team Workflow

## Branch workflow

Không làm trực tiếp trên `main`.

```text
main
↓
create branch
↓
work
↓
commit
↓
push branch
↓
open PR
↓
1 approval
↓
merge
```

## Branch naming

Tuần 1 có thể dùng:

- `setup/project-architecture`
- `data/course-audit`
- `data/regulation-audit`
- `prototype/computational-engine`
- `research/ai-finetuning`
- `research/product-benchmark`

Về sau:

- `feat/<feature-name>`
- `data/<task-name>`
- `research/<topic>`
- `test/<scope>`
- `ui/<scope>`

## Pull Request

PR cần ghi ngắn gọn:

- What: đã làm gì?
- Why: vì sao cần?
- Evidence: test/output/screenshot nếu có.
- Limitations: còn gì chưa xử lý?

## Review

- Mỗi PR cần ít nhất 1 approval.
- Người tạo PR không tự review PR của mình.
- Reviewer hoặc leader merge sau khi approve.
- Nếu cần sửa, reviewer để comment hoặc Request changes.

## Commit message

Ví dụ:

- `feat: add prerequisite graph prototype`
- `data: add sample course dataset`
- `test: add timetable conflict cases`
- `docs: add regulation audit`

Tránh các commit như `update`, `final`, `fix2`.

## Team principles

- Owner chịu trách nhiệm cuối cùng cho task.
- Có blocker hoặc nguy cơ trễ thì báo sớm.
- Dùng AI được nhưng người push phải hiểu và kiểm tra output.
- Thay đổi architecture / DSL / schema ảnh hưởng module khác phải báo nhóm trước.
- Done = hoàn thành + kiểm tra + review + merge.
