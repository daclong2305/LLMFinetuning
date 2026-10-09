# Hướng dẫn chạy ViSQL Lab từ máy mới

Hướng dẫn này dành cho Windows 10/11 và PowerShell. Người dùng clone mã nguồn từ GitHub, tải Ollama/model và dữ liệu vào máy riêng, rồi mở giao diện local. Không cần huấn luyện lại để chạy model đã phát hành.

## 1. Chuẩn bị

- Cài Git và Python >=3.10, có trên PATH.
- Có kết nối Internet cho lần tải đầu tiên.
- Chừa dung lượng cho archive Ollama, runtime giải nén, model base, dữ liệu và model chia sẻ nếu dùng. Bản GGUF fine-tuned hiện tại riêng đã khoảng 1,93 GB; toàn bộ cài đặt cần nhiều dung lượng hơn.
- GPU không bắt buộc: cấu hình mặc định chạy CPU. Tốc độ phụ thuộc RAM, CPU, GPU và độ dài prompt.

Kiểm tra:

```powershell
git --version
python --version
$env:PYTHONUTF8 = '1'
```

Giữ thiết lập `PYTHONUTF8` trong terminal đang dùng để Python xuất tiếng Việt đúng trên Windows. Nếu mở terminal mới, đặt lại biến này trước khi chạy lệnh Python.

Nếu đã cài Ollama hệ thống và đang chạy nền, hãy thoát Ollama ở khay hệ thống trước khi cài bản portable của dự án. Launcher tái sử dụng server đang nghe ở cổng 11434; server đó có thể dùng kho model khác với `.runtime/models`.

## 2. Clone code

```powershell
git clone https://github.com/daclong2305/LLMFinetuning.git
cd LLMFinetuning
```

Các lệnh bên dưới đều chạy từ thư mục này. Không cần dùng đường dẫn `F:\Code\CSDLPaper` trên máy tác giả.

## 3. Cài runtime và model base

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-demo.ps1
```

Script tải Ollama portable 0.35.1, kiểm tra SHA256 của archive, giải nén vào `.runtime/ollama`, khởi động Ollama, tải `qwen2.5-coder:3b` nếu chưa có và khởi động app. Lần đầu cần đợi tải hoàn tất. Không cần cài torch, transformers hoặc `requirements-training.txt` để mở ứng dụng.

Đây là cài đặt model base. Script không tự tải model fine-tuned của tác giả.

## 4. Tải dữ liệu nghiên cứu

```powershell
python scripts/prepare_vitext2sql.py --audit
```

Lệnh tải ViText2SQL từ revision được khóa, xác minh hash và audit. Dữ liệu nằm tại `.runtime/datasets/vitext2sql`. Audit có thể mất thời gian; đọc kết quả và bảo đảm không có lỗi tải/hash.

Nguồn hiện có 6.831 train, 954 dev và 1.908 test. Nguồn không kèm SQLite có dữ liệu tương thích: EM/CM và kiểm tra cú pháp có thể được chấm khi gold hợp lệ, còn EX/TS/VES có thể hiển thị N/A. Không cần tự tạo database rỗng để làm các chỉ số đó xuất hiện.

Sau khi đã tải, có thể audit lại không gọi mạng:

```powershell
python scripts/prepare_vitext2sql.py --offline --audit
```

## 5. Khởi động và kiểm tra giao diện

Setup đã mở app trước khi tải dữ liệu. Khởi động lại để chắc chắn app đọc dữ liệu và cấu hình mới:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-demo.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-demo.ps1
```

Mở http://127.0.0.1:8765. Demo bán lẻ với dữ liệu giả lập nằm tại http://127.0.0.1:8765/legacy.

Kiểm tra model trong Ollama và app:

```powershell
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $PWD '.runtime\models'
.\.runtime\ollama\ollama.exe list
(Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/experiment/info').models |
    Select-Object id,model,available,unavailable_reason
```

Kết quả mong đợi sau cài mới:

- `qwen_base` sẵn sàng sau khi tải model thành công.
- `qwen_ft` chưa sẵn sàng nếu chưa có checkpoint và manifest huấn luyện local.
- `gpt` chưa sẵn sàng nếu chưa cấu hình API key.

Chọn một câu hỏi ở split dev, chọn model base và C0, chạy và xem SQL, metric, thời gian và lỗi nếu có. Câu hỏi nghiên cứu cần schema tương ứng; không chỉ gửi một câu hỏi rời không có schema.

## 6. Tải model GGUF fine-tuned của tác giả

