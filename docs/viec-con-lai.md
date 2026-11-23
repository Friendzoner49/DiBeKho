# Việc còn lại của bản Swift (lập 17/11/2026, sau giai đoạn 3)

Viết cho anh/chị và cho phiên làm việc tiếp theo. Kế hoạch gốc: `CLAUDE_swift_plan.md` (chỉ trên máy, thư mục
`K:\HeThongSonDiBe`). Tình trạng chi tiết từng bước: mục "17/11/2026" của file đó.

## Đã xong (giai đoạn 0–3, 5 và `.dmg`; chi tiết ở mục cuối file)

- Giai đoạn 0–2: xem dữ liệu, bộ đọc phiếu Excel (khớp Python).
- Giai đoạn 3: ghi hàng về, chuyển, kiểm kê, dùng thử, huỷ/sửa; quét phiếu giao hàng + **Cần xử lý**; **Phiếu xuất kho**
  (lưu, xoá hẳn); file Excel của hàng về và phiếu xuất (bộ ghi .xlsx bằng Swift); chọn file hàng về để nhập; file hàng về
  trong `input/`; sắp xếp theo cột. 46 test khớp Python từng bước, file .xlsx so bằng openpyxl trên CI.

## Làm ngay đầu phiên sau: sửa theo lần thử của anh/chị

Anh/chị thử trên dữ liệu thật (mục 0, 0b… của `docs/thu-tren-mac.md`) rồi gửi lại. Những việc **chưa ai bấm thử thật**:
Lưu phiếu xuất, ★ mặt hàng mới, xoá hẳn, Chọn file để nhập, Xem và nhập / Bỏ / Ẩn, sắp xếp cột, quét phiếu thật, mở file
bằng Excel/Numbers, in A4, gõ Telex, khoá chung với bản Python, ⌘Q giữa lúc đang quét (có thể hiện thông báo lỗi).

## Câu hỏi đang chờ anh/chị trả lời

1. **Cột Tồn chưa ghim** (bảng Tồn kho co các cột theo bề rộng cửa sổ nên luôn thấy Tồn). Chấp nhận, hay làm ghim thật
   như bản Python (một bảng phụ dính mép, đồng bộ cuộn)?
2. **Lỗi bản Python #1:** `deliveries._is_done()` trả số id thay vì đúng/sai → phiếu "Giữ bản cũ" chuyển qua lại giữa
   `phieu-giao-hang` và `da-xu-ly` mỗi lần quét. Vá: `bool(...)` + 1 test.
3. **Lỗi bản Python #2:** `excel/receipt.py` ghi ngày `DD/MM/YYYY` (D hoa) → Quick Look/Numbers trên Mac hiện `319/11/2026`.
   Vá: chữ thường `dd/mm/yyyy` + 1 test. (Khách Mac mở file hàng về bằng xem trước sẽ thấy sai ngày.)

## Giai đoạn 4 — Cloud (đã viết 20/11/2026, CI xanh 92 test = biên dịch được, app dựng được; ⚠ CHƯA thử với Cloud thật; chỉ phần gộp hai chiều có golden)

Đã có: đăng nhập (địa chỉ + mã kết nối gõ trong app, lưu `config.json` cùng khoá với bản Python, **không** dùng Keychain),
kéo/gộp/đẩy hai chiều (`Replica`, `TwoWay`, golden `GoldenCloud`), chọn bản giữ khi trùng, nhân viên gửi chờ duyệt và chủ
duyệt/từ chối trong Cài đặt → Cloud, đồng bộ nền (60 giây / 5 giây sau thay đổi), sao lưu `.sqlite.gz` + phiếu gốc lên Storage
(«Đồng bộ ngay»). Tài khoản chỉ-xem bị từ chối đúng như bản Python (không có đường chỉ-xem trong app: thử bằng tài khoản
Nhân viên trên thư mục dữ liệu chưa nối). Cloud luôn bật: đăng nhập trước khi mở cửa sổ (21/11/2026, không còn bản thử).

