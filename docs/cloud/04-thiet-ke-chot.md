# Thiết kế chốt — DiBeKho Cloud (phương án C theo điều kiện người dùng, 10/11/2026)

> Người dùng đã chốt (10/11/2026): làm **C — webapp ghi được**, nhưng với các điều kiện:
> 1. **Undo chỉ dùng ở app local** (không cần undo xuyên cloud).
> 2. **Xung đột khi sync → hỏi người dùng**, không tự quyết.
> 3. **Đồng bộ tự động gắn với lúc tắt app** (người dùng đề nghị "5 phút sau khi tắt"), mục đích: **hai máy không làm việc chồng nhau**.
> 4. Supabase **Free**, tự lo backup bằng bản đẩy từ desktop. Nhánh `cloud` local, push khi ổn.
> 5. Tài khoản đăng nhập **không cần email thật** (xem mục 6).
>
> Nhánh: `cloud`. Tài liệu này là nguồn sự thật của thiết kế; đổi gì phải sửa ở đây trước.

## 1. Mô hình: "Gương + Hộp thư" (Mirror + Inbox) — KHÔNG phải sync từng dòng hai chiều

Điều kiện "không làm việc chồng nhau" + "Undo chỉ local" cho phép một mô hình **đơn giản và an toàn hơn hẳn** outbox/change-log/UUID của tài liệu GPT, mà vẫn đạt mọi mục tiêu của C:

- **SQLite trên desktop vẫn là nguồn sự thật duy nhất** về nghiệp vụ (tồn kho, quy tắc, mã phiếu).
- **Cloud giữ hai thứ:**
  1. **Gương (mirror):** bản chiếu đầy đủ, chỉ-đọc, của dữ liệu nghiệp vụ — desktop **thay toàn bộ gương** mỗi lần đẩy (giống xuất gói `.dibekho`, nhưng lên Postgres để web đọc được). Webapp đọc gương để xem tồn kho, đơn, khách, thống kê.
  2. **Hộp thư (web_inbox):** các thao tác ghi từ webapp (tạo phiếu giao, hàng về, sửa ghi chú…) **không ghi thẳng vào gương**. Chúng xếp hàng dạng JSON chờ desktop xử lý — đúng như một file phiếu bỏ vào `input/`: desktop kéo về, chạy qua đúng các hàm nghiệp vụ hiện có (`core/stock.py`, `core/receipts.py`…), hiện trong **Cần xử lý** nếu cần người xác nhận.

Vì sao mô hình này đúng với codebase (bằng chứng: `docs/cloud/01-audit-hien-trang.md`):
- Undo/nhập gói/restore đều thay nguyên file DB → mọi cơ chế cursor/event-log trong DB sẽ hỏng; còn "thay toàn bộ gương" thì **miễn nhiễm**: sau undo, lần đẩy sau gương lại khớp local.
- Không cần UUID/version/tombstone cho dữ liệu local — gương bị thay cả khối, danh tính dòng không cần ổn định xuyên máy. Chỉ item trong hộp thư cần id riêng (UUID sinh phía web).
- Mọi quy tắc nghiệp vụ (kiểm kê "đến hết ngày", mã đơn `#n`, đơn-sau-kiểm-kê, chống trùng) **không phải tái hiện ở cloud** — chỉ chạy một nơi: desktop.
- Dung lượng: ~60 mặt hàng, 2 phiếu/ngày → gương đầy đủ vài MB JSON, đẩy cả khối trong vài giây. Không cần sync vi phân.

## 2. Chu kỳ đồng bộ

```
MỞ APP:   đăng nhập cloud (token lưu theo HĐH) 
          → kiểm tra "ai đẩy gần nhất" (sync_state): nếu là MÁY KHÁC và máy này có thay đổi
            chưa đẩy → CẢNH BÁO XUNG ĐỘT, hỏi người dùng (giữ bên nào) — tái dùng đúng quy
            tắc "trao tay" 2 bước của gói .dibekho (transfer.has_unsent_changes)
          → kéo web_inbox pending → hiện ở Cần xử lý / tự áp dụng mục an toàn → có gì áp dụng
            xong thì đẩy gương luôn
TRONG PHIÊN: làm việc local như hiện nay; Undo thoải mái (chưa có gì rời khỏi máy);
          nút "Đồng bộ ngay" đẩy gương thủ công
TẮT APP:  nếu có thay đổi (meta.last_change_at) → đẩy gương TRƯỚC KHI THOÁT (hộp tiến trình,
          bấm bỏ qua được; offline thì thôi, lần mở sau đẩy bù)
```

**Khác với đề nghị "5 phút sau khi tắt":** sau khi tiến trình thoát, không còn gì chạy để đẩy — hẹn 5 phút cần một tiến trình nền riêng, dễ hỏng trên cả Windows lẫn Mac (máy sleep, antivirus, quyền). Đẩy **ngay lúc tắt** đạt cùng mục đích (phiên làm việc đóng lại là dữ liệu đã lên mạng, máy kia mở ra là thấy); mục đích "không chồng nhau" được bảo đảm bằng cảnh báo xung đột lúc mở. ❓ Nếu người dùng vẫn muốn đúng 5 phút, nói lại — sẽ làm helper nền, chấp nhận kém tin cậy hơn.

