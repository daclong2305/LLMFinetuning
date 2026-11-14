# ViSQL Lab — Kế hoạch refactor UI/UX

**Ngày:** 2026-11-14
**Phạm vi:** `demo/static/experiment.html`, `experiment.css`, `experiment.js` (chỉ phần render). Trang Query Lab cũ (`index.html`, `style.css`, `app.js`) giữ nguyên, không xoá.
**Brief đã chốt:**
- Phong cách: báo cáo nghiên cứu.
- Chữ: tối giản mạnh *phần trang trí* (hero, eyebrow, số bước, chữ quảng cáo). **Phần giải thích là nội dung báo cáo nên vẫn hiển thị**, viết gọn lại và đặt đúng chỗ như ghi chú dưới bảng của một bài báo.
- Mở trang thấy ngay: ô câu hỏi và nút Chạy. Cấu hình gom vào thanh bên.
- Màu: theo nhận diện UIT (xanh logo RGB 47,107,255).

**Ràng buộc kỹ thuật:** giữ nguyên toàn bộ `id` mà `experiment.js` truy vấn (xem mục 7), không đổi API server. Không có test nào kiểm tra HTML/CSS nên rủi ro hồi quy nằm ở JS selector.

---

## 1. Ý tưởng chủ đạo

**Trình bày kết quả như bảng trong một bài báo khoa học.** Mỗi lượt chạy cho ra một *Bảng* đánh số, kẻ theo kiểu booktabs (3 đường kẻ ngang, không có đường kẻ dọc), dùng chữ số tabular, và **giá trị tốt nhất mỗi cột được in đậm** theo đúng quy ước của paper. Toàn bộ "độ táo bạo" dồn vào bảng kết quả, những phần còn lại đều im lặng.

## 2. Token

### Màu: nhận diện UIT
Nguồn: trang nhận diện thương hiệu UIT (en.uit.edu.vn/article/brand-name-identity), xanh logo RGB 47,107,255 và xanh chữ RGB 0,0,253. Xanh chữ thuần `#0000FD` quá gắt cho màn hình nên được hạ sắc độ thành `--uit-deep`. Tương phản trên nền trắng đã đo ở cột cuối.

| Tên | Hex | Dùng cho | Tương phản |
|---|---|---|---|
| `--paper` | `#FFFFFF` | nền | — |
| `--ink` | `#1C2127` | chữ, đường kẻ đậm của bảng | 16:1 |
| `--ink-2` | `#5B636D` | chữ phụ, header cột, ghi chú bảng | 6.1:1 |
| `--hair` | `#D6DADF` | đường kẻ mảnh, viền input | — |
| `--uit` | `#2F6BFF` | xanh logo UIT: nền nút Chạy (chữ trắng), gạch chân tab đang chọn, focus ring, thanh biểu đồ | 4.5:1 |
| `--uit-deep` | `#1A47C2` | link, chữ xanh cỡ nhỏ, tên cấu hình đang chọn | 7.7:1 |
| `--uit-tint` | `#EEF3FF` | nền dòng đang mở trong bảng, nền ghi chú cảnh báo | — |
| `--pass` / `--fail` | `#1D6B43` / `#A8321F` | ✓/✗ thực thi, diff thêm/bớt (nền 8% opacity) | 6.5 / 6.7:1 |

Xanh UIT là màu nhấn duy nhất. Mọi thứ còn lại là đen, xám, trắng để bảng số liệu là trọng tâm.

### Chữ
- **Be Vietnam Pro** (400/500/600): toàn bộ UI và nội dung. Font thiết kế cho tiếng Việt, dấu rõ ở cỡ nhỏ.
- **Source Serif 4** (600): *chỉ* dùng cho chú thích bảng/hình ("Bảng 1.", "Hình 1.") và tiêu đề trong tab Phương pháp. Đây là dấu hiệu "paper", dùng rất ít.
- **JetBrains Mono**: *chỉ* SQL, prompt, diff. Không dùng cho nhãn.
- Thang cỡ: 13 / 15 / 18 / 24 px. Body 15/1.55, serif 1.6. Số: `font-variant-numeric: tabular-nums lining-nums`.
- Tự host `.woff2` (subset latin + vietnamese) trong `demo/static/fonts/` vì app chạy local; `font-display: swap`, fallback `"Segoe UI", system-ui`.