Còn thiếu:
- **Yêu cầu từ web**: đã viết (`WebInbox`, mục «Yêu cầu từ nhân viên (web)» ở Cần xử lý, máy chủ): hàng về, phiếu giao (file Excel), kiểm kê → xem rồi vào sổ / từ chối; xác nhận sau khi đẩy. CI xanh (test chỉ-Swift); ⚠ chưa chạy với Cloud thật; đã chuyển sang Cần xử lý 20/11 (CI xanh, ⚠ chưa thử trên Mac).
- **Khôi phục từ bản sao lưu Cloud** và tải lại phiếu gốc: ✅ viết 21/11 theo yêu cầu chủ dự án (`CloudRestore.swift`; test `CloudRestoreTests` phần không cần mạng). CI xanh run 44843766991; ⚠ chưa chạy với Cloud thật.
- `export_renamed`: đã viết (`TwoWay.exportRenamed`, gọi sau mỗi lần gộp). ⚠ chưa có golden (chỉ ghi file).
- Gửi nhật ký lên Cloud: ✅ viết 21/11 (`CloudLogs.swift`, che thông tin khớp Python bằng golden `tools/gen_logs.py`; tách theo tài khoản do máy chủ). Còn: `backfill_currency`/`fill_rates`.
- Việc chạy ở cửa sổ chính của Python, chỉ máy chủ: `backfill_currency`, `fill_rates` (đơn tệ: tỷ giá, `fx.json`, nguồn
  tỷ giá FXRatesAPI — anh/chị còn việc đọc điều khoản), `missing_copies`. Hiện Swift ghi loại tiền ngay nhưng **không điền tỷ giá**.
- Đồng bộ nền + cảnh báo khi mất mạng; khoá chung `data/dibekho.lock` giữ nguyên.
- Test: PGlite như phía Python (`tests/pg`), hoặc golden từ `tools/` chạy lõi Python.
- Khi xong: bản Swift **thay thế** việc đẩy của bản Python → quyết định cách hai app cùng chung `sync_outbox` / cờ đồng bộ.

## Giai đoạn 5 — Cài đặt, dữ liệu, ngôn ngữ (phần lớn đã làm, xem mục cuối)

- **Ba ngôn ngữ vi/en/zh** (đang cố định tiếng Việt; chuỗi đã sinh từ `i18n/*.json`, còn vài chuỗi viết thẳng:
  Thống kê, chi tiết, dải BẢN THỬ, các thông báo mới của giai đoạn 3b/3c) + chọn ngôn ngữ lần đầu.
- **Nút ₫ | ¥** toàn app (`ui/currency_switch.py`, `core/fx.py`): Đơn hàng 2 cột tiền, Thống kê, **Phiếu xuất kho gõ giá bằng tệ**.
- **Cài đặt** (kiểm lại những gì Swift đã có, thiếu thì làm): thư mục làm việc (chọn/đổi), cỡ chữ (hiện chỉ đọc từ `config.json`
  của Python), ngôn ngữ, Giấy phép mã nguồn mở (kèm giấy phép GRDB, ZIPFoundation), nhật ký ẩn (bấm 3 lần số phiên bản).
- **Danh mục mặt hàng** (tab Cài đặt): Thêm/Sửa/Xoá, ngừng dùng, ngưỡng báo động, **Tên trên phiếu đã học** (quên/đọc lại),
  gộp mặt hàng trùng, gộp khách hàng, khôi phục mặt hàng đã xoá (`core/catalog.py`).
