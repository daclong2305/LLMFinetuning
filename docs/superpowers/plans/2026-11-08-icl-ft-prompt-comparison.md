# Kế hoạch so sánh prompt cộng dồn và fine-tuning

Ngày: 08/11/2026. Trạng thái: người dùng đã yêu cầu triển khai đợt 1–2; đợt 3 (fine-tuning/Kaggle) chưa chạy.

## Quyết định và điểm đang chờ

- Người dùng chọn so sánh cộng dồn C0 → +C1 → +C2 → +C3 → +C4.
- Đã chốt hai màn hình: Thử nghiệm prompt và Báo cáo thông số trong app.
- Fine-tuning dự kiến dùng GPU Kaggle; adapter/checkpoint, thời hạn và ngân sách sẽ chốt ở đợt 3.
- PDF nguồn: paper.pdf, mục IV-A (trang 6–10), IV-B (trang 10–11).
- C0–C4 là nhóm phương pháp của survey. Chuỗi cộng dồn bên dưới là thiết kế thí nghiệm của project, không phải pipeline bắt buộc của paper.

## 1. Hai nhánh dùng chung một giao thức

ICL: giữ weights cố định, thay cấu hình prompt/pipeline trên Qwen base và Claude Haiku Bedrock.
FT: SFT bằng LoRA/QLoRA trên cùng checkpoint Qwen; so sánh trước/sau tuning.
Sau đó đo FT kết hợp cấu hình ICL được chọn bằng dev. Claude là đối chiếu hệ thống; tác dụng riêng của tuning được đo bằng Qwen trước/sau.

Giữ nguyên train/dev/test và database-disjoint. Train dùng học/retrieval; dev chọn cấu hình/checkpoint; test chỉ chạy cuối sau khi khóa quyết định. Không cung cấp gold của mẫu đích cho bất kỳ prompt, bước sửa hay bộ chọn nào.

## 2. Chuỗi cấu hình cộng dồn

| Tên hiển thị | Module bật | Thay đổi chính |
|---|---|---|
| P0: C0 | Không module cải tiến | Instruction + full schema + question |
| P1: +C1 | C1 | Gọi phân rã; đưa câu hỏi con vào prompt sinh SQL |
| P2: +C2 | C1,C2 | Schema linking + ví dụ train; giữ phân rã |
| P3: +C3 | C1,C2,C3 | Gọi lập kế hoạch SQL có cấu trúc; đưa kế hoạch vào prompt sinh SQL |
| P4: +C4 | C1,C2,C3,C4 | Thực thi SQL; chỉ thêm hội thoại sửa khi có lỗi, tối đa hai lần |

Mỗi cấu hình là một lần chạy độc lập cùng sample/model/settings; không truyền SQL giữa các cấu hình. Trong code hiện tại C2 được chuẩn bị trước lượt C1: bật C2 có thể đổi schema đầu vào của C1. Giao diện phải thể hiện thay đổi này. Kết quả cộng dồn đo tác động của việc thêm module trong ngữ cảnh đang có, không chứng minh hiệu quả độc lập của module.

P4 có thể không có lượt repair nếu SQL chạy được. SQL chạy được nhưng sai ý không tự phát sinh sửa theo EX/gold. Có thể bổ sung ví dụ lỗi cố ý cho mục đích dạy minh họa, nhưng phải gắn nhãn và tách khỏi benchmark.

## 3. So sánh prompt và trace

Tận dụng trace/messages/prompt_hash đã có; thêm preset cộng dồn và dữ liệu so sánh theo sample × model × preset × stage × attempt.

Hai chế độ đề xuất:
- Xem cấu trúc prompt trước khi gọi model: hiển thị instruction/schema/examples và placeholder cho đầu ra C1/C3/feedback chưa tồn tại. Không gắn nhãn là prompt thực đã gửi.
- Chạy thật: lưu nguyên messages đã gửi, phản hồi, SQL, lỗi DB, usage và thời gian từng lượt; xem diff với cấu hình trước; riêng lượt sửa C4 so với prompt của lượt gọi ngay trước trong cùng cấu hình.

Tổ chức các khối instruction, schema, examples, question, subquestions, plan và feedback. Hiển thị phần thêm/bớt/đổi; schema/examples có thể thu gọn. Cho xem toàn bộ prompt và copy/xuất kết quả. Không coi kế hoạch có cấu trúc là suy luận nội bộ của model.

Mẫu minh họa đề xuất: dev:00145, concert_singer; hỏi tên và sức chứa sân vận động tổ chức nhiều buổi hòa nhạc nhất từ năm 2014. Mẫu có JOIN/filter/group/order/limit, rõ hơn mẫu đếm ca sĩ trước đây. Thêm mẫu đơn giản và mẫu có lỗi tự nhiên để minh họa giới hạn từng module.

## 4. Kế hoạch fine-tuning