### Hình khối
- Không có card/panel bao viền. Các khối tách nhau bằng khoảng trắng (24 / 48 px).
- Bo góc 6px chỉ cho input, select, nút. Bảng không bo góc.
- Không đổ bóng, không gradient.

## 3. Bố cục

Căn trái toàn bộ. Nội dung chính rộng tối đa 1100px, văn bản tối đa 70ch.

### Thanh trên (56px)
`ViSQL` · 3 tab (So sánh / Báo cáo / Phương pháp) · bên phải là một chấm trạng thái "2/3 mô hình" (thay cho cả dải health-strip; bấm vào để xem chi tiết dữ liệu và mô hình).

### Tab So sánh
```
┌──────────────────────────────────────────────────────────────────────────┐
│ ViSQL    So sánh   Báo cáo   Phương pháp                    ● 2/3 mô hình │
├──────────────┬───────────────────────────────────────────────────────────┤
│ Mô hình      │  (Mẫu dev ▾)(Tự nhập)   [Tìm câu hỏi…              ]       │
│ ☑ Qwen-FT    │  ┌───────────────────────────────────────────┐ ┌──────┐   │
│ ☑ Haiku      │  │ Ca sĩ nào có nhiều buổi diễn nhất?        │ │ Chạy │   │
│ ☐ Qwen base  │  └───────────────────────────────────────────┘ └──────┘   │
│              │  concert_singer   Schema   Prompt                          │
│ Chế độ       │                                                            │
│ ◉ P0 → P4    │  Bảng 1. Kết quả cho mẫu dev_0123                          │
│ ○ Một cấu hình│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│              │  Mô hình  Cấu hình  EM   EX   TS   VES    Thời gian  Chi phí│
│ C1 ⓘ    [  ] │  ─────────────────────────────────────────────────────────  │
│ C2 ⓘ    [■ ] │  Qwen-FT  P2        1    1    1    0,98   1,2 s     $0      │
│ C3 ⓘ    [  ] │  Haiku    P2        0    1    0    0,71   0,8 s     $0,0004 │
│ C4 ⓘ    [■ ] │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│              │  ▸ SQL   (mở ra: SQL của các mô hình đặt cạnh nhau)        │
│ ⚙ Thêm mô hình│                                                           │
└──────────────┴───────────────────────────────────────────────────────────┘
```
- Thanh bên rộng 240px. Dưới 900px nó thành ngăn kéo mở bằng nút "Cấu hình".
- Bấm vào một dòng trong bảng để mở SQL, lỗi, usage của dòng đó.
- Prompt inspector (`#prompt-inspector`) mở dạng ngăn kéo bên phải khi bấm "Prompt", không chiếm luồng chính.
- Trạng thái trống: chỉ một dòng *"Chọn câu hỏi rồi bấm Chạy."*

### Tab Báo cáo
```
Cấu hình chạy (form gọn 1 hàng: mô hình · tập · số mẫu · cấu hình)  [Bắt đầu]
▬▬▬▬▬▬▬▬▬▬▬▬▬▬░░░░░  12/20                                          [Hủy]

Bảng 2. Kết quả benchmark trên dev (n = 20)      [CSV] [JSON]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mô hình   Cấu hình   EM     CM     EX     TS     VES    Độ phủ
───────────────────────────────────────────────────────────
...       (giá trị tốt nhất mỗi cột in đậm)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hình 1. EX theo cấu hình  (thanh ngang mảnh, 1 màu ink, nhãn số ở đầu thanh)

Lịch sử  (danh sách đơn giản: ngày · mô hình · n · EX, bấm để mở)
```
Ngay dưới đường kẻ cuối của Bảng 2 là khối **Ghi chú** (xem mục 4), luôn hiển thị.