- **Nhập file ở `input/`:** ✅ làm xong 20/11/2026 (danh mục Excel, dữ liệu gốc xuất/nhập, gói `.dibekho`; Cần xử lý có nút nhập riêng). CI xanh; ⚠ chưa thử trên Mac; gói chưa so với gói do Python tạo.
- **Xuất Excel:** ✅ Thống kê (4 sheet) và theo khách (theo bộ lọc ngày của cửa sổ khách). ⚠ chưa so bằng mắt với file Python.
- **Sao lưu** (10 bản, dọn 30 ngày, bảo trì 2 tuần), khôi phục từ sao lưu, **Đặt lại dữ liệu** (đặt lại tồn kho / xoá toàn bộ,
  hỏi 2 lần), Gỡ app (`core/uninstall.py`), lần đầu mở không có thư mục làm việc (máy Mac chưa từng dùng bản Python).
- **Ghim cột** (nếu anh/chị chọn làm thật) và các tinh chỉnh bảng: Kiểm kê, Chuyển hàng.
- Gõ tiếng Việt/Trung: Telex một lần bấm vào ô, số toàn độ rộng `１２，５`, phông chữ Hán.

## Giai đoạn 6 — Đóng gói, cập nhật, bàn giao (chưa làm)

- `.dmg` ✅ dựng trên CI cùng với zip (`scripts/make_app.sh`, tên cố định `DiBeKho-Swift-mac-arm64.dmg`); app chưa ký (không mua Apple Developer): "Vẫn mở" lần đầu; thử **Sparkle** (tự cập nhật,
  không bị quarantine) — ⚠ cần thử trên Mac.
- Hướng dẫn cho khách (vi/en/zh): `docs/huong-dan-su-dung.md` ở repo công khai viết theo bản Python, phải rà lại theo bản Swift.
- **Chạy song song với bản Python 2–4 tuần** trước khi bỏ bản Python trên Mac.
- **Bàn giao sang repo công khai chỉ khi anh/chị xác nhận đã thử xong mọi tính năng:** rà quyền riêng tư (`privacy_scan.py`,
  `check_links.py`, không chép tên khách/đường dẫn máy), giấy phép, README, tag mới, **hỏi trước khi phát hành**.
- Mac cài bản mới thay bản Python: mở được dữ liệu cũ không cần nhập lại (tên thư mục `DiBeKho`, `config.json`, `data/kho.sqlite` giữ nguyên).

## Quy tắc làm việc (nhắc cho phiên sau)

- Máy này là Windows: **không biên dịch được Swift**. Mỗi lần sửa: commit + push rồi chạy CI (`gh workflow run build.yml`;
  thêm `-f screens=true` để có app tải về + ảnh chụp, ~4 phút). Ảnh xem bằng công cụ đọc ảnh, không dán base64.
- Giữ nguyên với Python bằng **golden**: `tools/gen_*.py` chạy lõi Python (`uv --project K:/HeThongSonDiBe run python -X utf8
  tools/gen_xxx.py K:/HeThongSonDiBe`) → file `Tests/.../Generated/Golden*.swift` + fixture. Sinh lại làm đổi byte các file
  .xlsx → **commit fixture và golden cùng lúc**. File .xlsx do Swift ghi được so bằng openpyxl trên CI (`tools/check_xlsx.py`).
- Chỉ dữ liệu giả (cửa hàng giả của `Golden.swift`); không commit dữ liệu khách. Tác giả commit `Friendzoner49`.
- Chuỗi giao diện lấy từ `i18n/*.json` của Python (test kiểm mọi `t("…")` có khóa). Thêm chức năng ghi → ghi nhật ký `model.write("tên")`.
- Mọi đường dẫn đọc từ DB hay thư mục phải nằm trong thư mục làm việc (`Deliveries.validRel`, `inside`).
- Sau mỗi phần xong: cập nhật `CLAUDE.md`, `CLAUDE_swift_plan.md`, memory (như các lần trước), và hỏi advisor trước khi báo xong.

## Gợi ý thứ tự

