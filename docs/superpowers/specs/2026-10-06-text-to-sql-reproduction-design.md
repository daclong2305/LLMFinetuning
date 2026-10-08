# Phạm vi tái hiện khảo sát LLM-based Text-to-SQL

Ngày lập: 06/10/2026. Mục đích đã được người dùng xác nhận: thực nghiệm phục vụ đồ án/luận văn, có baseline và ablation.

## 1. Bài báo thực sự đóng góp gì?

Nguồn chính: [Next-Generation Database Interfaces: A Survey of LLM-based Text-to-SQL](../../../Paper/5.3%20Next-Generation%20Database%20Interfaces%203-%202025.pdf), Zijin Hong và cộng sự, bản arXiv:2406.08426v5 ngày 13/03/2025. File gồm 20 trang; phần nội dung chính kết thúc ở trang 14, các trang còn lại chứa tài liệu tham khảo và tiểu sử tác giả.

Đây là **survey**, không phải bài đề xuất một thuật toán duy nhất với bộ mã và bảng kết quả riêng. Bảng III và IV tổng hợp phương pháp, model, dataset và metric; chúng không phải bảng số đo của một thí nghiệm thống nhất. Vì vậy, mục tiêu hợp lý là tái hiện một số phương pháp đại diện và kiểm chứng các nhận định của khảo sát bằng một giao thức thực nghiệm chung.

| Phần trong PDF | Nội dung cần hiểu | Ý nghĩa khi tái hiện |
|---|---|---|
| I, trang 1-2; Hình 1-2 | Giao diện NL -> SQL -> kết quả; tiến trình nghiên cứu | Xây dựng pipeline thực thi được, phân biệt câu SQL và câu trả lời |
| II, trang 3-4 | Ngôn ngữ mơ hồ; schema phức tạp; SQL hiếm/phức tạp; chuyển miền | Phân tích lỗi theo từng nhóm và độ khó |
| III-A, trang 4-6; Bảng I | Dataset gốc và biến thể; cross-domain, knowledge, robustness, ngôn ngữ, hội thoại, long-context, domain | Chọn Spider/BIRD làm lõi; robustness và tiếng Việt là mở rộng |
| III-B, trang 6; phương trình (1)-(2) | CM, EM, EX, VES | Dùng evaluator chuẩn; đo riêng accuracy, SQL efficiency và LLM latency |
| IV-A, trang 6-10; Bảng II-III | C0 vanilla; C1 decomposition; C2 prompt optimization; C3 reasoning; C4 execution refinement | Baseline và ablation theo nhóm, cho phép một phương pháp thuộc nhiều nhóm |
| IV-B, trang 10-11; Bảng IV; phương trình (6)-(7) | SFT; kiến trúc; pre-training; data augmentation; multi-task | Nhánh fine-tuning nhỏ là tùy chọn, không thay thế toàn bộ nhóm FT |
| V, trang 11-12 | Ưu/nhược điểm truyền thống vs LLM; ICL vs FT | Không kết luận từ accuracy đơn lẻ hoặc từ các model khác nhau |
| VI, trang 12-14 | Robustness, chi phí, privacy, interpretability và mở rộng | Báo cáo trade-off và giới hạn; chọn một hướng nghiên cứu bổ sung |

Mô hình bài toán ở IV-A: SQL dự đoán phụ thuộc instruction, question và schema/content; few-shot thêm các cặp schema-question-gold SQL trong prompt. ICL giữ cố định trọng số; SFT thay đổi trọng số qua loss dự đoán chuỗi SQL.

## 2. Ba cách làm và lựa chọn đề xuất

