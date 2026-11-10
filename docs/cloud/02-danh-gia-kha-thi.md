# Đánh giá khả thi Cloud Sync + Webapp (theo GPT_NextStepPlan.md)

> Ngày: 10/11/2026. Tài liệu LOCAL — chưa commit. Đọc cùng `01-audit-hien-trang.md`.
> Kết luận ngắn: **kế hoạch GPT khả thi về kỹ thuật nhưng không cân xứng với nhu cầu hiện tại** (60 mặt hàng, 2 phiếu/ngày, 1 người làm việc tại một thời điểm, khách lớn tuổi, cam kết 0₫). Khuyến nghị: làm **Phương án B (Cloud Backup + trang xem chỉ-đọc)** nếu khách thật sự cần xem từ xa; chỉ làm full sync khi khách cần **hai người cùng ghi ở hai nơi cùng lúc** — điều chưa được xác nhận.

## 1. Bối cảnh quyết định

Tài liệu GPT chốt sẵn Supabase + React Webapp + sync 2 chiều. Nhưng nhu cầu gốc chưa được xác nhận từ khách: **"xem dữ liệu từ nhiều thiết bị" ≠ "ghi dữ liệu từ nhiều thiết bị"**. Toàn bộ phần khó (outbox, conflict, versioning, idempotency, tombstone, UUID migration) chỉ cần khi **ghi** nhiều phía. Nếu chỉ cần **xem**, bài toán nhỏ hơn ~10 lần.

## 2. Giới hạn gói miễn phí (tra cứu 10/11/2026 — nguồn bên thứ ba, cần kiểm lại supabase.com/pricing trước khi cam kết)

| Mục | Supabase Free | Ảnh hưởng tới DiBeKho |
|---|---|---|
| Database | 500 MB, quá thì **read-only** | DB hiện tại rất nhỏ (⚠ chưa đo file thật; ước < 20 MB nhiều năm) → đủ |
| **Tự tạm dừng** | **Project pause sau ~1 tuần không hoạt động**; dữ liệu giữ, phải "đánh thức" | ⚠ Rủi ro chính: khách nghỉ lễ >1 tuần → webapp "chết", khách lớn tuổi không biết vì sao. Cần ping định kỳ hoặc chấp nhận |
| Backup | **Không có backup tự động ở Free** (backup ngày là tính năng Pro $25/tháng) | Mâu thuẫn với mục Cloud Backup của kế hoạch GPT — phải tự làm backup export riêng |
| Auth | 50.000 MAU | thừa |
| Số project | 2 project free | đủ |
| Egress | ~5–10 GB/tháng (nguồn mâu thuẫn) | đủ cho quy mô này |
| Hosting webapp | Cloudflare Pages free: đủ, không giới hạn đáng kể cho static | OK |