1. Sửa theo lần thử dữ liệu thật + trả lời 3 câu hỏi ở trên.
2. Giai đoạn 5 phần nhỏ, ít rủi ro, dùng lại hạ tầng có sẵn: nút ₫ | ¥, Cài đặt/Danh mục, nhập danh mục + dữ liệu gốc,
   xuất Excel Thống kê, ngôn ngữ.
3. Giai đoạn 4 Cloud (rủi ro cao nhất: đụng dữ liệu dùng chung của khách; làm trên bản thử/Supabase thử trước).
4. Gói dữ liệu + sao lưu + đặt lại (phụ thuộc Cloud: "thay dữ liệu chung" ảnh hưởng mọi máy).
5. Giai đoạn 6.

## 19/11/2026: bắt kịp Python 0.6.2 (code + golden; CI xanh 20/11)

Đã làm bên Swift (cần một lần `swift test` trên Mac/CI để biết có lỗi biên dịch):
- Migration 012 (`customers.tax_code`, `customers.email`) và trigger đồng bộ: sinh lại bằng `tools/gen_from_python.py`.
- Bộ đọc phiếu: nhãn MST/email, MST dạng số, phiếu mẫu mới (`Notes/17…20`); lưu khách: MST/email chỉ điền ô trống, `known` (khách của cùng file đọc lại).
- File Phiếu xuất kho theo mẫu mới của khách (dòng 6 MST/email, tiêu đề dòng 9, gộp ô mới, SimSun, căn giữa khi in, lề dưới 0) và `XlsxWriter` có `bottomMargin`, `centerHorizontally`.
- Phiếu xuất kho: ô MST/Email, nút ＋ Khách hàng mới…; **Sửa phiếu xuất kho…** (`Issues.load/edit`, file cũ vào `da-sua`, tồn của phiếu cũ được tính là còn trống trong cảnh báo thiếu hàng).
- Khách hàng: cột MST/Email, tìm theo MST/email, Chi tiết khách có MST/Email và **Sửa thông tin khách hàng…** (`Catalog.updateCustomer`, hỏi khi trùng SĐT/tên).
- Golden mới: `edit_*`, `issue_edit`, `cust_*` trong `tools/gen_issue.py`.

**Gộp khách hàng…** đã làm (20/11/2026, CI xanh): `Catalog.mergeCustomers` khớp Python `merge_customers` bằng golden (`merge_*` trong `tools/gen_issue.py`), nút ở trang Khách hàng (chọn nhiều dòng bằng ⌘/Shift), hộp chọn tên chung.

Còn thiếu: sửa phiếu xuất trong cùng giao dịch dựa vào `queue.write` của `model.write` (Swift không cần savepoint riêng vì mọi việc chạy trong một lần ghi, nhưng chưa thử trên dữ liệu thật).

## 19/11/2026 (từ bản Python)

- Phiếu xuất kho (mã A…/W…) sửa được: Python `core/issues.edit` xoá bản cũ + ghi bản mới cùng mã trong một giao dịch, file cũ vào `output/phieu-xuat/da-sua/`. Bố cục file Excel không đổi; Swift cần cùng chức năng khi làm màn Phiếu xuất. `db.transaction` bên Python nay lồng được (savepoint).

## 20/11/2026: dữ liệu gốc, Excel theo khách, `.dmg`

Đã làm (CI xanh 20/11/2026; ⚠ chưa thử trên Mac): `MasterData` (xuất/nhập 3 trang, khớp tồn kho theo mã → tên → vị trí, nhập có sao lưu trước),
Inbox nhận 4 loại file, `Report.exportCustomer`, `.dmg` trong `make_app.sh`. Test của ba phần này là **test chỉ có ở Swift**
(`MasterDataTests`, `CustomerExportTests`), không phải golden từ Python. Chưa làm:
rà ảnh chụp cửa sổ thật. (Bộ lọc ngày trong cửa sổ khách: đã thêm 20/11/2026, CI xanh.)