### Ghi chú dưới bảng (mẫu)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ghi chú. Số in đậm là tốt nhất mỗi cột. N/A: chưa có phép đo hợp lệ;
độ phủ = số mẫu đo được / n. Lỗi vẫn tính vào mẫu số. EX/TS/VES đo
bằng giao thức local trên dữ liệu Spider ánh xạ schema ViText2SQL,
không phải điểm leaderboard. Chi phí chỉ gồm API.
```
Cỡ 13px, màu `--ink-2`, rộng tối đa 70ch, nằm sát bảng. Đây là cách paper trình bày giải thích: đọc được ngay, không làm rối bảng.

### Tab Phương pháp
Trang đọc 1 cột, 70ch, tiêu đề serif. Chứa bản đầy đủ của các giải thích: định nghĩa EM/CM/EX/TS/VES, quy ước P0–P4 / C1–C4, quy tắc dev/test, nguồn dữ liệu, nguyên tắc suy luận. Ghi chú dưới bảng là bản rút gọn và liên kết sang đây.

## 4. Chữ: bỏ gì, giữ gì, đặt ở đâu

Nguyên tắc: **bỏ chữ trang trí, giữ chữ giải thích**. Giải thích được viết gọn lại và đặt cạnh thứ nó giải thích.

### Giữ và hiển thị (nội dung báo cáo)
| Giải thích hiện có | Vị trí mới |
|---|---|
| P0=C0 … P4=+C4, mỗi cấu hình chạy độc lập, C4 chỉ sửa khi lỗi | Ghi chú dưới Bảng 1 và ngay dưới lựa chọn "Chế độ" ở thanh bên |
| Mô tả C1–C4 (Phân rã câu hỏi, Ví dụ & liên kết schema…) | Giữ 1 dòng mô tả dưới mỗi công tắc ở thanh bên |
| Câu hỏi tự nhập không có SQL tham chiếu → EM, CM, EX, TS, VES là N/A | Ghi chú dưới Bảng 1 (chỉ hiện khi nguồn là "Tự nhập") |
| N/A, độ phủ, lỗi tính vào mẫu số, EX/TS/VES local không phải leaderboard | Ghi chú dưới Bảng 2 |
| Pilot là tập con cố định; test chỉ dành cho đánh giá cuối | Dưới ô "Cách chọn mẫu" / "Tập đánh giá" trong form benchmark |
| Chi phí API không gồm phần cứng/huấn luyện; local = $0 | Ghi chú dưới cả hai bảng (1 câu) |
| Thành phần CM & độ phủ usage (`<details>` trong JS) | Giữ, nằm trong dòng mở rộng của Bảng 1 |
| Định nghĩa chỉ số, dữ liệu & huấn luyện, nguyên tắc suy luận | Tab Phương pháp, đầy đủ |

### Bỏ (chữ trang trí)
| Hiện tại | Sau refactor |
|---|---|
| Hero (h1 "Từ câu hỏi đến…", đoạn mô tả, hero-tag ⌘) | Bỏ |
| Health-strip 3 ô | Chấm trạng thái trên thanh trên |
| Số bước `01 02 03`, eyebrow VIẾT HOA, badge "CÙNG MỘT CÂU HỎI", "TIẾNG VIỆT", "BATCH RUN" | Bỏ |
| "Áp dụng đồng nhất cho mọi mô hình được chọn." | Bỏ (bố cục đã thể hiện) |
| Empty state (icon ⌁, 2 câu, 4 chip chỉ số) | Một dòng |
| Loading box (tiêu đề + đoạn) | Spinner trong nút Chạy |
| Nút "Chạy so sánh →", "Tải JSON ↓", "Làm mới ↻" | "Chạy", "Tải JSON", "Làm mới" |
| Chuỗi JS "KẾT QUẢ ĐANG XEM · id · db · câu hỏi · Run …" | Chú thích bảng: "Bảng 1. Kết quả cho mẫu dev_0123" |
| Nhãn JS "SQL ĐƯỢC SINH" và các nhãn viết hoa khác | Viết thường đầu câu: "SQL" |
| Footer | Bỏ |

## 5. Đối chiếu với lối mòn, và những gì đã sửa

- *Bản nháp đầu:* nền kem, tiêu đề serif lớn, đường kẻ mảnh khắp nơi, kiểu tờ báo. Đây chính là hai lối mòn phổ biến nhất (kem + serif, broadsheet). **Đã đổi:** nền trắng thuần, sans là chữ chính, serif chỉ dùng cho chú thích bảng, đường kẻ chỉ có trong bảng (booktabs), không dùng để chia khối.
- *Bản nháp đầu:* giữ kết quả dạng thẻ (card) cạnh nhau. Đây là bộ SaaS-card mặc định, và khó so sánh số liệu. **Đã đổi:** một bảng chung, SQL mở ra theo dòng.
- *Bản nháp đầu:* nhãn nhỏ dùng font mono. **Đã đổi:** mono chỉ dành cho code.
- Lý do màu nhấn xanh mực: gợi bút chú thích trên bản in, đủ tương phản AA trên nền trắng, và khác teal hiện tại để thấy rõ là đã làm mới.

## 6. Chuyển động và chất lượng tối thiểu

- Chuyển động chỉ khi người dùng thao tác: mở dòng (120ms), ngăn kéo trượt vào, spinner. Tôn trọng `prefers-reduced-motion`.
- Focus ring 2px `--accent` trên mọi phần tử tương tác.
- Dưới 900px: thanh bên thành ngăn kéo. Bảng cuộn ngang, cột "Mô hình" cố định (sticky).
- Tương phản: `--ink-2` trên trắng ≥ 4.5:1.

## 7. ID phải giữ nguyên (do `experiment.js` truy vấn)

`benchmark-button benchmark-chart benchmark-limit benchmark-models benchmark-presets benchmark-split benchmark-status benchmark-table cancel-button compare-button compare-export compare-loading compare-mode compare-results compare-status comparison-context csv-export custom-db custom-input custom-question database-demo-status dataset-badge dataset-details dataset-health dataset-input difficulty-results final-eval-label final-evaluation global-status gold-details gold-sql job-bar job-id job-percent job-progress job-state json-export metric-definitions model-cards model-health model-setup preset preset-label prompt-diff prompt-inspector prompt-kind prompt-model prompt-note prompt-preset prompt-preview-button prompt-rationale prompt-response prompt-stage refresh-runs report-context report-details-button report-manifest report-records retry-info run-history sample-count sample-preview sample-search sample-select sample-selection sample-split schema-button schema-content schema-db schema-details sequence-cancel single-options training-info view-benchmark` cùng các `id` c1–c4, `view-compare`, `view-method`, và class `.nav-tab`, `[data-view]`, `[data-source]`, `.compare-model`.

## 8. Các bước triển khai

1. **Nền tảng:** đổi `experiment.css` cũ thành `experiment.legacy.css` (để so sánh), viết `experiment.css` mới từ token ở mục 2, thêm font tự host.
2. **Khung HTML:** viết lại `experiment.html` theo bố cục mục 3, giữ đủ ID ở mục 7. Thêm script kiểm tra: mọi `$("#…")` trong JS đều có trong HTML.
3. **Bảng kết quả So sánh:** sửa `renderComparison` để render bảng booktabs và dòng mở rộng; in đậm giá trị tốt nhất; rút gọn chuỗi trạng thái.
4. **Tab Báo cáo:** sửa `renderSummary`, `renderJob` và phần lịch sử theo mục 3; biểu đồ thành thanh ngang mảnh.
5. **Sắp lại chữ giải thích:** viết gọn và đặt các ghi chú theo bảng ở mục 4 (ghi chú dưới bảng, dòng mô tả ở thanh bên, bản đầy đủ ở tab Phương pháp). Không ẩn giải thích sau popover.
6. **Responsive và a11y:** ngăn kéo, cột sticky, focus, reduced-motion.
7. **Kiểm tra:** chạy server, chụp màn hình ở 1440px và 390px cho cả 3 tab (trống / đang chạy / có kết quả / lỗi), chạy `pytest`, chạy script kiểm tra ID, rồi xoá `experiment.legacy.css`.
