# 06 — Cloud làm gốc, app là client (quyết định 11/11/2026; bước 1–5 đã làm, xem cuối file)

> Đảo lại nguyên tắc "máy chính là nguồn sự thật" của `04-thiet-ke-chot.md` — đã thay thế hẳn (bước 1–5 xong). Các tài liệu cũ `01`–`04` (audit, khả thi, câu hỏi, thiết kế Gương + Hộp thư) đã gỡ khỏi repo 13/11/2026; xem lại trong lịch sử git nếu cần (các file SQL 001–006 còn nhắc tới chúng).
> Lý do người dùng nêu: "dữ liệu lưu trên cloud mới là chính xác nhất; app như một client kết nối, đồng bộ ngược lại và thao tác trên chúng. Không cần app mở ở đâu đó mới chạy được."

## Quyết định đã chốt (11/11/2026)

| Vấn đề | Chốt |
|---|---|
| Nguồn sự thật | Postgres trên Supabase (bảng thật, không còn "gương") |
| Gói Supabase | **Free** + app tự kéo **bản sao SQLite đầy đủ mỗi ngày** (vừa là sao lưu, vừa là bản xem khi mất mạng) — vì Free ngủ sau ~1 tuần không dùng và không tự sao lưu |
| Mất mạng | **Ghi được cả khi mất mạng, đồng bộ sau** (người dùng chọn, trái với khuyến nghị "chỉ xem") → cần hàng đợi thao tác (outbox) + xử lý xung đột |
| Hoàn tác | **Phiếu đảo ngược cho thao tác cuối của chính mình** (như "Huỷ phiếu" hiện có). Bỏ kiểu chụp cả file |
| Khách thật | Giữ **chế độ local làm mặc định**; chạy chế độ cloud trên máy người phát triển trước; chỉ bật cho khách khi số liệu hai bên khớp |

## Cảnh báo đã nói với người dùng
- "Ghi được khi offline" là chỗ khó nhất: phải quay lại bài toán đồng bộ từng dòng mà audit Phase 0 (`01`,`02`) đã loại. Cần: id không đụng nhau giữa máy (UUID), phiếu chỉ **thêm** (không sửa tại chỗ) để hợp nhất được, tồn = tổng biến động nên hai máy cùng ghi phiếu không mâu thuẫn; chỉ những thao tác **sửa** (mặt hàng, khách, nơi lấy hàng) mới có xung đột thật.
- Kiểm kê và "đơn sau kiểm kê" (`count_conflicts`) phụ thuộc thứ tự thời gian → phải dùng giờ của máy chủ lúc ghi nhận, không dùng giờ máy khách.
- Nhập gói `.dibekho`, Đặt lại dữ liệu, Khôi phục: thành thao tác quản trị trên cloud (hỏi 2 lần, sao lưu trước), không còn "thay file".

## Luật nghiệp vụ nằm ở đâu (sửa 11/11 sau khi chốt "ghi được khi offline")
Máy offline không gọi được hàm trên mạng, nên **Python trên app vẫn là nơi cài luật** (giữ nguyên `core/`, đã có hàng trăm test). Web phải chạy được khi không app nào mở, nên web ghi qua **hàm Postgres (RPC)** cài lại đúng các luật đó; mỗi RPC có **test song song** với Python (cùng đầu vào → cùng phiếu, dòng, biến động). Đọc Excel vẫn ở Python.

