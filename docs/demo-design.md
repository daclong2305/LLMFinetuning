# Bản minh họa Text-to-SQL

Người dùng yêu cầu cài đặt minh họa và chọn Ollama chạy LLM trên máy. Phạm vi: một ứng dụng local Python/SQLite, giao diện tiếng Việt, dữ liệu bán hàng giả lập, LLM Ollama thực sinh SQL từ câu hỏi/schema. Đây là bản minh họa khảo sát, không phải tái lập DAIL-SQL hoặc kết quả Spider/BIRD.

Luồng: chọn schema -> dựng prompt zero/few-shot -> Ollama JSON SQL -> SQLite chỉ đọc -> sửa tối đa 2 lần nếu bật và có lỗi runtime -> hiển thị trace/kết quả. Truy vấn chạy được không đảm bảo đúng ngữ nghĩa. Người dùng được xem và sửa SQL rồi chạy lại. Có chế độ offline chỉ cho bộ câu hỏi mẫu được ghi nhãn rõ, không tự thay Ollama khi kết nối lỗi.

Stack: Python >=3.10 và thư viện chuẩn; HTML/CSS/JS thuần. Ollama portable trong `.runtime`, model trong `.runtime/models`, dữ liệu trong `data/demo.sqlite`. Server chỉ bind 127.0.0.1. Không cần npm/pip cho app.

Kiểm tra bắt buộc: kết quả aggregate trên fixture độc lập; SQL ghi/ATTACH/PRAGMA bị chặn; timeout; một statement; schema không mất bảng nối; prompt không chứa gold câu cần trả lời; repair có giới hạn; lỗi Ollama không được biến thành success/offline; API validation và UI thật. Trước bàn giao, chạy một số câu hỏi qua Ollama thực và kiểm tra kết quả bằng SQL tham chiếu.

Tiến độ: kiểm tra runtime và tải model; RED tests -> core/data/backend; app server/UI; tests tích hợp; chạy Ollama và kiểm tra UI; hướng dẫn khởi động và giới hạn.
