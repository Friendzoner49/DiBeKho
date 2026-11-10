# Audit hiện trạng DiBeKho — phục vụ đánh giá Cloud Sync (Phase 0)

> Ngày audit: 10/11/2026, trên nhánh `main` sau v0.4.5, schema SQLite **9**.
> **Tài liệu LOCAL — chưa được commit/push** (repo công khai; chỉ đưa lên sau khi người dùng duyệt + privacy_scan).
> Mỗi kết luận đánh dấu: **[V]** Verified (đã đọc code), **[A]** Assumption (cần xác nhận), **[N]** Not found.

## 1. Kiến trúc hiện tại

**[V]** App desktop Python 3.13 + PySide6, một tiến trình, một database SQLite tại `data/kho.sqlite` trong thư mục làm việc (`Documents/DiBeKho`). Tách lớp: `ui/` (Qt) → `core/` (nghiệp vụ, không Qt) → `db/` (kết nối + migrations). `excel/` đọc/ghi file Excel, hàm thuần.

**[V]** Kết nối: `db/__init__.py:connect` — autocommit (`isolation_level=None`), transaction mở tường minh bằng `db.transaction(conn)` = `BEGIN IMMEDIATE … COMMIT/ROLLBACK`. Hai hàm Python đăng ký vào SQLite: `unaccent`, `matches_words` (tra cứu không dấu).

**[V]** Migration: file SQL `db/migrations/NNN_*.sql`, phiên bản ở `PRAGMA user_version`, chạy trong một transaction mỗi migration, FK tắt khi chạy + `foreign_key_check` trước commit (`db/__init__.py:migrate`). Migration đã phát hành bị đóng băng (test `tests/test_migrations_frozen.py`).

**[V]** Chỉ một bản app chạy mỗi thư mục làm việc (`ui/single_instance.py`, QLockFile).

### Luồng dữ liệu vào/ra

```
phieu-giao-hang/*.xlsx ──scan──> documents(delivery) + document_lines + stock_movements
input/ (hàng về cũ, gói .dibekho, danh mục, dữ liệu gốc) ──> core/inbox.py phân loại
UI (Hàng về, Chuyển hàng, Dùng thử, Kiểm kê, sửa danh mục) ──> core/* ghi DB
output/ <── gói .dibekho, Excel thống kê, file hàng về
sao-luu/ <── backup ngày (10 bản) · sao-luu/hoan-tac/ <── snapshot undo (20 bản)
data/phieu-goc/<sha256>.xlsx <── bản sao mọi phiếu gốc
```

## 2. Bảng và quan hệ (đã xác minh từ migrations 001–009)

**[V]** 15 bảng:

| Bảng | Vai trò | PK | Ghi chú sync |
|---|---|---|---|
| `products` | mặt hàng (code `SPxxx` UNIQUE) | INTEGER | nghiệp vụ — cần đồng bộ |
| `product_aliases` | tên trên phiếu đã học → product | TEXT key | nghiệp vụ |
| `customers`, `suppliers` | khách / nhà cung cấp | INTEGER | nghiệp vụ |
| `documents` | mọi phiếu: `delivery/receipt/stock_count/transfer/trial`; status `active/cancelled/replaced` | INTEGER | nghiệp vụ, lõi |
| `document_lines` | dòng phiếu (qty, giá 007, location 008) | INTEGER | nghiệp vụ |
| `stock_movements` | sổ cái tồn kho, append-only | INTEGER | nghiệp vụ, lõi |
| `locations` | 2 dòng cố định (1 Kho tổng, 2 Văn phòng) | INTEGER | gần như hằng số |
| `ignored_lines`, `document_skipped_lines` | dòng không phải hàng hoá | — | nghiệp vụ phụ |
| `scanned_files` | hash file ↔ trạng thái quét | TEXT hash | **chỉ local** (đường dẫn máy này) |
| `hidden_inputs` | file input bị ẩn | — | chỉ local |
| `meta` | key-value: `last_change_at`, `last_transfer_at`, `low_stock_default`, `freed_codes`, `count_checked`… | TEXT | lẫn lộn local + đi theo gói |
| `app_log` | nhật ký trong DB | INTEGER | chỉ local |

**[V]** **Mọi PK là INTEGER autoincrement; không có UUID, không có cột version, không có tombstone.** Xoá mặt hàng là hard-delete (`catalog.delete_product`) — "khôi phục mặt hàng đã xoá" hoạt động bằng cách **dò các file backup cũ** (`catalog.deleted_products` mở từng bản sao lưu chỉ-đọc), không phải tombstone trong DB.

**[V]** Index nghiệp vụ quan trọng: `ux_documents_active_delivery` — UNIQUE `(code_norm)` WHERE delivery AND active (mã đơn dùng lại xử lý bằng hậu tố `#n` trong `code_norm`, `deliveries._separate_code`).

## 3. Cách tính tồn kho và invariant

**[V]** Bất biến số 1 (ghi ngay đầu `001_init.sql` và `core/stock.py`): **tồn không bao giờ sửa trực tiếp; tồn = `SUM(stock_movements.qty)`**; tồn theo nơi = SUM theo `location_id` (`stock.stock_levels`, `stock.stock_table`).

**[V]** Các `kind` biến động: `delivery_out`, `receipt_in`, `count_adjust`, `transfer_out/in`, `trial_out` + bản đảo `*_reverse` (`stock._FORWARD`, `stock._REVERSE`).