## Mô hình đồng bộ (bước 1–2)
- **Trên máy:** SQLite vẫn là bản làm việc (và hàng đợi khi offline). Migration **010** thêm `sync_map` (id trên máy ↔ uuid trên cloud), `sync_outbox` (dòng nào đã đổi) và **trigger** trên các bảng nghiệp vụ — không phải sửa đường ghi nào trong `core/`. Trigger chỉ ghi khi `sync_flags.enabled = 1` (chế độ cloud), nên máy khách ở chế độ local không phình hàng đợi; xoá dòng luôn xoá `sync_map` (SQLite có thể cấp lại id đã xoá cho dòng mới — không được thừa hưởng uuid cũ).
- **Bảng đồng bộ:** `products`, `customers`, `suppliers`, `documents`, `document_lines`, `stock_movements`, `product_aliases` (khoá = chuỗi tên), `ignored_lines` (khoá = chuỗi), `document_skipped_lines`, `meta` chỉ các khoá dùng chung (`low_stock_default`, `freed_codes`, `count_checked`, `skipped_lines_backfilled`, `product_code_max`). **Chỉ của từng máy:** `scanned_files`, `hidden_inputs`, `app_log`, `locations` (cố định), các khoá meta `cloud_*`, `last_*`, `device`.
- **Trên cloud:** bảng thật cùng tên cột, khoá `uuid` (bảng có khoá chuỗi giữ chuỗi), thêm `rev` (số thứ tự máy chủ, để kéo "từ lần trước"), `deleted` (xoá mềm để báo cho máy khác), `updated_at`, `origin` (máy nào ghi).
- **Đẩy lên:** một lần đẩy = một lô trong **một transaction**, gửi lại không nhân đôi (upsert theo uuid); phiếu + dòng + biến động luôn đi cùng nhau.
- **Trùng mã khi offline** (người dùng chốt 11/11): **đánh số lại phiếu đến sau** (HV/CH/DT/SP lấy mã kế tiếp còn trống), app báo "phiếu … của máy … đã đổi thành …" và xuất lại file Excel hàng về theo mã mới. Phiếu giao hàng: mã lấy từ giấy, không do app cấp — cùng file (cùng `source_hash`) trên 2 máy = một phiếu; khác file trùng mã = luồng "Nhập thành đơn riêng" hiện có. `product_code_max` gộp bằng giá trị lớn nhất.
- **Migration dựng lại bảng** (như 008/009) làm mất trigger: có test kiểm mọi bảng đồng bộ còn đủ trigger sau `migrate`.

## Cách làm — lát cắt, có kiểm chứng TRƯỚC khi viết lại
0. **Nền (làm ngay, không phụ thuộc quyết định):** mạng ra khỏi luồng giao diện (đo: refresh token 2,1 s + đọc trạng thái 1 s đứng hình mỗi lần mở app, mỗi 3 phút và mỗi lần Quét lại) ✔ xong; nhớ kích thước cửa sổ ✔ xong.
1. **Lược đồ + chuyển dữ liệu một lần** từ một *bản sao* dữ liệu thật; đối chiếu **tồn theo mặt hàng × nơi** với SQLite làm tổng độc lập.
2. **Test song song từng thao tác** (mẫu `tests/test_web_stats.py`): cùng đầu vào chạy qua lõi Python và qua RPC, đòi cùng bộ biến động.
3. **Đổi từng đường ghi của app sang RPC**, mỗi lát đổi cả web cùng lúc, rồi mới gỡ "hộp thư + lệnh của chủ".
4. Hàng đợi offline + xung đột; kéo bản sao SQLite hằng ngày; hoàn tác bằng phiếu đảo.

Ước lượng thật: nhiều tuần, đụng gần hết `core/`. Mỗi lát phải qua test song song trước khi sang lát sau.