## 20/11/2026: đối chiếu với README và hướng dẫn công khai của bản Python (`Friendzoner49/DiBeKho`)

Đã có bên Swift và khớp mô tả: quét phiếu + Cần xử lý, Hàng về, Phiếu xuất kho (sửa, xoá hẳn), Kiểm kê/Chuyển hàng/Dùng thử, ghi chú tồn kho, Tra cứu, đơn hàng, khách (Excel, lọc ngày, gộp), Thống kê + Excel, Danh mục mặt hàng (ngưỡng báo động, gộp, tên đã học, nhập Excel), dữ liệu gốc xuất/nhập, gói `.dibekho`, sao lưu/khôi phục/đặt lại, khôi phục mặt hàng đã xoá, ₫ | ¥, đổi ngôn ngữ, Gỡ app, Cloud (đăng nhập, đồng bộ, nhân viên/chủ duyệt, yêu cầu từ web).

**Chưa có so với mô tả công khai** (không tự làm hết: phần Cloud đụng dữ liệu chung nên cần chủ dự án quyết):
- Cài đặt → Cloud: Khôi phục từ Cloud… và Gửi nhật ký sử dụng: ✅ viết 21/11 (⚠ chưa biên dịch). **Tài khoản** (tạo, đổi vai trò, đặt lại mật khẩu, thu hồi) chỉ có trên **trang web** (`webapp/accounts.js`), bản Python trên máy cũng không có: không phải chỗ thiếu.
- ✅ viết 20/11 (CI xanh, ⚠ chưa thử trên Mac): **Tự kiểm tra bản mới** (`Update`, `Updater`; hỏi GitHub releases của `DiBeKho-mac`, tải `DiBeKho-Swift-mac-arm64.dmg` có nối tiếp + kiểm sha256, mở .dmg). **Kho còn private nên GitHub trả 404 → báo «chưa kiểm tra được»; chạy được khi kho công khai** (hoặc đặt `DIBEKHO_UPDATE_URL`). Số phiên bản trong `packaging/Info.plist` còn 0.0.1: phải tăng theo mỗi bản phát hành thì mới so được.
- ✅ viết 20/11 (CI xanh, ⚠ chưa thử trên Mac): phím **⌘F** cho Tra cứu; bộ lọc **Loại tiền** ở Danh sách đơn hàng; dòng trạng thái Cloud góc phải; **thay đổi nhân viên chờ duyệt và yêu cầu từ web ở Cần xử lý**; hộp chọn ngôn ngữ và thư mục làm việc ở lần mở đầu tiên (`FirstRun`, có test).
- Màn hình còn thiếu: (cột «Tiền hàng (CNY)» riêng và chuột phải một đơn → Đọc lại cả phiếu: đã có từ đợt 2, 21/11); cột Tồn ghim: không làm (Tồn luôn hiện vì bảng vừa cửa sổ); «Nhập dữ liệu» ở Cần xử lý đã có từ trước; đăng nhập bắt buộc khi mở app.
- ✅ viết 20/11 (CI xanh, ⚠ chưa thử trên Mac): Phiếu xuất kho gõ giá bằng tệ (giống Python: tỷ giá lúc mở cửa sổ, lưu bằng ₫); en/zh thêm cho cửa sổ chi tiết, Cài đặt, hộp yêu cầu nhân viên/web, đặt lại/sao lưu (dùng `tr(vi, en, zh)` khi Python không có khoá). Còn sót vài chữ tiếng Việt ở hộp nhỏ (vd. thông báo trong `CloudRunner`, `Forms`).
- Nhập gói `.dibekho`: chưa có trên Mac (đã bỏ bản thử 21/11/2026; Python: thay dữ liệu chung, chỉ Chủ, cần mạng).

Hướng dẫn công khai viết cho khách dùng bản Python; chưa viết bản cho Swift (giai đoạn 6).

## 20/11/2026: đối chiếu giao diện với bản Python (ảnh chụp bản Python từng màn)