**[V]** Huỷ/thay phiếu **không xoá gì**: thêm biến động đảo cùng ngày phiếu gốc, đổi `status` (`stock.close_document`). Sửa phiếu = phiếu cũ `replaced` + phiếu mới cùng mã.

**[V]** Kiểm kê: chênh lệch = số đếm − tồn **tính đến hết ngày đếm** tại nơi đếm (`stock.stock_count`); phụ thuộc việc phiếu trước ngày đếm đã quét xong. Đơn đọc sau kiểm kê có quy trình riêng (`deliveries.count_conflicts`, `keep_counted`/`subtract_too`, nhớ theo hash trong `meta.count_checked`).

**[V]** Không chặn tồn âm (chỉ tô đỏ). Mỗi file nhập / thao tác ghi = một transaction (mọi hàm ghi trong `core/stock.py` yêu cầu được gọi trong `db.transaction`).

**[V]** `db.touch(conn)` ghi `meta.last_change_at` sau mọi thay đổi nghiệp vụ — đây là "điểm móc" duy nhất hiện có đánh dấu "dữ liệu đã đổi" (dùng cho cảnh báo gói chưa gửi, `transfer.has_unsent_changes`).

## 4. Undo — trở ngại kiến trúc lớn nhất cho Sync

**[V]** `core/undo.py`: trước mỗi thao tác ghi (27 điểm gọi `ctx.undo_point(...)` trong `ui/`, xem danh sách grep ngày 10/11), app **chụp nguyên file database** vào `sao-luu/hoan-tac/` (`backup.snapshot` = `conn.backup()`). Hoàn tác = **thay nguyên file DB bằng bản chụp** (`undo.undo` → `backup.restore` → `os.replace`).

Hệ quả với Cloud Sync: khôi phục file DB sẽ quay ngược **cả** trạng thái sync nếu outbox/cursor nằm trong cùng DB → Cloud đã nhận event mà Local "chưa từng tạo" nó, hoặc ngược lại outbox gửi lại event của dữ liệu đã bị undo. Muốn sync đúng, Undo phải đổi thành thao tác nghiệp vụ có event (giao dịch đảo), hoặc outbox/cursor tách khỏi DB và có logic đối chiếu sau undo — **cả hai đều là thay đổi sâu vào tính năng người dùng tin dùng nhất**.

## 5. Gói `.dibekho` (tài liệu GPT gọi là "USB")

**[V]** `core/transfer.py`: mô hình **"trao tay" — một máy làm việc tại một thời điểm, nhập gói THAY TOÀN BỘ dữ liệu** (không merge). Gói = zip: snapshot `kho.sqlite` + `manifest.json` (device, schema, đếm) + toàn bộ `phieu-goc/` + `app.log`. Bảo vệ: kiểm tra DB thật (`_check_database`), nâng schema trên bản giải nén trước khi thay (`import_package`), cảnh báo 2 lần khi máy nhận có thay đổi chưa xuất (`has_unsent_changes`).

Hệ quả với Sync: nhập gói thay cả DB → cùng vấn đề như Undo nhưng nặng hơn (thay toàn bộ lịch sử, `device_id` trong meta của máy khác). Nếu có Cloud Sync hai chiều thì cơ chế gói trao tay về logic trở thành **nguồn xung đột trực tiếp** với Cloud (hai "nguồn sự thật" thay nhau ghi đè).

## 6. Reset, backup local

**[V]** `core/reset.py`: reset tồn = DELETE 6 bảng; xoá toàn bộ = xoá file DB. Luôn backup trước. Với sync: reset local mà Cloud còn dữ liệu = phải định nghĩa lại ngữ nghĩa (reset là thao tác local hay toàn hệ thống?).

**[V]** `core/backup.py`: backup ngày (10 bản, ≤30 ngày, sàn 3 bản), VACUUM 2 tuần/lần. Khôi phục backup cũng là thay nguyên file DB → cùng vấn đề với sync như Undo.

## 7. Những thứ tài liệu GPT giả định nhưng KHÔNG tồn tại trong code

- **[N]** UUID, version column, tombstone, outbox, change log, device registration trong DB (chỉ có `device_id` trong `config.json` và manifest gói).
- **[N]** Bất kỳ mã mạng/HTTP nào — app hoàn toàn offline, không có dependency mạng trong `pyproject.toml`.
- **[N]** Khái niệm `organizations`, `warehouses` (chỉ có 2 `locations` cố định), `receipts/issues` tách bảng (tất cả phiếu chung bảng `documents`).
- **[A]** Tài liệu GPT mô tả "USB Import/Export" như tính năng rời — thực tế là gói `.dibekho` qua `input/`/`output/`, không gắn với USB cụ thể.

## 8. Điểm tích hợp Outbox NẾU làm (để tham khảo, chưa quyết)

**[V]** Mọi ghi nghiệp vụ đi qua số ít hàm trong `core/`: `stock.insert_document/add_lines/close_document/stock_count/transfer/record_trial_use/set_location`, `catalog.create_product/update_product/delete_product/merge_products/merge_customers/import_catalog/import_master/set_alias/upsert_customer`, `deliveries._import/map_line/…`, `receipts.*`. Tất cả đã chạy trong `db.transaction` và đã gọi `db.touch` — về mặt kỹ thuật outbox chèn được cùng transaction tại `db.touch`/từng hàm. Nhưng các vấn đề mục 4–6 (undo, gói, reset, backup-restore đều thay nguyên file DB) mới là rào cản thật, không phải chỗ chèn outbox.