Khi web ghi trong lúc desktop đang mở phiên: item nằm chờ trong hộp thư, desktop lấy ở lần mở sau (hoặc khi bấm Đồng bộ ngay). Gương cũ hơn local một phiên là chấp nhận được (đã chốt: không realtime).

## 3. Xung đột — chỉ còn 2 tình huống, đều hỏi người dùng

1. **Hai desktop cùng dùng:** máy A đẩy gương sau khi máy B đã đẩy mà máy A chưa từng thấy bản của B (so `sync_state.last_push_id` lưu local ↔ cloud). → Hỏi như nhập gói hiện nay: "Máy <B> đã gửi dữ liệu lúc <…>. Giữ dữ liệu máy này (ghi đè) / Xem lại / Thôi". Không tự merge.
2. **Hộp thư ↔ local:** item web áp dụng được nhưng "lệch" (vd. mặt hàng đã bị xoá/gộp, kho không đủ, trùng mã) → vào **Cần xử lý** cho người dùng quyết — đúng khuôn mẫu màn hình hiện có.

Undo sau khi đã áp dụng item hộp thư: item chỉ được đánh dấu `applied` trên cloud **tại thời điểm đẩy gương thành công VÀ phiếu tương ứng còn tồn tại trong DB** — nếu người dùng Undo trước khi đẩy, item vẫn `pending` và quay lại Cần xử lý lần sau, không mất đơn của web.

## 4. Schema cloud (Supabase Postgres) — file `cloud/supabase/001_init.sql`

- `mirror_snapshot(id, pushed_at, device_name, device_id, app_version, schema_version, payload jsonb)` — mỗi lần đẩy một dòng, giữ 30 dòng gần nhất. **Đây là lịch sử bản chiếu để tra cứu, KHÔNG phải backup khôi phục được** (sửa 11/11/2026): payload chỉ có tồn đã cộng dồn và thiếu nhiều bảng/cột (`stock_movements`, `product_aliases`, `suppliers`, `meta`, `code_norm`, `source_hash`…), nên không dựng lại được database và sẽ phá bất biến tồn = tổng biến động.
- **Cloud Backup thật = Supabase Storage, bucket riêng tư `backups`** (`cloud/supabase/002_backups.sql`, chỉ role `desktop` ghi/đọc/xoá): sau mỗi lần đẩy thành công app tải lên một bản sao nhất quán của `kho.sqlite` (~300 KB, `backup.snapshot`), tên `<UTC>__<máy>__s<schema>.sqlite`, giữ 30 bản gần nhất. **Khôi phục** (tab Cloud → *Khôi phục từ Cloud…*) tải về, kiểm tra như nhập gói (đúng DB DiBeKho, `quick_check`, không mới hơn app, bản cũ được nâng cấp trên bản sao trước), rồi chạy đúng đường khôi phục sao lưu cục bộ: sao lưu hiện tại → điểm Hoàn tác → thay file. Không chứa `phieu-goc/` (file Excel gốc vẫn ở máy/gói `.dibekho`).
- Đẩy xong mà máy mới nhất trên Cloud lại chính là máy này (sau Hoàn tác/Khôi phục mốc đẩy cục bộ lùi lại) → không hỏi xung đột, tự đẩy lại.
- Bảng gương "phẳng" cho web đọc nhanh: `mirror_products`, `mirror_customers`, `mirror_documents`, `mirror_document_lines`, `mirror_stock(product_id, location, qty)` — desktop thay cả khối qua RPC `replace_mirror(payload)` trong một transaction Postgres.
- `web_inbox(id uuid, kind text, payload jsonb, created_by, created_at, status pending|applied|rejected, result jsonb, applied_at)`.
- `sync_state(id=1, last_push_id, last_push_at, device_id, device_name)` — một dòng.
- `profiles(user_id, display_name, role viewer|editor|desktop)`.
- **RLS:** viewer đọc mirror; editor thêm đọc + INSERT `web_inbox`; role desktop mới được gọi `replace_mirror`, cập nhật `web_inbox.status`, ghi `sync_state`. **Không dùng Service Role Key ở bất kỳ client nào** — desktop đăng nhập bằng tài khoản role `desktop`.

## 5. Phía desktop