Đợt 1 (viết 20/11, CI xanh 21/11 run 44831954081): xem mục 11 của `docs/thu-tren-mac.md`.

| Chỗ | Bản Python | Swift trước | Đợt 1 |
|---|---|---|---|
| Bảng hàng Phiếu xuất kho / Nhập hàng về | khung, kẻ ô, số dòng, ▲▼, cột ✕ | không khung; Hàng về tràn trái | ✅ `FormTable.swift` |
| «Tên trên phiếu đã học» | cây theo đơn | mở ra trống | ✅ ⚠ (danh sách phẳng, id riêng) |
| Bảng danh sách | kẻ ô, xen kẽ, cột vừa nội dung, cột 2 giãn | cột rộng cố định | ✅ `DataTable` |
| Dòng trạng thái | cạnh nút trên cùng | dưới cùng + dòng ms | ✅ |
| Cài đặt → Chung | thứ tự + Đổi thư mục + Đặt lại dữ liệu | thiếu | ⚠ chưa có Đặt lại dữ liệu (đã bỏ bản thử 21/11/2026) |
| Cài đặt → Danh mục mặt hàng | hai khung nhóm | tiêu đề trang | ✅ |
| Nút bấm | to (Qt, 120%) | nút macOS nhỏ hơn | ✅ to hơn ~10% (`AppButtonStyle`), vị trí giữ nguyên |
| Ô Ngày xuất / Ngày về | rộng hết hàng | ô ngày macOS cố định | còn (ô ngày của macOS không giãn) |

Đợt 2 (viết 21/11, CI xanh 21/11 run 44831954081): xem mục 12 của `docs/thu-tren-mac.md`.

| Chỗ | Bản Python | Swift trước | Đợt 2 |
|---|---|---|---|
| Tra cứu | 3 khung trong vạch kéo, MST/Email, ✕ | bảng thấp cố định, thiếu MST/Email | ✅ |
| Kiểm kê | cột theo nội dung, cuộn ngang | bóp cột vừa cửa sổ | ✅ (tiêu đề 1 dòng thay vì 2) |
| Đơn hàng | lọc loại / ngày / khách / mặt hàng, chuột phải Đọc lại | chỉ ô tìm + đã huỷ + loại tiền; ô tìm dùng chung với Tồn kho | ✅ `OrderQueries.documents`, golden `documents_*` |
| Phiếu chuyển / dùng thử / kiểm kê | cùng cửa sổ Đơn hàng, cố định loại | cửa sổ riêng thiếu lọc ngày | ✅ |
| Khách hàng | thứ tự cột, gợi ý, ✕ | MST/Email giữa bảng | ✅ |
| Thống kê | Kỳ 5 loại, phạm vi, Chia theo, biểu đồ | 3 loại, không lọc, không biểu đồ | ✅ `Stats.Filters`, `buckets`, `dailyOut` + Excel cùng phạm vi; golden `fsummary_*`, `fmoney_*`, `fdaily_*`, `per_bucket_*`… (biểu đồ Swift Charts, chưa so ảnh) |
| Chi tiết đơn / khách / mặt hàng | nút dưới, Đóng phải, dòng tổng, liên kết khách, nháy đúp | nút trên cùng, bảng phẳng, không nháy đúp | ✅ golden `customer_*`, `customer_lines_*`, `count_differences_1`; cây đơn của khách = danh sách phẳng có dòng đậm |
| Cần xử lý | thứ tự khung | yêu cầu nhân viên/web lên đầu | ✅ |
| Chuyển dữ liệu và sao lưu | 3 khung, danh sách sao lưu | khung tự đặt, chọn file sao lưu | ✅ (khung riêng Swift để sau) |
| Cloud | Đồng bộ ngay, Khôi phục từ Cloud…, Gửi nhật ký | không có 2 mục sau | còn (đã biết, chờ chủ dự án) |