## Tiến độ
- Bước 1–3 (bảng thật, đồng bộ 2 chiều, đồng bộ nền trong app): xong 11/11/2026.
- Bước 4 (12/11/2026): chủ ghi trên web qua `cloud/supabase/009_web_rpc.sql` (10 hàm, mỗi hàm làm lại đúng một hàm lõi, kiểm song song ở `tests/test_cloud_web_rpc.py`); web đọc bảng thật, bố cục giống app; nhân viên vẫn gửi yêu cầu chờ duyệt. Giờ của phiếu do web ghi lấy theo đồng hồ máy chủ đổi sang giờ cửa hàng (`meta.clock_offset_min`). Hộp thư cho lệnh của chủ (`cmd_*`) không dùng nữa, gỡ sau khi người dùng xác nhận.
- Bước 5 (12/11/2026, 2 phần đầu): **Hoàn tác** khi dùng dữ liệu chung = huỷ phiếu vừa lưu trên chính máy này (hàng về, chuyển hàng, dùng thử, kiểm kê), đúng đường Huỷ phiếu, rồi đồng bộ như mọi thay đổi (`core/undo.py` `cloud_*`, khoá meta `cloud_undo_doc` riêng từng máy, mỗi điểm hoàn tác mới xoá nó). Thao tác khác (sửa phiếu, gộp, sửa mặt hàng, duyệt Cần xử lý…) không hoàn tác được trên dữ liệu chung: sửa tay. **Bản sao mỗi ngày**: sau lần đồng bộ thành công đầu tiên trong ngày, app chép `sao-luu/DiBeKho_dulieu-chung_<ngày>.sqlite` (có cả phần web và máy khác ghi; tính chung vào giới hạn 10 bản). Không cần SQL mới.
- Gỡ lệnh của chủ (`core/cloud/commands.py`, hẹn giờ lệnh chủ) và bản gương (`mirror.py`, `push_mirror`) sau khi người dùng xác nhận bước 4 (12/11/2026). Việc chúng làm kèm được giữ: hỏi yêu cầu nhân viên mỗi 3 phút, báo "đã vào sổ" lên web sau mỗi lần đẩy, sao lưu lên Storage khi bấm Đồng bộ ngay và lúc tắt app. Điện thoại chỉ xem bảng Tồn kho.
- ★ Mặt hàng mới khi nhập hàng về trên web (13/11/2026, SQL `010_web_receipt_new_products.sql`): `web_receipt` nhận dòng `{"new": {...}}`, tạo mặt hàng trong cùng giao dịch với phiếu như `receipts.save` (phiếu lỗi không để lại mặt hàng, không mất mã); trước khi gửi, web hỏi mặt hàng "trông giống" bằng `webapp/dupes.js` (chép `catalog.find_possible_duplicates`, kể cả `difflib`), dùng luôn cho Cài đặt → Thêm mặt hàng. Chỉ chủ; yêu cầu của nhân viên vẫn chỉ mặt hàng có sẵn.
- Gói `.dibekho` trên web (13/11/2026, người dùng chọn "web tự làm gói"): `webapp/package.js` xuất từ `sync_pull(0)` / nhập bằng một `sync_push` như `core/cloud/admin.py`, kiểm song song với app ở `tests/test_web_package.py` (Node chạy đúng code của trang; Chrome headless bấm nút dưới CSP thật). Điện thoại: mỗi mặt hàng một thẻ (soi bằng evon).
- Bước 5 xong (12/11/2026): **khôi phục bản sao lưu (trên máy hoặc từ Cloud), nhập gói, xoá toàn bộ** khi bật dữ liệu chung = thay toàn bộ dữ liệu chung (`core/cloud/admin.py`, `ui/shared_admin.py`). Hỏi rồi sao lưu trước; dựng file mới riêng; **một lần gửi** `sync_push` (008) đánh dấu xoá mọi dòng đang có và ghi mọi dòng của file mới trong cùng một giao dịch có khoá (không cần SQL mới: chỉ mục không trùng chỉ tính dòng chưa xoá, ghi đè dòng đã xoá thì dòng sống lại); Cloud nhận xong mới thay file trên máy. Có máy khác/web ghi chen giữa → từ chối, không đổi gì. Máy còn thay đổi chưa gửi hoặc còn thay đổi trùng → từ chối. Máy khác tự kéo về ở lần đồng bộ sau. Yêu cầu nhân viên đang chờ có thể trỏ tới mặt hàng không còn.