- Module mới `src/dibekho/core/cloud/` (không Qt): `auth.py` (đăng nhập/refresh GoTrue), `mirror.py` (gom dữ liệu → JSON), `client.py` (REST PostgREST/RPC), `inbox.py` (kéo + áp dụng item qua core hiện có). HTTP bằng **stdlib `urllib.request`** trước (0 dependency mới, giữ build nhỏ); nếu quá vướng mới cân nhắc `httpx` (hỏi trước khi thêm dependency).
- UI: thêm vào Cài đặt tab "Cloud" (đăng nhập, trạng thái, Đồng bộ ngay); dải trạng thái nhỏ ở cửa sổ chính (offline/đã đồng bộ lúc…/x mục chờ). Không thiết kế lại gì.
- Token lưu: `config.json` chỉ giữ refresh token mã hoá nhẹ theo máy (hoặc keyring HĐH nếu sẵn); không log token (`core/activity.py` đã có quy tắc không ghi chữ người dùng).
- `scanned_files`, `app_log`, `hidden_inputs`, đường dẫn máy — **không đưa vào gương** (chỉ local).

## 6. Tài khoản không cần email — ĐƯỢC

Supabase Auth cho tạo user bằng email "kỹ thuật" không có thật (vd. `me@dibekho.local`, `khach1@dibekho.local`) + mật khẩu, **tắt đăng ký tự do và tắt xác nhận email** trong dashboard. Người dùng chỉ thấy "Tên đăng nhập + mật khẩu" (app tự ghép `@dibekho.local` sau hậu trường). Đánh đổi: quên mật khẩu thì không tự khôi phục qua email — người phát triển đặt lại trong dashboard (phù hợp: 2–3 tài khoản, khách lớn tuổi).

## 7. Webapp (giai đoạn sau của nhánh này)

**Đổi 10/11/2026 (người dùng chọn "cái nhẹ và dễ sửa hơn"):** ~~React + TypeScript + Vite~~ → **HTML + JavaScript thuần** trong `webapp/`, supabase-js nạp từ CDN, không có bước build — người dùng (Java/Python) tự bảo trì được, deploy Cloudflare Pages = kéo thả thư mục. URL + publishable key nằm trong `webapp/config.js` (gitignored; mẫu ở `config.example.js`). MVP-1: đăng nhập, xem Tồn kho / Đơn hàng (+ dòng hàng) / Khách hàng từ bảng mirror, tiếng Việt. MVP-2 (đã làm): tab **Gửi yêu cầu** cho nhân viên (`editor`) → INSERT `web_inbox` với 3 loại: `receipt` (hàng về), `delivery_file` (tải file Excel phiếu giao lên bucket riêng `inbox-files`; duyệt = đặt file vào `phieu-giao-hang/`, tái dùng nguyên đường quét có sẵn — tên hàng, giá, chống đọc trùng, Mở file gốc), `stock_count` (kiểm kê; áp dụng bằng `stock.stock_count(..., at=<lúc nhân viên gửi>)`: chênh lệch tính theo tồn máy biết tại thời điểm đó và phiếu kiểm kê mang `created_at` = lúc gửi, nên phiếu giao vào sổ sau đó rơi vào `deliveries.count_conflicts` để chủ quyết). Gương có thêm `mirror_movements` (mọi biến động tồn) và các cột `created_at`/`location_set`/`supplier_name`… (005) để web tự tính lịch sử vào ra và Thống kê giống app (`webapp/stats.js`, đối chiếu bằng test). Chủ duyệt ở Cần xử lý → *Yêu cầu từ nhân viên (web)* (`ui/web_requests.py`, `core/cloud/inbox.py`). Quyết định người dùng 11/11/2026: phiếu giao = tải file Excel (không form), nhân viên xem được như chủ (không thêm vai trò hạn chế), kiểm kê tính theo lúc gửi. Không offline, không service worker.

## 8. Lộ trình bước nhỏ (mỗi bước: test + commit riêng, trên nhánh `cloud`)

| # | Bước | File chính | Kiểm |
|---|---|---|---|
| 1 | Schema cloud + RLS + RPC | `cloud/supabase/001_init.sql` | đọc duyệt; áp lên project thật ở bước 3 |
| 2 | `core/cloud/mirror.py`: gom DB → JSON (+ ngược lại cho restore) | core, thuần | pytest với DB mẫu |
| 3 | **Người dùng tạo project Supabase** (chỉ người dùng làm được: tài khoản), áp 001_init.sql, tạo user desktop + viewer | dashboard | smoke test |
| 4 | `core/cloud/auth.py` + `client.py` (stdlib HTTP) | core | pytest mock + 1 test thật tuỳ chọn |
| 5 | Đẩy gương thủ công: tab Cloud + nút Đồng bộ ngay | ui/settings | chạy app thật |
| 6 | Đẩy lúc tắt app + cảnh báo xung đột lúc mở | app.py/main_window | test + thử 2 thư mục làm việc |
| 7 | `web_inbox` desktop: kéo + áp dụng + Cần xử lý | core/cloud/inbox.py | pytest |
| 8 | Webapp MVP-1 (xem) | `webapp/` mới | thử trình duyệt |
| 9 | Webapp MVP-2 (ghi vào inbox) | webapp | thử 2 đầu |
| 10 | Rà bảo mật + privacy_scan + quyết định push nhánh | — | checklist |

Mốc dừng tự nhiên: sau bước 6 đã có "C tối thiểu" cho desktop (cloud backup + bàn giao giữa 2 máy không cần USB); web là 8–9.
