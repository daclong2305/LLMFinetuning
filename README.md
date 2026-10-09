# ViSQL Lab: thí nghiệm Text-to-SQL tiếng Việt

Hệ thống thực nghiệm trên **ViText2SQL chính thức**: Qwen2.5-Coder gốc, Qwen đã fine-tune riêng và GPT snapshot cố định `gpt-4.1-mini-2025-04-14`. Một pipeline C0–C4 dùng chung cho mọi backend, có so sánh từng câu hỏi và benchmark/ablation. Model hoặc metric chưa đủ điều kiện luôn hiển thị **N/A/chưa sẵn sàng**, không thay bằng kết quả mô phỏng.

## Chạy từ máy mới sau khi clone

Xem [hướng dẫn đầy đủ cho Windows/PowerShell](docs/getting-started.vi.md): cài runtime, tải dữ liệu, tải/import GGUF đã phát hành, cấu hình model, benchmark và xử lý lỗi.

```powershell
git clone https://github.com/daclong2305/LLMFinetuning.git
cd LLMFinetuning
$env:PYTHONUTF8 = '1'
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-demo.ps1
python scripts/prepare_vitext2sql.py --audit
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-demo.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-demo.ps1
```

Mở http://127.0.0.1:8765 và chạy trước với Qwen base. Cần Python >=3.10 và Git trên PATH; không cần cài thư viện train. Model fine-tuned/dữ liệu không kèm trong Git. Tải bản GGUF đã phát hành tại [zhenlong54/qwen-vitext2sql-3b-GGUF](https://huggingface.co/zhenlong54/qwen-vitext2sql-3b-GGUF) theo bước 6–7 trong hướng dẫn để dùng entry `qwen_public`; chỉ tải GGUF chưa đủ bật entry `qwen_ft` có kiểm tra provenance.

## Khởi động hệ thống mới

```powershell
cd F:\Code\CSDLPaper
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-demo.ps1
```