1. **Tái dựng khảo sát:** lập ma trận tài liệu, taxonomy, bảng dataset và thảo luận. Bám loại bài gốc nhưng thiếu thực nghiệm cho đồ án.
2. **Tái hiện thực nghiệm đại diện, đề xuất chọn:** DAIL-SQL làm phương pháp chính; baseline và các module đối chiếu C0-C4 trên Spider/BIRD. Phù hợp câu trả lời của người dùng, có thể kiểm soát chi phí và xác định tác dụng của từng kỹ thuật.
3. **Bao phủ sâu cả ICL và FT:** thêm SFT/QLoRA, data augmentation và multi-task. Phạm vi lớn hơn, cần GPU và thêm thời gian; chỉ mở sau khi hoàn thành giao thức ICL.

Thiết kế hiện tại chọn cách 2; cách 3 là nhánh mở rộng có điều kiện. Các lựa chọn kỹ thuật dưới đây là đề xuất triển khai, không phải toàn bộ cấu hình do survey quy định.

## 3. Phạm vi bắt buộc

- Một harness chung cho tải dữ liệu, prompt, LLM, SQL execution, official evaluation và logging.
- Spider 1.0 dev là bộ đánh giá chính; BIRD-SQL dev là bộ xác nhận thứ hai. Nếu tài nguyên hạn chế, công bố rõ kết quả BIRD trên subset cố định và giới hạn kết luận.
- Ít nhất một model được cố định trên tất cả phương pháp. Một model thứ hai giúp kiểm tra khả năng tổng quát nếu có tài nguyên.
- Tái hiện DAIL-SQL theo mã tác giả, có nhật ký sai khác về model, SDK, dataset, prompt, retrieval và evaluator.
- Baseline zero-shot, random few-shot, semantic few-shot; đối chiếu masking, SQL skeleton và tổ chức ví dụ.
- Pipeline nghiên cứu có module schema linking, decomposition, kế hoạch SQL có cấu trúc, sửa lỗi và voting bật/tắt độc lập. Phải gọi các tổ hợp tự xây là **biến thể nghiên cứu**, không gọi là bản DIN-SQL/ACT-SQL chính thức.
- Ablation, phân tích độ khó/lỗi, chi phí token, số gọi model, độ trễ và confidence interval.
- Sản phẩm cuối: mã chạy lại được, manifest, prompt, raw predictions, evaluator output, bảng/biểu đồ, báo cáo và demo tối giản.

## 4. Phạm vi mở rộng

