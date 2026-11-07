# Chuẩn bị EX, TS và VES

Hai script dùng Python >=3.10 và thư viện chuẩn, không cần cài thêm gói:

```powershell
python scripts/download_execution_sources.py
python scripts/prepare_execution_assets.py --self-check
```

Nguồn riêng nằm trong `.runtime/metric-sources`, database và kết quả audit nằm trong `.runtime/datasets/vitext2sql`. ViText2SQL vẫn dùng nguyên revision và hash JSON đã khóa; script không sửa câu hỏi, gold SQL hoặc split. Dữ liệu đã tải và đã đổi tên chỉ dùng local theo điều khoản nguồn, không được đưa lên Git.

## Nguồn và biến đổi

- Spider gốc: liên kết được công bố trên [trang Spider](https://yale-lily.github.io/spider). Google Drive đã báo quota trong lần chuẩn bị này; dữ liệu được lấy từ [mirror](https://huggingface.co/datasets/HAL-9001/spider-databases/tree/4a01bbac6520cd35b216db9e1724e5e1ada60aa4), SHA-256 `00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b`.
- Test suite: file ZIP được liên kết trong [repo evaluator](https://github.com/taoyds/test-suite-sql-eval/tree/e97acc546ecbee8fa27fa8dbf025ef61493a876c), SHA-256 tải về `9ec24ea8debc6bd04abfe137b5f1a739b5a8836f32c0464e4dfc94eb7f41da96`.
- Metadata schema: `tables.json` của repo evaluator tại cùng revision, SHA-256 `b68de9166952871d64554486fca4b25ff88509e983857a6af428250ffd58b67f`.

Importer đối chiếu số bảng/cột, vị trí cột, loại được chú thích, primary key và foreign key giữa metadata tiếng Anh/Việt. SQLite backup giữ dữ liệu gốc; ALTER TABLE đổi tên identifiers, kể cả khi tên cần hoán đổi. So sánh lại dữ liệu dạng bytes để không sửa text lỗi UTF-8. Với `sqlite_sequence` được liệt kê trong schema, importer giữ snapshot các dòng gốc ở một bảng người dùng mang tên tiếng Việt và để SQLite tiếp tục quản lý sequence nội bộ. Nguồn SQLite gốc không bị sửa.

Tên tiếng Việt trùng nhau không thể ánh xạ thành schema SQLite tương ứng: script báo lý do, không tự đặt tên mới. Dữ liệu demo được nhận diện qua `__visql_demo` và sao lưu có hash trong `demo-backups` trước khi thay thế. Các database không có provenance của importer được giữ nguyên.

## Đọc kết quả

`execution-assets-readiness.json` có coverage theo split và lý do theo database. `execution-assets-import.json` giữ ánh xạ, hash nguồn/đầu ra, danh sách suite và lỗi nhập. `execution-audit.json`, `test-suite-manifest.json` và `evaluation-options.json` được bộ chấm hiện tại nạp trực tiếp.

EX chỉ sẵn sàng cho database có dữ liệu tương thích và toàn bộ gold SQL của schema chạy hoàn chỉnh trong giới hạn bộ chấm. TS còn yêu cầu suite công bố đã nhập đầy đủ, tất cả state qua audit và ít nhất hai trạng thái dữ liệu thực sự khác nhau. Script không thay một suite thiếu bằng các database tự sinh. Nhiều schema không có suite công bố; một số schema có gold không chạy được hoặc nguồn chứa text lỗi UTF-8. Các trường hợp này vẫn N/A, có lý do cụ thể.

VES dùng protocol local 100 cặp gold/prediction xen kẽ, budget 60 giây/mẫu. `ves_eligible` trong báo cáo là số câu đủ điều kiện dữ liệu EX; coverage VES thực tế còn phụ thuộc việc hoàn thành protocol đo. Điểm không phải VES leaderboard BIRD chính thức.

Gold self-check chạy một câu mỗi database đủ điều kiện và một dự đoán cố ý sai, giúp kiểm tra bộ chấm cấp điểm đúng/sai. Kết quả này không đo chất lượng model và không được đưa vào bảng so sánh model.

## Chạy benchmark

Khởi động lại server để nạp snapshot mới, rồi chọn mẫu dev thuộc schema có `ex: true` hoặc `ts: true` trong báo cáo. Benchmark CLI ví dụ:

```powershell
python scripts/run_benchmark.py --split dev --limit 10 --models qwen_base --presets c0
```

Các mẫu cùng model/cấu hình phải dùng chung ID; báo cáo coverage bên cạnh điểm và phân biệt pilot với đánh giá đầy đủ. Test được giữ cho đánh giá cuối qua `--final-evaluation`. Các run cũ không bị ghi đè hay chấm lại dưới fingerprint dữ liệu mới.

Audit lại mà không tải/nhập lại:

```powershell
python scripts/prepare_execution_assets.py --audit-only --self-check
```

Importer có thể chạy lại để dùng các file đã xác minh; checksum sai hoặc database ngoài provenance được báo lỗi và giữ nguyên. Checkpoint suite được lưu nguyên tử sau từng state để tiếp tục sau gián đoạn. Các kiểm tra này bảo vệ quá trình chuẩn bị; provenance và metadata không tự chứng minh rằng mọi câu hỏi/giá trị trong hai phiên bản dữ liệu tương đương về ngữ nghĩa. Kết quả phải được ghi là thí nghiệm local với schema ViText2SQL và dữ liệu Spider được ánh xạ.