Nguồn: [jetadmin.io](https://www.jetadmin.io/blog/supabase-pricing-2026-guide-to-plans-limits-and-real-world-costs/), [activepieces.com](https://www.activepieces.com/blog/supabase-pricing-free-tier-limits-pro-costs-egress), [selfhost.dev](https://selfhost.dev/blog/supabase-pricing-explained/), [metacto.com](https://www.metacto.com/blogs/the-true-cost-of-supabase-a-comprehensive-guide-to-pricing-integration-and-maintenance).

Kết luận chi phí: chạy được 0₫/tháng, **nhưng** (a) không cam kết miễn phí vĩnh viễn, (b) free không có backup, (c) project tự ngủ — tức là "0₫ nhưng kèm điều kiện vận hành", khác hẳn tiêu chí "0₫, không phụ thuộc ai" hiện nay.

## 3. Ba phương án

### A. Giữ nguyên + cải tiến gói `.dibekho` (công: ~vài ngày)

Không cloud. Chỉ làm trơn hơn cách hiện có: nhắc xuất gói khi đóng app có thay đổi chưa gửi (`transfer.has_unsent_changes` đã có), hoặc tự xuất gói vào thư mục đồng bộ sẵn có của khách (Google Drive/iCloud — app đã biết phát hiện thư mục cloud).
- ✅ 0₫ thật, không phụ thuộc dịch vụ, không đổi kiến trúc, Undo/reset/backup giữ nguyên.
- ❌ Không xem được từ điện thoại/web; vẫn mô hình trao tay một máy.

### B. Cloud Backup + trang web XEM chỉ-đọc (công: ~2–4 tuần làm thật)

Desktop sau mỗi phiên (hoặc nút bấm) **đẩy một bản xuất lên cloud**; một trang web tĩnh đăng nhập xem tồn kho/đơn hàng — **không ghi gì từ web**. SQLite vẫn là nguồn sự thật duy nhất → **không cần outbox, conflict, UUID, versioning; Undo/gói/reset giữ nguyên 100%** vì cloud chỉ là bản chiếu.
- Hai biến thể: (B1) upload gói `.dibekho`/JSON xuất vào storage riêng tư + webapp nhỏ đọc nó; (B2) upsert dữ liệu tóm tắt vào Supabase Postgres + webapp Supabase JS. B1 đơn giản hơn nữa.
- ✅ Giải quyết đúng "xem từ nhiều thiết bị"; kiêm luôn Cloud Backup (khắc phục việc Free không có backup — bản xuất chính là backup ngoài máy); rủi ro dữ liệu ≈ 0 (một chiều).
- ❌ Dữ liệu web trễ (mới đến lần đẩy gần nhất); vẫn không cho máy thứ hai ghi; thêm phụ thuộc mạng + đăng nhập (giải được bằng token nhúng/thiết kế đơn giản).

### C. Full Cloud Sync 2 chiều + Webapp ghi được (theo GPT_NextStepPlan.md)

Ước lượng công **thực tế: 3–6 tháng** làm nghiêm túc (sync engine + RPC idempotent + conflict + webapp nghiệp vụ + migration UUID + test đa thiết bị), tức **lớn hơn toàn bộ dự án DiBeKho từ đầu đến nay**. Các điểm phá vỡ kiến trúc đã xác minh trong audit:

| Xung đột | Mức độ |
|---|---|
| **Undo = thay nguyên file DB** (`core/undo.py`) — quay ngược cả outbox/cursor | Chặn. Phải viết lại Undo thành giao dịch đảo hoặc chấp nhận bỏ "hoàn tác mọi thứ" — tính năng xương sống cho khách lớn tuổi |
| **Nhập gói = thay nguyên DB** (`core/transfer.py`) | Chặn tương tự; gói trao tay và sync 2 chiều là hai nguồn sự thật đối đầu |
| Khôi phục backup, reset dữ liệu | Cùng họ vấn đề |
| PK INTEGER, không UUID/version/tombstone; xoá là hard-delete | Migration lớn + đổi thói quen ở mọi nơi ghi |
| Kiểm kê tính "đến hết ngày", đơn-sau-kiểm-kê, mã đơn dùng lại `#n` | Quy tắc nghiệp vụ tinh vi phải tái hiện đúng ở Cloud |
| Supabase free tự ngủ, không backup | Vận hành không "cài rồi quên" được |

- ✅ Đúng tầm nhìn đa thiết bị ghi đồng thời.
- ❌ Không cân xứng: 2 phiếu/ngày, một người thao tác; chi phí bảo trì lâu dài (người dùng tự bảo trì, có thể không dùng Claude hằng tháng); rủi ro cao nhất đặt lên thứ quý nhất (số tồn đúng).

## 4. Khuyến nghị

1. **Hỏi khách một câu duy nhất trước mọi việc:** "Anh/chị cần **xem** số liệu khi không ở máy chính, hay cần **nhập liệu** từ máy thứ hai cùng lúc?"
2. Nếu *xem* (khả năng cao, vì mô hình một-người-làm-việc đã được chốt từ 10/2026): làm **B** (khuyến nghị B1 tối giản), được luôn Cloud Backup. Có thể làm A trước như bước đệm gần-0-công.
3. Nếu thật sự *ghi nhiều máy*: chưa bắt đầu C ngay; làm B trước để có backup + đường mạng, rồi quyết C với kế hoạch riêng (Undo và gói `.dibekho` phải được thiết kế lại trước — đó là việc lớn nhất, không phải Supabase).
4. Dù chọn gì: **không bỏ SQLite, không bỏ gói `.dibekho`, không đụng quy tắc tồn kho** — trùng với ràng buộc của chính tài liệu GPT.