Mở [http://127.0.0.1:8765](http://127.0.0.1:8765). Nếu server cũ đang chạy, dừng app rồi khởi động lại để nạp mã mới. Bản bán lẻ trước đây được giữ tại [http://127.0.0.1:8765/legacy](http://127.0.0.1:8765/legacy). Cổng kiểm tra riêng có thể dùng `-Port 8766`.

Runtime chính dùng Python >=3.10 và stdlib, không cần torch để mở giao diện. Ollama/model portable hiện có được tái sử dụng. Cấu hình mô hình nghiên cứu nằm trong [config/experiment.json](config/experiment.json); `-Model`/`-NumGpu` của launcher phục vụ demo bán lẻ cũ, còn các backend nghiên cứu lấy settings từ JSON.

## Dữ liệu và khóa split

```powershell
python scripts/prepare_vitext2sql.py --audit
# Sau khi đã tải, chạy lại audit mà không gọi mạng:
python scripts/prepare_vitext2sql.py --offline --audit
```

Nguồn VinAIResearch/ViText2SQL khóa ở commit `e759141d891feb794bb9a9fb912d544b25583b3c`, syllable-level. Nguồn thực tải về có **6.831 train / 954 dev / 1.908 test**, 166 database không trùng giữa split. Test thực tế khác con số 1.906 trong bài công bố; giữ nguyên bytes nguồn và SHA256. Các tệp nguồn riêng ở `.runtime/datasets/vitext2sql`, không phân phối lại cùng mã. Xem [điều kiện sử dụng của tác giả](https://github.com/VinAIResearch/ViText2SQL).

Train dùng cho SFT và few-shot retrieval; dev chọn cấu hình/checkpoint; test chỉ dành cho đánh giá cuối với `final_evaluation=true`. Không dùng gold của mẫu cần đánh giá để sinh hoặc chọn SQL. Audit gold lưu cả IDs/lý do không chấm được; không sửa nhãn nguồn hay tự loại mẫu dự đoán sai.

**Nguồn không kèm SQLite có dữ liệu.** Tên bảng/cột và các giá trị SQL đã dịch; không ghép tùy tiện với SQLite tiếng Anh. Cung cấp database tương thích tại `.runtime/datasets/vitext2sql/database/<db_id>/<db_id>.sqlite`, hoặc đặt `TEXT2SQL_DATABASE_DIR`, rồi audit và khởi động lại server. Đóng writer và checkpoint WAL trước: chỉ dùng snapshot tĩnh, có hash được khóa. Bước kiểm tra bằng schema trống chỉ xác nhận cú pháp, không dùng kết quả rỗng để chấm EX.

## Mô hình, fine-tuning và mở rộng

- Qwen base: `qwen2.5-coder:3b`, mặc định CPU trên máy này.
- Qwen fine-tuned: checkpoint riêng và manifest chứng minh quá trình huấn luyện, merge và đăng ký Ollama. Chuẩn bị dữ liệu không đồng nghĩa đã huấn luyện.
- GPT: tạo `.env` local từ `.env.example`, điền `OPENAI_API_KEY` trên máy; không gửi key trong chat hoặc đưa vào Git. Thông tin/trace/export không trả credential. Chỉ có key chưa bảo đảm tài khoản có quyền gọi model; lỗi provider được ghi nhận.

```powershell
python scripts/train_qwen.py --diagnostics
python scripts/train_qwen.py --prepare-only
python scripts/train_qwen.py --status
```

Exporter đã thực chạy và giữ **6.458 train / 941 dev** sau khi compile target với schema; 373/13 mẫu bị loại có IDs/lý do. Huấn luyện GPU cần môi trường riêng và [requirements-training.txt](requirements-training.txt). CLI hỗ trợ SFT LoRA/QLoRA completion-only, pinned HF revision, seed, giới hạn pilot, merge và đăng ký bằng Ollama portable. Xem toàn bộ lệnh tại [docs/training-qwen.md](docs/training-qwen.md). Model đã fine-tune và manifest không được phân phối cùng Git; máy mới cần tải bản phát hành hoặc tái tạo run trước khi sử dụng.

Khi kết luận tác dụng riêng của fine-tuning, phải xác minh baseline GGUF và model dùng để train có cùng checkpoint gốc/HF revision, template và điều kiện lượng tử hóa. Manifest ghi HF revision, digest/quantization Ollama và settings; nếu chưa xác minh cùng nguồn weights, chỉ diễn giải như so sánh hai cấu hình hệ thống.

Thêm model cùng provider bằng một entry JSON. Thêm provider qua `BackendRegistry.register_provider(name, factory, availability)`; adapter trả text, token/cached token, cost, model/digest và lỗi có metering. Không cần sửa pipeline, dataset hay evaluator. Khởi động lại server sau khi sửa JSON.

## C0–C4 và ablation

| Cấu hình | Triển khai đại diện |
|---|---|
| C0 | Question + DDL/schema + instruction, không có các module cải tiến |
| C1 | Một lượt phân rã thành tối đa 4 câu hỏi con |
| C2 | Retrieval lexical chỉ từ train + schema linking, giữ đường FK |
| C3 | Một lượt tạo kế hoạch SQL có cấu trúc; không tuyên bố đó là suy luận nội bộ của LLM |
| C4 | Phản hồi lỗi SQLite/output để sửa, tối đa 2 lần; không dùng gold để sửa |

Preset gồm baseline, C2, C2+C4, full và full bỏ lần lượt từng C1–C4. Đây là module nghiên cứu dựa trên survey, không phải bản tái lập nguyên DIN-SQL/DAIL-SQL. Không cần bật tất cả module hoặc chạy mọi tổ hợp để sử dụng.

## Metric và cách diễn giải

| Metric | Giao thức |
|---|---|
| EM | Spider Exact Set Match có adapter tên tiếng Việt; bỏ giá trị literal/DISTINCT và dùng FK equivalence theo chính sách upstream. Có SQLite compile guard. |
| CM | Mean active-component F1 theo mẫu; có breakdown SELECT/WHERE/GROUP/ORDER/KEYWORDS và thành phần phụ. |
| EX | So toàn bộ kết quả trên SQLite có dữ liệu và gold audit; giữ duplicate, chỉ yêu cầu thứ tự hàng khi gold có ORDER BY ở mức ngoài cùng; cho phép một hoán vị cột nhất quán. |
| TS | Nhiều trạng thái dữ liệu đã xác minh; cần manifest, hash, provenance, schema, gold và ít nhất 2 trạng thái khác nhau. Đây là adapter nghiên cứu local, không tự nhận là official ViText2SQL leaderboard. |
| VES | Bật bằng protocol riêng; tối thiểu 100 cặp gold/pred chạy xen kẽ, mean sqrt(gold_ms/pred_ms), chỉ khi EX/gold hợp lệ. Sai dự đoán điểm 0; VES là điểm hiệu suất có thể lớn hơn 1, không phải tỷ lệ accuracy. |
| Syntax/Execution success | Phân biệt SQL compile được và chạy được trên data-filled DB; không thay EX. |
| Latency | Toàn pipeline p50/p95/mean, SQL riêng; điều kiện CPU/GPU/mạng lưu trong run. |
| Usage/Cost | Tất cả lượt C1/C3/sinh/sửa, token thực và cached rate; unknown giữ N/A cùng subtotal đã biết. Local API cost 0 không bao gồm GPU/điện/huấn luyện. |

N/A không phải 0. Báo cáo có denominator/coverage từng metric, lỗi/timeout, per-difficulty, component F1, Wilson 95% (giả định theo mẫu; các câu cùng DB có thể tương quan). Dự đoán lỗi/timeout vẫn nằm trong denominator khi gold/assets hợp lệ. Gold không chấm được có lý do và coverage riêng. Preview 200 dòng không được dùng làm kết quả chấm điểm.

TS dùng `.runtime/datasets/vitext2sql/test-suite-manifest.json`; VES dùng `evaluation-options.json`. Contract và giới hạn đầy đủ tại [vendor/spider/NOTICE.md](text2sql_demo/experiment/vendor/spider/NOTICE.md). Thiếu assets thì EX/TS/VES hiện N/A; không có số benchmark ngụy tạo.

## Chạy và xuất benchmark

```powershell
python scripts/run_benchmark.py --split dev --limit 10 --models qwen_base --presets c0 c2_c4 --output reports/pilot.csv
# Chạy full dev bằng limit 954; chỉ thêm model đã sẵn sàng:
python scripts/run_benchmark.py --split dev --limit 954 --models qwen_base qwen_ft gpt --presets c0 full
# Test khóa, chỉ đánh giá cuối sau khi chốt:
python scripts/run_benchmark.py --split test --limit 1908 --models qwen_base --presets c0 --final-evaluation
```

Giao diện **Benchmark** hỗ trợ start/progress/cancel/history và JSON/CSV. CLI Ctrl+C chờ lượt đang chạy lưu usage rồi dừng. Run lưu sample IDs, source/database/metric fingerprints, code/evaluator hashes, model snapshot/digest/settings/giá và môi trường chạy. Run partial/cancelled/interrupted không được trình bày như full benchmark; tiến trình owner được kiểm tra cả từ CLI khác. File local ở `reports/experiments`, raw trace chứa các ví dụ nguồn nên không tự công bố/đẩy lên Git.

Kiểm tra:

```powershell
python -m unittest discover -s tests -v
```

## Demo bán lẻ trước đây — /legacy

Ứng dụng local minh họa khảo sát **Next-Generation Database Interfaces: A Survey of LLM-based Text-to-SQL**. Nhập câu hỏi tiếng Việt/Anh -> Ollama sinh SQL từ schema -> SQLite trả kết quả. Giao diện hiển thị prompt, ví dụ, bảng được chọn, SQL, số token, thời gian và lỗi/sửa lỗi.

## Chạy ngay trên máy này

Ollama portable và model được lưu trong `.runtime/`; không cần pip/npm để chạy ứng dụng. Mở PowerShell tại thư mục dự án:

```powershell
.\start-demo.ps1
```

Mở [http://127.0.0.1:8765](http://127.0.0.1:8765). Nếu PowerShell chặn script, chạy với policy chỉ áp dụng cho tiến trình đó:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-demo.ps1
```

Script khởi động Ollama và app ở chế độ nền, đợi dịch vụ sẵn sàng và tải model nếu thiếu. Dịch vụ Ollama có sẵn được tái sử dụng. Model mặc định `qwen2.5-coder:3b`; có thể đổi bằng `-Model <tên-model>` (model mới sẽ cần tải). Xem log trong `.runtime/logs/`.

Dừng app nền bằng `.\stop-demo.ps1`; thêm `-StopOllama` nếu muốn dừng cả dịch vụ Ollama do script này tạo. Script đối chiếu PID, executable và thời điểm khởi động, không dừng dịch vụ ngoài bản demo. Khi đổi model/compute, dừng app hiện tại hoặc dùng một cổng khác.

Bản cài trên máy này mặc định **CPU** (`-NumGpu 0`), do Ollama 0.35.1 gặp lỗi CUDA `device kernel image is invalid` với driver RTX 3060 hiện có. Không thay driver hệ thống. Khi đã có runtime/driver GPU tương thích, có thể thử `-NumGpu -1` (auto) trên cổng mới, ví dụ `-Port 8766`; giao diện hiển thị cấu hình compute. Model 3B trên CPU cần chờ lâu hơn GPU.

Nếu chép mã sang máy khác: Python >=3.10, Windows 10/11 phù hợp Ollama; chạy `setup-demo.ps1` để tải runtime chính thức đã khóa version/SHA256 và model. Cần dung lượng cho runtime, archive và model. Thư mục `.runtime` bị bỏ qua trong Git.

Chạy app ở terminal để có thể dừng bằng Ctrl+C:

```powershell
python -m text2sql_demo.server
```

Lệnh trên chỉ chạy app; Ollama phải đang hoạt động. Server chỉ bind `127.0.0.1`. Không đổi sang public binding khi chưa thiết kế authentication.

## Cách trình diễn

1. Giữ chế độ **Ollama · LLM local** và chọn “Top 5 sản phẩm có doanh thu cao nhất”.
2. Nhấn **Sinh SQL & xem kết quả**. Quan sát JOIN, GROUP BY, ORDER BY, LIMIT và bảng kết quả. Ví dụ hoàn tất này trả “Laptop văn phòng” với doanh thu 570.000.000 VND trên dữ liệu giả lập.
3. Mở **Luồng xử lý** và **Prompt gửi đến model**: xem schema, 2 ví dụ khác câu hỏi hiện tại và các lượt thực thi.
4. Tắt few-shot, bật schema linking hoặc tắt refinement; chạy lại và đối chiếu SQL, token, thời gian. Đây là quan sát demo, không phải ablation benchmark có ý nghĩa thống kê.
5. Sửa tên cột trong SQL thành tên không có thật và nhấn **Chạy lại SQL đã sửa** để xem phản hồi của DB. Nút này thực thi SQL chỉnh sửa, không tự gọi LLM sửa; refinement áp dụng khi pipeline sinh SQL gặp lỗi.
6. Hỏi tự do, ví dụ: “Liệt kê tên các sản phẩm thuộc danh mục Điện tử, sắp xếp theo mã sản phẩm”. Model vẫn có thể hiểu sai; cần kiểm tra SQL.

Chế độ **Ví dụ offline** chỉ thực thi SQL tham chiếu của 6 câu hỏi mẫu, không dùng LLM và không hỗ trợ câu hỏi tự do. Không tự động chuyển sang offline khi Ollama lỗi.

## Nội dung minh họa từ bài báo

| Thành phần | Cách minh họa |
|---|---|
| Vanilla prompting C0 | Câu hỏi + instruction + schema; tắt few-shot |
| Prompt optimization C2 | 2 ví dụ được chọn bằng lexical similarity; loại câu hỏi trùng target |
| Schema linking | Heuristic từ khóa Việt/Anh và đường nối khóa ngoại |
| Execution refinement C4 | Feedback lỗi SQLite, tối đa 2 lần sửa; SQL lặp lại thì dừng |
| Chi phí/hiệu năng | Token Ollama thực, thời gian pipeline và thực thi SQL riêng |

Đây **không phải DAIL-SQL, DIN-SQL hay kết quả Spider/BIRD**. Không triển khai fine-tuning, SQL skeleton retrieval hoặc decomposition trong demo này. Kế hoạch nghiên cứu đầy đủ nằm trong [docs/superpowers/plans](docs/superpowers/plans/2026-10-06-text-to-sql-reproduction.md).

## Dữ liệu và quy tắc

- SQLite tự tạo: 32 khách, 12 sản phẩm, 144 đơn hàng và các dòng chi tiết; seed 42; dữ liệu giả lập.
- Tiền là số nguyên VND. Doanh thu = `SUM(quantity * unit_price)` của đơn `completed`; `pending`/`cancelled` không tính.
- Bốn bảng: `customers`, `products`, `orders`, `order_items`; model nhận DDL, quan hệ và mô tả ngắn.
- Thực thi ở chế độ đọc, chặn ghi/DDL/ATTACH/PRAGMA/load_extension và các hàm tạo blob/format lớn. SQLite progress callback có deadline 5 giây theo kiểu best-effort; không thay thế process isolation của sản phẩm production. Python >=3.11 bổ sung SQLite length limit 1 MB; preview từ chối ô text trên 100.000 ký tự.
- Preview tối đa 200 dòng, có nhãn cắt bớt; không sửa SQL để tự thêm LIMIT.
- Không dùng SQL tham chiếu của câu hỏi hiện tại làm ví dụ trong prompt LLM. Bộ demo nhỏ có schema và miền cố định, không đo generalization.
- Thực thi thành công chỉ xác nhận SQL chạy được, chưa chứng minh SQL trả lời đúng câu hỏi.

## Kiểm tra

```powershell
python -m unittest discover -s tests -v
python scripts/smoke_ollama.py
```

Test tự động dùng SQLite thật và server HTTP local; kiểm tra aggregate, FK bridge, read-only, timeout, repair budget, validation và offline labeling. Live smoke gọi model thật và so với 7 truy vấn tham chiếu trên dữ liệu giả lập; giữ duplicate khi so kết quả không yêu cầu thứ tự, giữ thứ tự cho ranking/tháng. Ghi kết quả ở `reports/demo-live-smoke.json`. Đây là kiểm tra smoke nhỏ, không phải metric của bài khảo sát.

## Nguồn

- PDF trong [Paper](Paper/5.3%20Next-Generation%20Database%20Interfaces%203-%202025.pdf).
- [Ollama Windows và standalone CLI](https://docs.ollama.com/windows).
- [Ollama Chat API](https://docs.ollama.com/api/chat): payload messages, stream=false, format=json, token counts.
- [Model qwen2.5-coder:3b](https://ollama.com/library/qwen2.5-coder:3b).
