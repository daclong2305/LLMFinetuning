# Đợt 1–2: triển khai và kiểm tra

Ngày: 08/11/2026. Đợt 3 (fine-tuning/Kaggle) chưa thực hiện.

## Kết quả triển khai

- Màn hình Thử nghiệm prompt: P0–P4 độc lập, preview không inference, diff theo model/preset/lượt gọi; C4 so với prompt ngay trước sửa.
- Màn hình Báo cáo thông số: run đã lưu, progress/cancel/history, coverage và mẫu số, lỗi, lượt sửa, độ khó, latency, token, cost, CSV/JSON và mở prompt từng mẫu.
- Đóng connection SQLite tường minh trong fixture/pipeline; mock Bedrock đúng SDK Session.client.
- 167/167 unittest đạt; node --check và git diff --check đạt. Browser đã xác minh preview, diff C3/C4, lịch sử sau reload, mở từng mẫu, deep link và tải CSV; console không có warning/error trong các lượt kiểm tra.
- Smoke một câu hỏi: run 597786b1d7e64f6f912d7fb1f195ee2a hoàn tất 10/10 records, 22 lượt model; prompt hashes khớp, preview không gọi model và test split khóa.

## Pilot thực tế

Run: d9d85f454d444a02a55d186f8c78ae36. Hoàn tất 200/200 records: 20 mẫu dev × 2 model × 5 cấu hình. Có 449 lượt gọi model theo trace.

Đây là pilot xác định, luân phiên theo độ khó/database; không phải mẫu ngẫu nhiên đại diện full dev. EX/TS/VES là giao thức local trên dữ liệu Spider ánh xạ schema ViText2SQL, không phải điểm leaderboard. N/A không phải 0. Mẫu lỗi vẫn giữ trong mẫu số khi gold/assets hợp lệ.

| Model | Preset | EM | CM | EX | TS | VES | p50 (s) | Lượt gọi | Lỗi pipeline | API USD ước tính |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|
| claude_haiku | p0 | 70.6% (17/20) | 88.4% (17/20) | 68.8% (16/20) | 50.0% (4/20) | 0.690 (16/20) | 1.36 | 20 | 0 | 0.035102 |
| claude_haiku | p1 | 62.5% (16/20) | 79.6% (16/20) | 75.0% (16/20) | 50.0% (4/20) | 0.749 (16/20) | 2.41 | 40 | 0 | 0.064545 |
| claude_haiku | p2 | 82.4% (17/20) | 90.0% (17/20) | 75.0% (16/20) | 50.0% (4/20) | 0.753 (16/20) | 2.62 | 40 | 1 | 0.087787 |
| claude_haiku | p3 | 70.6% (17/20) | 91.6% (17/20) | 81.2% (16/20) | 100.0% (4/20) | 0.819 (16/20) | 4.15 | 60 | 0 | 0.131456 |
| claude_haiku | p4 | 70.6% (17/20) | 91.6% (17/20) | 81.2% (16/20) | 100.0% (4/20) | 0.813 (16/20) | 4.09 | 60 | 0 | 0.131456 |
| qwen_base | p0 | 42.1% (19/20) | 64.7% (19/20) | 43.8% (16/20) | 75.0% (4/20) | 0.439 (16/20) | 15.60 | 20 | 5 | 0.000000 |
| qwen_base | p1 | 44.4% (18/20) | 59.3% (18/20) | 37.5% (16/20) | 75.0% (4/20) | 0.381 (16/20) | 26.63 | 40 | 6 | 0.000000 |
| qwen_base | p2 | 41.2% (17/20) | 61.4% (17/20) | 37.5% (16/20) | 75.0% (4/20) | 0.378 (16/20) | 26.24 | 40 | 5 | 0.000000 |
| qwen_base | p3 | 35.3% (17/20) | 57.3% (17/20) | 31.2% (16/20) | 75.0% (4/20) | 0.315 (16/20) | 29.17 | 60 | 7 | 0.000000 |
| qwen_base | p4 | 47.1% (17/20) | 69.1% (17/20) | 43.8% (16/20) | 75.0% (4/20) | 0.439 (16/20) | 30.56 | 69 | 5 | 0.000000 |

Tổng lỗi pipeline: 29; tổng lượt sửa C4: 9. Lỗi pipeline và EX=0 là hai khái niệm khác nhau. Local API cost 0 chưa gồm phần cứng/điện. Giá API là cấu hình đã khóa trong manifest.

## Tái lập và giới hạn

- Dataset fingerprint: 41ae0d3f32d246210b1b0ec1c89511ddc1d922e9230b3f87fbb1e75ac394c5b1
- Sample selection: balanced; sample IDs: dev:00000, dev:00009, dev:00007, dev:00001, dev:00019, dev:00022, dev:00017, dev:00021, dev:00047, dev:00083, dev:00085, dev:00061, dev:00121, dev:00145, dev:00133, dev:00123, dev:00166, dev:00171, dev:00174, dev:00168
- Toàn bộ prompt hashes đã xác minh lại trên 200 records; mỗi tổ hợp sample/model/preset chỉ có một record.
- Runtime, model digest/settings, presets, source hashes và raw traces nằm trong reports/experiments/d9d85f454d444a02a55d186f8c78ae36.json (private local, Git ignored).
- Trong smoke Qwen dev:00145, C1 có đầu ra SQL trong subquestions. JSON hợp lệ không bảo đảm nội dung phân rã/lập kế hoạch đúng; cần xem trace khi diễn giải tác dụng C1/C3.
- Dữ liệu cell Spider được giữ nguyên; chỉ ánh xạ tên schema. Xem docs/execution-metrics.vi.md về provenance và giới hạn tương đương ngữ nghĩa của câu hỏi/giá trị tiếng Việt.
- Pilot giữ num_gpu=0. Thử GPU riêng không thay driver/config; các run bị hủy vẫn giữ trong history.
- CLI tái lập: python scripts/run_benchmark.py --split dev --limit 20 --sample-selection balanced --models qwen_base claude_haiku --presets p0 p1 p2 p3 p4
- CSV nhóm: reports/phase12-pilot.csv. Không kết luận module cộng dồn luôn tăng điểm; đây là kiểm tra hệ thống và số liệu pilot.