1. Kiểm tra model-q4_k_m.gguf/visql-custom và adapter/checkpoint người dùng đang có. GGUF/Modelfile riêng chưa đủ chứng minh đã tuning. Nếu có artifact phù hợp, kiểm tra base revision, data split, số bước, template, hash và khả năng tái lập trước khi quyết định train lại.
2. Khóa checkpoint Qwen2.5-Coder-3B-Instruct và revision. Chuẩn hóa prompt/output contract chung giữa exporter và inference; code hiện có hai nơi xây prompt cần đối chiếu. Không tạo nhãn explanation không được giám sát từ dữ liệu SQL-only.
3. Audit/export lại train/dev. Con số lịch sử là 6.458/941 mẫu giữ lại; xác nhận bằng manifest mới trước khi train. Ghi rõ mẫu loại, lý do và độ dài, không âm thầm cắt mất target.
4. Pilot QLoRA trên GPU được xác nhận; smoke số bước nhỏ để kiểm tra loss/labels/save/reload, rồi pilot chất lượng có dev cố định. Tham số khởi điểm: 4-bit NF4, rank 8 hoặc 16, batch 1, accumulation theo VRAM; chọn độ dài từ phân bố token thực, không mặc định 1024 nếu loại quá nhiều truy vấn khó.
5. Chạy SFT đầy đủ với loss chỉ trên completion SQL/JSON và EOS. Chọn checkpoint theo dev EX kèm coverage và EM, theo dõi loss, truncation/exclusion và lỗi theo difficulty. Dùng tập dev nhỏ cố định cho kiểm tra thường xuyên nếu chi phí đánh giá đầy đủ quá cao; đánh giá checkpoint cuối trên full dev.
6. Merge/export/register và xác minh artifact. Tạo baseline và FT cùng HF nguồn, template, quantization, runtime và inference settings; nếu chưa khớp thì chỉ kết luận so sánh cấu hình hệ thống.
7. So sánh Qwen base C0, Qwen base + ICL chọn từ dev, Qwen FT C0, Qwen FT + cùng ICL. Nếu đủ tài nguyên, chạy toàn bộ P0–P4 cho cả base và FT.

Nguồn kỹ thuật: https://huggingface.co/docs/peft/main/developer_guides/quantization và https://arxiv.org/abs/2305.14314 . QLoRA cập nhật adapter trên base quantized/frozen, không cần full-parameter tuning. Ưu tiên môi trường Linux GPU; ngân sách và GPU cụ thể chưa chốt.

## 5. Thứ tự thực hiện và nghiệm thu

1. Sửa lỗi quản lý connection SQLite cần thiết cho các test liên quan; xác nhận smoke hiện có vẫn hoạt động.
2. Bổ sung preset P0–P4, chuẩn hóa dữ liệu trace/prompt snapshot, preview và export.
3. Làm phần trình bày theo lựa chọn app/báo cáo; kiểm tra diff bằng một sample có nhiều module, kiểm tra C4 không repair khi thành công.
4. Chạy pilot cố định khoảng 20–30 mẫu dev, cân đối độ khó/database, trên Qwen base và Bedrock để dự toán token/thời gian/chi phí trước full run.
5. Hoàn thành FT theo môi trường/weights đã chốt, rồi đánh giá cùng sample IDs.
6. Khóa giao thức, chạy full dev và đánh giá test cuối; xuất bảng kết quả và phân tích lỗi.

Nghiệm thu: cùng sample/model có năm cấu hình độc lập; prompt thực và preview phân biệt rõ; truy nguyên được mọi lượt gọi; không có gold leak; repair có điều kiện; số liệu gồm denominator/coverage, SQL kết quả, EM/CM/EX/TS/VES, calls/tokens/cost/latency. Asset không đủ giữ N/A. Không tuyên bố năm mức phải tăng điểm liên tục. FT có manifest và cặp baseline phù hợp trước khi kết luận tác dụng tuning.

## Tiến độ thực hiện đợt 1–2

- Đã sửa fixture SQLite đóng connection tường minh trên Windows; sửa mock Bedrock theo Session.client hiện hành.
- Đã thêm preset P0–P4, prompt builder dùng chung preview/runtime, snapshot từng lượt gọi và chọn mẫu pilot cân bằng xác định.
- Đã triển khai hai màn hình, diff theo model/preset/stage/attempt, mở lại prompt từ báo cáo từng mẫu, CSV/JSON và manifest/coverage/pilot label.
- Bộ test: 167/167 đạt. JavaScript syntax và git diff --check đạt.
- Browser: preview, diff, tải lại trang/lịch sử, xem từng mẫu, mở prompt C3, CSV download và bố cục khung hẹp đã xác minh; console không có warning/error.
- Smoke run 597786b1d7e64f6f912d7fb1f195ee2a: 10/10 records, 22 lượt model, toàn bộ prompt hashes khớp. Test split khóa và preview không inference đã kiểm tra.
- Pilot d9d85f454d444a02a55d186f8c78ae36 đã hoàn tất 200/200 records (20 mẫu dev × 2 model × 5 cấu hình), 449 lượt model, 9 lượt sửa. Toàn bộ prompt hashes và code snapshot khớp. Có 29 record lỗi pipeline được giữ nguyên trong báo cáo; đây chưa phải full dev benchmark. Kết quả tại reports/phase12-verification.md và reports/phase12-pilot.csv.
- GPU inference được thử riêng, không thay driver/config; pilot giữ num_gpu=0. Run thử bị hủy giữ nguyên trong history, không trình bày như run hoàn tất.
- Đợt 3 chưa thực hiện: không train, không merge, không tạo hoặc đăng ký model FT.