Đợt 3 (viết 21/11, CI xanh 21/11 run 44831954081): hộp thoại nhỏ ảnh 23–31, xem mục 13 của `docs/thu-tren-mac.md`. Đợt 4 (viết 21/11, CI xanh run 44831954081): ảnh 32–37 chụp thêm từ bản Python, các hộp nhập Excel / khôi phục / kiểm kê web, xem mục 14 của `docs/thu-tren-mac.md`; Chọn file để nhập… nhận cả dữ liệu gốc và danh mục. **Hết phần rà giao diện**; còn: so ảnh CI thật sau lần chạy tới. Còn lại: macOS hỏi «tìm thiết bị trong mạng nội bộ» khi mở cửa sổ Đơn hàng trên CI (ảnh 07 của CI ngày 19/11, chưa rõ nguyên nhân, có thể do Cloud/Updater).


## 21/11/2026: rà lần cuối so với bản Python (chữ giao diện)

So mọi khoá chữ bản Python dùng ở `ui/*.py` và `app.py` với code Swift (702 khoá; 32 chưa dùng). Phần còn khác, có lý do:
- **Đăng nhập bắt buộc lúc mở app** (`app.sign_in_and_link`, `login.offline`, `login.other_queue`): bản Swift để Cloud tự chọn trong thời gian thử (đăng nhập ở Cài đặt → Cloud). Làm khi bản Swift thay bản Python.
- **Cảnh báo thư mục làm việc nằm trong iCloud/OneDrive** (`app.cloud_warning`), lỗi tạo thư mục, lỗi ngoài dự kiến: chưa làm.
- **Đặt lại / khôi phục sao lưu / nhập gói `.dibekho`** (`reset.*`, `backup.*`, `transfer.*`): chưa có trên Mac từ khi bỏ bản thử (21/11/2026). Muốn có thì chép `settings_page.reset_*` và `shared_admin.replace_shared_data` (thay dữ liệu chung trên Cloud), có test, thử với Cloud thử trước.
- `license.hint` (bản Python nói về Qt): bản Swift có câu riêng. `note.edit_tip` (gợi ý khi rê chuột ô ghi chú): chưa có. `settings.uninstall_done_win`: chỉ Windows.
- Khoá ghép tên (`receipt_form.source_*`, `web.kind_*`) có dùng, chỉ là công cụ rà không thấy.

## 21/11/2026: Danh mục mặt hàng ở Tra cứu, phát hành chung với bản Python

- Bản Python và web đã chuyển danh mục sang **Tra cứu → Danh mục mặt hàng** giống bản Swift (`ui/catalog_page.py`). Tab thứ hai của Cài đặt giờ tên «Tên trên phiếu đã học». Khoá `settings.tab_products` đã bỏ khỏi `i18n/*.json`. Swift không dùng khoá này nữa; lần chạy `tools/gen_from_python.py` tới sẽ xoá nó khỏi `Strings.swift`.
- Từ tag Python kế tiếp (v0.6.3), `build.yml` ở `main` dựng thêm bản Swift từ nhánh `Mac_swift`, rồi đính file `DiBeKho-Swift-mac-arm64.dmg` vào cùng Release. README có nút **macOS Swift** trỏ vào file đó. Số phiên bản app = số của tag (`DIBEKHO_VERSION` → `make_app.sh`), bộ cập nhật hỏi repo công khai `Friendzoner49/DiBeKho`. ⚠ Chưa chạy lần nào trên CI thật.

## 21/11/2026: Phiếu xuất kho bằng nhân dân tệ (cả 3 bản)

