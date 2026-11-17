# Màn hình Duyệt log — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tab "Duyệt log": chọn lần chạy, bước qua từng câu theo thứ tự chạy, xem chỉ số cộng dồn (bảng + hình) và chi tiết câu như khi chạy đơn lẻ.

**Architecture:** Logic thuần trong `demo/static/run-log.js` (`window.RunLog` / `module.exports`), test bằng `node --test`. `experiment.js` thêm view `log`, tải export JSON một lần, render Bảng A, Hình A (SVG), danh sách câu, và mượn hai khối DOM `#view-compare .results-section` + `#prompt-inspector` để hiển thị chi tiết bằng `renderComparison`.

**Tech Stack:** Vanilla JS, Python `http.server`, `node --test`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-17-run-log-question-browser-design.md`

## Global Constraints
- Không đổi API; chỉ thêm `'/run-log.js'` vào whitelist tĩnh `text2sql_demo/server.py:87`.
- Export tải tối đa một lần cho mỗi `(id, done)`.
- Chuỗi từ log vào HTML qua `safe(...)`.
- Sau câu N, chỉ số cộng dồn = `summary.rows` (cùng công thức `summarize_records`).

## Review Focus
1. Bản ghi `status:"error"` có `metrics.ex == null` → ô "error", không phải "na" (test Task 1).
2. Câu chưa có đủ bản ghi (run đang chạy / bị hủy) → ô "pending", chỉ số cộng dồn không tính (test Task 1).
3. Model/preset lạ không có trong `run.models`/`run.presets` → vẫn hiện, xếp sau (test Task 1).
4. Chỉ số cuối khớp summary trên log thật 750 bản ghi (test Task 1, bỏ qua nếu thiếu file).
5. Rời tab Duyệt log → khối kết quả/prompt trả về view So sánh nguyên vẹn (kiểm tra thủ công Task 3).

---

### Task 1: `RunLog` + route tĩnh
**Files:** Create `demo/static/run-log.js`, `tests/js/run-log.test.js`; Modify `text2sql_demo/server.py:87`, `demo/static/experiment.html:12`, `tests/test_server.py`.

**Produces:**
- `exCell(record) -> "pass"|"fail"|"error"|"na"|"pending"`
- `groupRecords(run) -> { models, presets, questions: Question[] }`; `Question = { sample_id, db_id, difficulty, question, records, cells:{[m]:{[p]:cell}}, problems }`, thứ tự theo `run.sample_ids`.
- `cumulative(groups, metric) -> Step[]` với `Step[k-1][model][preset] = { value: number|null, eligible: number, n: number }` sau k câu (trung bình các giá trị khác null).
- `filterQuestions(questions, {difficulty, onlyProblems})`.

- [ ] Viết test (fixture nhỏ + kiểm tra khớp summary trên `reports/experiments/3691cd10d73f4b43879a068701ffdd4e.json` nếu có) → `node --test tests/js/` FAIL.
- [ ] Implement → PASS. Thêm test route `/run-log.js` 200 → thêm route + `<script>` → PASS.
- [ ] Commit.

### Task 2: Tab Duyệt log — chọn run, thanh bước, Bảng A, Hình A, danh sách câu
**Files:** Modify `demo/static/experiment.html` (nav tab `data-view="log"`, `<section id="view-log">`), `experiment.js`, `experiment.css`.
- [ ] `state.runLog = {id, done, run, groups, k}`; `openLog(id)`, `renderLog()`; hash `#log/<id>`; nút "Duyệt log" trong Lịch sử.
- [ ] Kiểm tra trong app với run `3691cd10…`: 50 câu; kéo k=50 → Bảng A khớp bảng Báo cáo; ◀ ▶ / phím ←/→ đổi k; một request export.
- [ ] Commit.

### Task 3: Chi tiết câu k trong tab
- [ ] `mountDetail()` / `unmountDetail()` di chuyển `.results-section` và `#prompt-inspector` giữa view So sánh và `#log-detail`; gọi `renderComparison({id, sample, results: q.records})` khi k đổi.
- [ ] Kiểm tra: chi tiết dev:00005 hiện 15 dòng + so sánh prompt; chuyển sang tab So sánh → khối trở về đúng chỗ.
- [ ] Commit.