Model đã phát hành tại [zhenlong54/qwen-vitext2sql-3b-GGUF](https://huggingface.co/zhenlong54/qwen-vitext2sql-3b-GGUF). Repo public, không gated; người dùng không cần đăng nhập để tải bản này. Metadata repo được kiểm tra ngày 09/10/2026.

Tệp đã phát hành là `model-q4_k_m.gguf` (1.929.902.496 bytes). SHA256 trong metadata Hugging Face khớp bản xuất local. Các lệnh bên dưới khóa revision `579ae3d2f0db23dd25fd83076a57dbab79f68dd9`; nếu phát hành bản mới, cập nhật cả tên/revision và SHA256.

```powershell
$sharedRepo = 'zhenlong54/qwen-vitext2sql-3b-GGUF'
$sharedRevision = '579ae3d2f0db23dd25fd83076a57dbab79f68dd9'
$sharedDir = Join-Path $PWD '.runtime\shared-model'
New-Item -ItemType Directory -Force -Path $sharedDir | Out-Null
$sharedFile = Join-Path $sharedDir 'model-q4_k_m.gguf'

Invoke-WebRequest -Uri "https://huggingface.co/$sharedRepo/resolve/$sharedRevision/model-q4_k_m.gguf" -OutFile $sharedFile

$sharedExpectedHash = 'b34a028bc6c18d738b57552423bb75ca555d823c19722c4261acc792547a4cd2'
if ((Get-FileHash -LiteralPath $sharedFile -Algorithm SHA256).Hash -ne $sharedExpectedHash) {
    throw 'GGUF SHA256 mismatch. Do not import this file.'
}
```

Nếu sau này repo chuyển sang private/gated, người dùng cần quyền truy cập và cách tải có xác thực phù hợp.

Tạo Modelfile dùng đường dẫn tương đối, rồi import vào Ollama portable đang phục vụ app:

```powershell
@'
FROM ./model-q4_k_m.gguf
PARAMETER temperature 0
PARAMETER num_ctx 16384
'@ | Set-Content -LiteralPath (Join-Path $sharedDir 'Modelfile') -Encoding ascii

$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $PWD '.runtime\models'
.\.runtime\ollama\ollama.exe create qwen-vitext2sql-public:3b -f (Join-Path $sharedDir 'Modelfile')
if ($LASTEXITCODE -ne 0) { throw 'Ollama model import failed.' }
.\.runtime\ollama\ollama.exe list
```

Không sao chép nguyên Modelfile trên máy tác giả vì nó có thể chứa đường dẫn tuyệt đối `F:/Code/...`.

## 7. Cho app dùng model vừa import

Mở `config/experiment.json`, thêm object dưới đây vào mảng `models`. Giữ nguyên các entry hiện có và thêm dấu phẩy giữa các object; đây là một object để chèn, không phải toàn bộ file config.

```json
{
  "id": "qwen_public",
  "label": "Qwen ViText2SQL · GGUF tải về",
  "provider": "ollama",
  "model": "qwen-vitext2sql-public:3b",
  "base_url": "http://127.0.0.1:11434",
  "num_gpu": 0,
  "num_ctx": 16384,
  "num_predict": 2048,
  "temperature": 0,
  "seed": 42,
  "timeout_s": 240
}
```

Kiểm tra JSON, rồi khởi động lại app:

```powershell
python -m json.tool config/experiment.json > $null
if ($LASTEXITCODE -ne 0) { throw 'Invalid experiment config JSON.' }
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-demo.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-demo.ps1
```

Chọn **Qwen ViText2SQL · GGUF tải về** trong giao diện. ID dùng ở CLI là `qwen_public`.

Entry này dùng để chạy suy luận từ bản phát hành. Hash được kiểm tra ở bước tải, nhưng app hiện không kiểm chứng provenance huấn luyện cho entry này. Không thêm `trained: true` hoặc sửa entry `qwen_ft` để bỏ qua kiểm tra: `qwen_ft` hiện đòi hỏi Safetensors, dữ liệu/manifest của run và đăng ký Ollama khớp digest. GGUF cùng một bản sao manifest chưa đủ đáp ứng luồng đó. Xem `docs/training-qwen.md` nếu muốn tái tạo toàn bộ run.

Tham số `-Model` và `-NumGpu` của `start-demo.ps1` phục vụ demo `/legacy`. Các model ở giao diện nghiên cứu dùng `config/experiment.json`; muốn thử GPU cho `qwen_public` thì đổi `num_gpu` của entry đó thành `-1`, khởi động lại và kiểm tra lỗi/bộ nhớ. Bắt đầu bằng CPU nếu chưa xác minh runtime/driver GPU tương thích.

## 8. Chạy thử benchmark

Trước tiên chạy một pilot nhỏ với base:

```powershell
python scripts/run_benchmark.py --split dev --limit 10 --models qwen_base --presets c0 --output reports/base-pilot.csv
```

Sau khi `qwen_public` sẵn sàng, so sánh trên cùng mẫu và preset:

```powershell
python scripts/run_benchmark.py --split dev --limit 10 --models qwen_base qwen_public --presets c0 --output reports/comparison-pilot.csv
```

Có thể chạy tương tự từ tab Benchmark. Kiểm tra trạng thái completed, số mẫu, lỗi/timeout, coverage và metric unavailable trước khi đọc điểm. Pilot 10 mẫu chỉ để xác minh luồng, chưa đủ kết luận model tốt hơn.

Sau khi chốt cấu hình trên dev, tăng `--limit` lên `954` để chạy full dev. Chỉ dùng test cho đánh giá cuối với `--final-evaluation`. So sánh fine-tune còn cần xác minh checkpoint gốc, template và mức lượng tử hóa tương đương; nếu chưa làm được, báo cáo như so sánh hai cấu hình hệ thống.

Muốn EX, cung cấp SQLite có dữ liệu và schema tương thích tại `.runtime/datasets/vitext2sql/database/<db_id>/<db_id>.sqlite`, audit lại và khởi động lại app. TS/VES cần thêm assets/protocol riêng theo README.

## 9. GPT tùy chọn

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

Lệnh giữ nguyên `.env` nếu đã tồn tại. Mở `.env` trên máy và điền `OPENAI_API_KEY`, rồi khởi động lại app. Không cần key để chạy Qwen local. Gọi GPT cần tài khoản có quyền truy cập model và phát sinh chi phí API.

## 10. Chạy lại, dừng và cập nhật

Những lần sau không cần chạy setup hoặc tải dữ liệu lại:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-demo.ps1
```

Dừng app, giữ Ollama chạy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-demo.ps1
```

Dừng cả app và Ollama do launcher của dự án khởi động:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-demo.ps1 -StopOllama
```

Script chỉ dừng tiến trình mà dự án có bản ghi sở hữu khớp; không dừng Ollama hệ thống được tái sử dụng.

Để cập nhật: dừng app, kiểm tra `git status` và giữ lại thay đổi cấu hình local, chạy `git pull`, rồi khởi động lại. Nếu Git báo conflict, giải quyết conflict trước khi chạy app. `.runtime` bị ignore nên model/dữ liệu local không được tải bằng `git pull`.

## Lỗi thường gặp

| Hiện tượng | Kiểm tra/cách xử lý |
|---|---|
| Không tìm thấy `python`/`git` | Kiểm tra PATH, mở PowerShell mới sau khi cài. |
| `UnicodeEncodeError` khi in tiếng Việt | Đặt `$env:PYTHONUTF8 = '1'` rồi chạy lại Python; có thể dùng `python -X utf8 ...`. |
| Script bị chặn | Dùng lệnh `powershell -NoProfile -ExecutionPolicy Bypass -File ...` ở trên. |
| Cổng 8765 bận | Chạy `start-demo.ps1 -Port 8766` và mở cổng mới; khi dừng dùng `stop-demo.ps1 -Port 8766`. |
| Ollama create xong nhưng app không thấy model | Kiểm tra `/api/tags`, tên/tag config và kho model của server. Thoát Ollama hệ thống nếu nó chiếm 11434, rồi khởi động lại portable và import vào đúng kho. |
| Dataset unavailable | Chạy prepare/audit thành công rồi khởi động lại app. |
| `qwen_ft` unavailable trên máy mới | Đây là trạng thái dự kiến khi không có toàn bộ run; dùng entry `qwen_public` cho bản phát hành. |
| GGUF tải bị 404/403 | Kiểm tra URL/revision/tên file và quyền truy cập; repo có thể đã đổi tên, bị xóa hoặc chuyển sang private/gated. |
| Timeout/CUDA/thiếu bộ nhớ | Bắt đầu CPU; xem `.runtime/logs`. Chỉ tăng timeout trong config khi chấp nhận thời gian chờ dài hơn. |
| EX/TS/VES là N/A | Đọc unavailable reason; bổ sung database/test suite/protocol phù hợp. |

## Phần tác giả cần hoàn tất trước khi chia sẻ

1. Push code cùng hướng dẫn này lên GitHub.
2. GGUF đã phát hành trên Hugging Face và hướng dẫn đã pin revision/hash. Khi cập nhật model, cập nhật hướng dẫn tương ứng; không thay hash để bỏ qua một lượt tải sai.
3. Bổ sung model card và LICENSE vào repo model: tại revision đã kiểm tra mới có `.gitattributes` và GGUF. Model card cần ghi model gốc, revision, dữ liệu/split, hyperparameters, mức lượng tử hóa, SHA256, cách chạy và giới hạn đánh giá. Model gốc `Qwen/Qwen2.5-Coder-3B-Instruct` dùng Qwen Research License; giữ giấy phép và thông báo cần thiết khi phân phối. Việc thêm tài liệu trên repo model sẽ tạo revision mới; revision tải weights được khóa ở trên vẫn dùng được.
4. Thử lại từ một checkout mới để xác minh download/import/start trên máy người dùng. Hướng dẫn này chưa thay thế kiểm tra cài mới có mạng.

Tệp GGUF phục vụ chạy Ollama. Checkpoint merged FP32 khoảng 12,34 GB phục vụ lưu bản gốc hoặc chạy qua Transformers riêng; launcher hiện chưa hỗ trợ checkpoint FP32 trong giao diện. Chạy app/GGUF không cần tải checkpoint merged hay cài thư viện train.

Nguồn: [Ollama import GGUF](https://docs.ollama.com/import), [Hugging Face GGUF/Ollama](https://huggingface.co/docs/hub/en/ollama), [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct/blob/main/LICENSE).