- Python, web và Swift: công tắc ở ¥ thì phiếu xuất là phiếu tệ (`IssueInput.currency = "CNY"`, `fx_rate` = tỷ giá của cửa sổ). File Excel: tiêu đề cột giá "CNY", định dạng `[$¥]\ #,##0.00`, chữ "… NHÂN DÂN TỆ … XU". `last_price` đổi giá sang đúng loại tiền. Chuỗi `issue.cny_hint` đổi nội dung (đã sinh lại `Strings.swift`).
- Golden: `tools/gen_issue.py` thêm phiếu `issue_cny` (+ `XlsxRef/issue_cny.json`); `IssueTests.swift` thêm đúng bước đó. ⚠ Chưa chạy trên CI.
- Web cần SQL 022 (`web_issue_money`) chạy trên Supabase trước khi tải web lên.

## 21/11/2026: đơn nháp và số Excel không dấu nghìn (đã chép sang Swift)
- Excel: `issue_note.MONEY = '[$VND]\ 0'`, `MONEY_CNY = '[$¥]\ 0.00'`, `report.MONEY = "0"`, dòng tiền trong file thống kê không dấu nghìn (Swift `Report.dong/plain`).
- Đơn nháp: tiêu đề `issue_note.TITLE_DRAFT` ("… (NHÁP)"), `issues.save_draft / load_draft / close_draft`, thư mục `output/phieu-xuat/nhap/`, quét phiếu từ chối file nháp (`deliveries.DRAFT_REFUSED`). Swift: `Issues.saveDraft/loadDraft/closeDraft`, `DraftTests`. ⚠ chưa biên dịch lúc viết.

## 21/11/2026: phiếu gốc từ Cloud, tự điền khách cũ (Python 9324e8e)
- Python: `deliveries.missing_originals` (mọi phiếu thiếu bản sao, phiếu chưa rõ tiền trước), cửa sổ chính tải nền tất cả; «Mở file gốc» tải đúng file đó nếu còn thiếu, lỗi mạng báo `doc.original_not_fetched` (chuỗi mới, đã sinh lại `Strings.swift`). Swift: `Deliveries.missingOriginals`, `CloudBackup.fetchNamed`, `CloudRunner.fetchMissingOriginals/fetchOriginal`, `OriginalsTests`. ⚠ chưa biên dịch lúc viết, chưa thử Cloud thật.
- Swift Phiếu xuất kho: gõ tên khách cũ (không cần «· SĐT», không phân biệt hoa thường) là điền SĐT, địa chỉ, MST, email và giá (`Issues.pickedCustomer`); Python đã làm được nhờ ô chọn tự hoàn tất, web khớp đúng tên.
- 21/11/2026 (sau): chọn khách từ ▾ không điền gì (SwiftUI `Menu` cạnh `TextField` không đưa lựa chọn về form, CI bấm chuột thật thấy lại). `ComboField` giờ là `NSComboBox` (Phiếu xuất kho, Hàng về). CI bước «Phiếu xuất kho fills an old customer» bấm thật (`tools/ci_click.js`, `tools/ci_pick_customer.applescript`) và chụp `screen-19-issue-*.png`: chọn và gõ tên đều điền đủ (run 44945288756). Release v0.6.5 dựng lại (tag giữ nguyên).
- 22/11/2026: cửa sổ chặn (`Windows.show(modal: true)` = `NSApp.runModal`) có hai bẫy, CI bấm thật đã thấy cả hai: (1) mục của SwiftUI `Menu` và lệnh của `NSMenu` đến sau khi menu đóng, ở chế độ run loop mà phiên chặn không chạy, nên không bao giờ tới → dùng `PopMenuButton` (chạy mục được tô sáng khi menu đóng); (2) cửa sổ chặn mở ngay trong lúc nút/menu đang xử lý cú bấm thì SwiftUI không vẽ lại (danh mục trống) → luôn mở qua `UI.later` (RunLoop.perform ở chế độ default + modalPanel, KHÔNG eventTracking: mở ở đó làm treo app). `Picker` thì chạy bình thường. Kịch bản CI: `tools/ci_dialogs.sh`, ảnh `screen-20-*.png`.
