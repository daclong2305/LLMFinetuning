# Màn hình "Duyệt log" — thiết kế ngắn

## Mục đích
Mở log của một lần chạy trong **Lịch sử** và xem nó theo từng câu: chỉ số tổng thể thay đổi thế nào khi cộng dồn từng câu theo thứ tự chạy cho đến kết quả cuối, và bấm vào câu để xem đúng giao diện như khi chạy đơn lẻ (Bảng 1, "Prompt thay đổi như thế nào?", SQL, kết quả thực thi). Dùng để phân tích benchmark câu-theo-câu cho báo cáo ViSQL.

## Mục tiêu
- Tab mới **"Duyệt log"** (hash `#log/<run id>`). Tab Báo cáo giữ nguyên; mỗi dòng Lịch sử có thêm nút "Duyệt log".
- Chọn lần chạy (dropdown từ `/api/experiment/runs`).
- Thanh bước câu k/N (◀ thanh trượt ▶, phím ←/→) theo thứ tự `sample_ids`.
- **Bảng A**: chỉ số cộng dồn sau k câu cho mỗi mô hình × P0–P4, chọn một chỉ số (EM/CM/EX/TS/VES); mỗi ô hiện giá trị, thay đổi so với sau k−1 (▲/▼/=), số mẫu đo được / số mẫu; viền ô có kết quả câu k.
- **Hình A**: đường chỉ số cộng dồn theo k, một preset mỗi lần (chọn P0–P4), một đường mỗi mô hình, vạch dọc tại k.
- Danh sách câu (mã, db, độ khó, câu hỏi, lưới mô hình × preset tô theo EX), lọc theo độ khó và "chỉ câu có sai/lỗi". Bấm câu → k nhảy tới câu đó.
- Chi tiết câu k ngay trong tab, tái dùng bảng kết quả + so sánh prompt của view So sánh.
- Sau câu N, Bảng A khớp đúng `summary` của lần chạy (cùng cách tính với `summarize_records`: trung bình trên các giá trị khác null; ô không có giá trị đo được là N/A).
- Lần chạy đang chạy: tải lại khi `done` thay đổi.

## Không làm
- Không phát lại theo thời gian; không gọi model; không sửa API.

## Ràng buộc
- Dữ liệu từ `GET /api/experiment/export?id=<id>&format=json` (đã có), tải một lần cho mỗi `(id, done)`.
- Bộ lọc danh sách không ảnh hưởng chỉ số cộng dồn (luôn theo thứ tự chạy).
- Logic tính toán ở module thuần `demo/static/run-log.js`, test bằng `node --test`; chỉ thêm route tĩnh `/run-log.js` vào whitelist của server.

## Các cách đã cân nhắc
- **A. Dùng API export sẵn có, màn hình riêng trên trình duyệt (đã chọn).**
- B. Tính chuỗi cộng dồn ở server — thêm API mới, không cần vì dữ liệu đã đủ ở client.
- C. Trang HTML riêng ngoài app — phải viết lại phần hiển thị.

## Để người làm tự quyết
Kiểu ô lưới, cách vẽ hình (SVG thuần), cách mượn DOM bảng kết quả/so sánh prompt của view So sánh (di chuyển node khi vào/ra tab).