- DIN-SQL đầy đủ theo [mã tác giả](https://github.com/MohammadrezaPourreza/Few-shot-NL2SQL-with-prompting), nếu đủ ngân sách cho pipeline nhiều lượt gọi.
- Một phép đánh giá robustness trên Spider-Realistic hoặc Dr.Spider.
- Spider-Vietnamese theo reference [43]; sử dụng dữ liệu/bản chia gốc sau khi kiểm tra, không tự dịch dev rồi coi là benchmark chính thức.
- Một nhánh SFT/QLoRA trên cùng checkpoint trước và sau tuning; data augmentation chỉ từ train.
- Spider 2.0/BIRD-CRITIC, CLLMs và incremental pre-training quy mô lớn: để ngoài phạm vi lõi. Survey nêu chúng, nhưng workload và tài nguyên khác đáng kể.

## 5. Câu hỏi nghiên cứu và tiêu chí thành công

- RQ1: representation, khóa ngoại và cách chọn ví dụ tác động thế nào tới EX/TS và token?
- RQ2: decomposition và kế hoạch SQL có cấu trúc giúp truy vấn khó hay tạo lỗi dây chuyền?
- RQ3: sửa lỗi thực thi và voting cải thiện được nhóm lỗi nào; tốn thêm bao nhiêu?
- RQ4: lợi ích có giữ được trên BIRD, với/không có evidence, và dữ liệu bị biến đổi không?
- RQ5, tùy chọn: SFT trên cùng checkpoint thay đổi accuracy, chi phí và tính linh hoạt ICL thế nào?

Thành công là tạo được thực nghiệm minh bạch, so sánh công bằng và giải thích được kết quả, kể cả kết quả âm. Không đặt mục tiêu bắt buộc đạt một tỷ lệ EX công bố khi khác model/split/evaluator.

## 6. Nguồn sơ cấp đã đối chiếu và các bẫy tái lập

### DAIL-SQL

Đã đối chiếu [bài gốc, mục 3.3 và Appendix A.1](https://arxiv.org/html/2308.15363v3) và [repository tác giả](https://github.com/BeachWang/DAIL-SQL). Phương pháp kết hợp masked-question retrieval, SQL similarity từ SQL dự đoán sơ bộ và tổ chức ví dụ dạng question-SQL. Không dùng SQL chuẩn của câu hỏi cần đánh giá để chọn ví dụ. Chi tiết threshold, model sơ bộ và sampling phải lấy từ đúng cấu hình tác giả được chọn.

Các số liệu tham khảo trong README: DAIL-SQL Spider-dev EX 83.1%, bản có self-consistency 83.6%; Spider-test lần lượt 86.2% và 86.6%. Các số này là kết quả lịch sử của cấu hình tác giả; tuyệt đối không so dev của đồ án với test 86.6% để kết luận tái lập thành công/thất bại. [Nguồn bảng kết quả](https://github.com/BeachWang/DAIL-SQL#evaluation-of-dail-sql).

### Spider

[Trang chính thức](https://yale-lily.github.io/spider) công bố Test Suite Accuracy là metric chính thức và đã dừng nhận submission Spider 1.0; test set đã được phát hành. Kế hoạch ưu tiên chạy local dev, có thể khóa local test để đánh giá cuối. [Evaluator test-suite](https://github.com/taoyds/test-suite-sql-eval) phân biệt có/không thế giá trị gold và giữ/bỏ DISTINCT. Phải lưu các flag; primary track dự đoán đầy đủ giá trị, không dùng `--plug_value`.

### BIRD

[Trang chính thức BIRD](https://bird-bench.github.io/) thông báo dữ liệu dev được làm sạch và phát hành `bird-sql-dev-1106` sau thời điểm PDF này; đồng thời R-VES đã được đưa vào đánh giá. Khóa snapshot gắn với cấu hình cần tái hiện, hoặc ghi rõ dùng snapshot mới và không đối chiếu trực tiếp số lịch sử. [Mini-Dev chính thức](https://github.com/bird-bench/mini_dev) có dữ liệu và evaluator riêng; Mini-Dev không mặc nhiên tương đương một subset nguyên trạng của dev gốc.

### Kiểm tra độ nhất quán của chính survey

- Bảng I trang 5 ghi DuSQL là EN, trong khi III-A5 mô tả câu hỏi tiếng Trung. Khi làm lại bảng phải kiểm tra reference [31].
- Bảng III trang 8 ghi TA-SQL [70], trong khi tài liệu tham khảo [54] là TA-SQL và [70] là Dubo-SQL. Bảng IV trang 10 ghi SQL-LLaMA [48] trong khi [48] là MAC-SQL, còn [85] là bài Code Llama. Không sao chép reference ID thành nguồn thuật toán.
- Mục V có cách mô tả/phân loại không hoàn toàn nhất quán với phần overview; khi triển khai từng method, paper gốc và code gốc là nguồn quyết định.
- Tổng số mẫu của một dataset trong Bảng I không phải số mẫu của split dev được dùng để đánh giá.

## 7. Giả định vận hành

Chưa biết GPU, ngân sách inference và hạn nộp. Lịch lõi đề xuất 8 tuần cho một người làm khoảng 15-20 giờ/tuần, chưa bao gồm thời gian chờ tải dữ liệu, thuê GPU hay xử lý dependency cũ. Bắt đầu với API hoặc checkpoint chạy được trên tài nguyên sẵn có; định cỡ bằng pilot trước khi chốt full run. Kế hoạch chi tiết đi kèm mô tả các mức tài nguyên, giao thức và checklist thực hiện.
