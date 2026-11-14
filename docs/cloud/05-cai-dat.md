# Cài đặt DiBeKho Cloud từ đầu (tự làm, ~20 phút)

Dùng khi dựng lại project Supabase mới, hoặc chuyển sang tài khoản khác. Thiết kế: `06-cloud-la-goc.md`.
Không bao giờ đưa **service_role key** hay mật khẩu database vào app, trang web hay repo.

## 1. Tạo project Supabase

1. supabase.com → New project: gói **Free**, vùng **Singapore**, đặt tên tuỳ ý, **Generate a password** rồi lưu mật khẩu database ở nơi riêng (ta gần như không dùng).
2. Mục Security khi tạo: giữ *Enable Data API* và *Automatically expose new tables*, **tick** *Enable automatic RLS*.
3. Authentication → Sign In / Providers: **tắt** *Allow new users to sign up* và **tắt** *Confirm email* (tài khoản chỉ do bạn tạo tay).

## 2. Chạy SQL (SQL Editor → New query → dán → Run), theo thứ tự

1. `cloud/supabase/001_init.sql` — bảng gương, hộp thư web, quyền RLS, hàm `replace_mirror`.
2. `cloud/supabase/002_backups.sql` — kho lưu trữ riêng tư `backups` cho bản sao lưu đầy đủ.
3. `cloud/supabase/003_low_stock.sql` — **chỉ khi project được tạo trước khi có file này** (project mới đã có sẵn trong 001).
4. `cloud/supabase/004_staff_requests.sql` — yêu cầu của nhân viên: kiểm kê và phiếu giao hàng Excel (thêm loại yêu cầu, kho riêng tư `inbox-files`, giới hạn kích thước). **Bắt buộc nếu muốn nhân viên gửi kiểm kê/phiếu giao.**
5. `cloud/supabase/005_full_view.sql` — gương có thêm bảng biến động tồn và vài cột, để web có **lịch sử vào ra, chi tiết mặt hàng/khách, Thống kê**. **Chạy xong thì mở app bấm Đồng bộ ngay một lần** (không thì web chưa có dữ liệu mới). Dự án cài mới đã có sẵn trong 001.
6. `cloud/supabase/006_owner_commands.sql` — lệnh của chủ kiểu cũ qua hộp thư (web mới không dùng nữa, chạy cho đủ thứ tự). Dự án cài mới đã có sẵn trong 001.
7. `cloud/supabase/007_core.sql` + `008_sync_rpc.sql` — bảng thật của **Dữ liệu chung** và đồng bộ 2 chiều.
8. `cloud/supabase/009_web_rpc.sql` — **chủ ghi thẳng trên web** (hàng về, chuyển hàng, dùng thử, kiểm kê, huỷ phiếu, nơi lấy hàng, mặt hàng, gộp khách). **Bắt buộc cho trang web mới.** Chạy lại nhiều lần không sao, **nhưng mỗi lần chạy lại 009 thì chạy lại 010 ngay sau** (009 đặt lại hàm hàng về cũ). Từ 14/11/2026 trang web **không gọi** các hàm này nữa (web chỉ xem); vẫn chạy cho đủ thứ tự.
9. `cloud/supabase/010_web_receipt_new_products.sql` — **"★ Mặt hàng mới" khi nhập hàng về trên web**: mặt hàng mới được tạo cùng lúc với phiếu (phiếu lỗi thì không để lại mặt hàng thừa). Chạy sau 009 (và chạy lại sau mỗi lần chạy lại 009); chạy lại nhiều lần không sao. Chưa chạy thì web báo "người cài đặt cần chạy SQL 010" khi bấm lưu phiếu có ★. Từ 14/11/2026 trang web **không gọi** các hàm này nữa (web chỉ xem); vẫn chạy cho đủ thứ tự.
10. `cloud/supabase/011_accounts.sql` — **quản lý tài khoản ngay trên web** (liệt kê, đổi vai trò, thu hồi quyền; có chốt chặn không tự khoá mình). Chạy sau 009 (dùng một hàm của 009). Chạy lại nhiều lần không sao. Muốn tạo tài khoản và đặt lại mật khẩu trên web thì cần thêm Edge Function ở **mục 5b**.
11. `cloud/supabase/012_web_settings.sql` — cỡ giao diện web dùng chung cho mọi máy (chỉ tài khoản `maychinh` đổi được, ở Cài đặt → Chung). Chạy sau 011.
12. `cloud/supabase/013_return_prices.sql` — hàng khách trả lại có **Đơn giá trả lại** và được trừ khỏi doanh thu (phiếu trả hàng nhập trên web). Chạy sau 010; **chạy lại 009 hoặc 010 thì chạy lại 013**.
13. `cloud/supabase/014_drop_mirror.sql` — xoá các bảng `mirror_*` và hàm `replace_mirror` của mô hình gương cũ (không app/web nào dùng nữa; riêng `mirror_snapshot` giữ 30 bản dữ liệu dạng jsonb). Chạy lại được.

## 3. Tạo tài khoản

Authentication → Users → Add user → Create new user, tick *Auto Confirm User*. Email chỉ là "tên đăng nhập kỹ thuật", không cần có thật:

| Tài khoản | Vai trò | Dùng để |
|---|---|---|
| `maychinh@dibekho.local` | `desktop` | app trên máy chính đẩy dữ liệu, kéo hộp thư, sao lưu |
| `khach1@dibekho.local` … | `viewer` (chỉ xem) hoặc `editor` (xem + tạo file **Phiếu xuất kho**) | trang web — mỗi người một tài khoản riêng. Sếp/quản lý muốn xem trang **Tổng quan** thì cấp vai trò `desktop` |

Gán vai trò (SQL Editor), đổi tên/vai trò cho đúng:

```sql
insert into public.profiles (user_id, display_name, role)
select id, 'May chinh', 'desktop' from auth.users where email = 'maychinh@dibekho.local';
insert into public.profiles (user_id, display_name, role)
select id, 'Nguoi xem', 'editor' from auth.users where email = 'khach1@dibekho.local';
```

Quên mật khẩu: không có email khôi phục. Cách tạo tài khoản từng bước, đổi mật khẩu, đổi vai trò và thu hồi quyền khi nhân viên nghỉ: [07-tai-khoan-va-mat-khau.md](07-tai-khoan-va-mat-khau.md).

### Trang web: chỉ xem, tiếng Việt / 中文 (từ 14/11/2026)

Khi máy chính đã **bật Dữ liệu chung** (app → Cài đặt → Cloud), trang web đọc **bảng thật** trên Cloud. Bố cục **giống app** (thanh bên trái *Tồn kho · Cần xử lý · Tra cứu · Hàng về · Kiểm kê · Cài đặt*, nút cùng tên, cùng chỗ; bấm một dòng để chọn, nháy đúp để mở). Chọn **Tiếng Việt / 中文** ở trang đăng nhập, góc phải trên hoặc Cài đặt → Chung (nhớ trong trình duyệt; chữ ở `webapp/i18n.js`, kiểm bằng `tests/test_web_i18n.py`). Ở trang tiếng Trung, mặt hàng hiện tên Trung nếu có.

**Web không ghi dữ liệu của cửa hàng** (khách yêu cầu 14/11/2026): mọi việc ghi (hàng về, kiểm kê, chuyển hàng, dùng thử, sửa/gộp mặt hàng, gộp khách, huỷ phiếu, chọn nơi lấy hàng, nhập gói) làm trên app. Các cửa sổ ghi cũ của web, yêu cầu của nhân viên (hộp thư `web_inbox`) và gửi file phiếu đã gỡ khỏi trang; SQL 009/010 vẫn nằm trên Supabase (đã chạy thì không sửa), `tests/test_cloud_web_rpc.py` vẫn kiểm. Yêu cầu cũ còn trong hộp thư thì app vẫn duyệt được ở Cần xử lý. Những gì web còn làm:
- **Tổng quan** (`webapp/dashboard.js`, chỉ vai trò `desktop`, là trang mở đầu của vai trò này): doanh thu tiền hàng và số đơn của kỳ (tháng này / tháng trước / quý này / năm nay) so với cùng kỳ trước, số mặt hàng sắp hết và tồn âm, doanh thu 12 tháng, mặt hàng bán chạy, khách mua nhiều, hàng sắp hết, đơn gần nhất. Chỉ tổng hợp dữ liệu mà mọi vai trò đã đọc được ở các trang khác, nên ẩn bằng giao diện là đủ (không cần RLS riêng).
- **📤 Phiếu xuất kho…** (`webapp/issue.js` + `webapp/xlsx.js`, vai trò `desktop` và `editor`): giống app, nhưng trình duyệt chỉ tạo file Excel `PhieuXuat_W160.xlsx` (mã W + số tiếp theo sau mã đơn lớn nhất; app dùng A) (từng ô giống file app tạo, tức khuôn phiếu giao hàng của cửa hàng: tên + địa chỉ công ty lấy từ `meta.note_letterhead` mà app đọc ở phiếu giao hàng và đồng bộ lên; cột ẩn H Mã hàng, I Lấy từ kho; `tests/test_web_issue.py` so từng ô với file app và đọc lại bằng bộ đọc của app). Bỏ file vào thư mục phiếu giao hàng của máy chính thì app mới trừ tồn từng nơi; đọc lại không trừ hai lần.
- Công tắc **₫ | ¥** góc trái dưới (`webapp/fx.js`, như app): ¥ hiện mọi số tiền trên trang bằng nhân dân tệ theo tỷ giá hôm nay (dữ liệu và file tải về vẫn VND); tỷ giá thị trường từ open.er-api.com (miễn phí, không khoá; CSP `connect-src` có thêm địa chỉ này), nhớ tỷ giá và lựa chọn trong trình duyệt.
- **Cài đặt → Sao lưu → Xuất dữ liệu** (vai trò `desktop`, không có trên điện thoại): tải toàn bộ dữ liệu chung thành gói `.dibekho` app mở được (không kèm file Excel phiếu gốc và nhật ký). Trình duyệt tự làm gói bằng `webapp/package.js` + `webapp/vendor/` (sql.js, fflate; MIT); cấu trúc CSDL lấy từ `webapp/schema.js`, sinh bằng `scripts/make_web_schema.py` — **thêm migration thì chạy lại script này** (test báo đỏ nếu quên). Gói schema 10 nên app 0.4.5 của khách không mở được.
- **Cài đặt → Tài khoản** và cỡ giao diện: chỉ tài khoản `maychinh` (mục 5b).

**Điện thoại** (màn hình cảm ứng có cạnh ngắn ≤ 760 px, kể cả khi xoay ngang; máy tính màn nhỏ vẫn có đủ trang): chỉ xem bảng Tồn kho (tên, tồn, Kho tổng, Văn phòng), không có menu. Máy tính bảng và máy tính có đủ trang.

Tất cả tài khoản đăng nhập xem được toàn bộ dữ liệu (tồn, giá, khách). Muốn hạn chế thì cần vai trò riêng — chưa làm.

**Lệnh của chủ kiểu cũ** (`cmd_*` qua hộp thư, SQL 006) và **bản gương** (`mirror_*`, SQL 001/005, xoá ở 014): đã gỡ khỏi app (12/11/2026).

### Web xem được những gì (giống app)

- **Tồn kho**: nháy đúp một mặt hàng → tồn theo nơi, **lịch sử vào ra** có số dư sau từng dòng, khách lấy nhiều nhất, xuất file CSV.
- **Tra cứu → Đơn hàng / Khách hàng / Thống kê**: như app; Chi tiết đơn mở thành cửa sổ (phiếu xuất lấy ở cả 2 nơi ghi nơi của từng dòng).
- Số liệu Thống kê và Tổng quan trên web dùng `webapp/stats.js`, được kiểm tự động bằng `tests/test_web_stats.py` (so với `core/stats.py`), nên hai nơi luôn khớp.
- `tests/test_web_contract.py` cho Chrome thật đi qua trang với vai trò nhân viên, chỉ xem và máy chính (cả bản tiếng Trung): không lệnh ghi nào rời trang, file phiếu xuất trang tạo được app đọc và trừ tồn đúng từng nơi.

## 4. Nối app trên máy chính

Project Settings → API: lấy **Project URL** và **publishable (anon) key** (hai thứ này công khai theo thiết kế).
App → Cài đặt → tab **Cloud**: dán URL, mã kết nối, tên đăng nhập `maychinh`, mật khẩu → **Đồng bộ ngay**.
Từ đó: tắt app tự đẩy, mở app tự kéo phiếu từ web. Mật khẩu không được lưu; app giữ phiên đăng nhập trong `config.json`.

## 5. Trang web (`webapp/`)

1. Sao `webapp/config.example.js` thành `webapp/config.js`, điền URL + publishable key (file này nằm trong `.gitignore`).
2. Thử trên máy: `python -m http.server 8808 --directory webapp` rồi mở http://localhost:8808.
3. Đưa lên mạng (Cloudflare Pages, miễn phí):
   - Dựng bản tải lên: `uv run python scripts/make_web_deploy.py` → thư mục `dist/web/` (có `config.js` và `_headers`: chặn nhúng trang vào trang khác, không giữ bản cũ trong bộ nhớ đệm) và `dist/DiBeKho-web.zip`.
   - Lần đầu: dash.cloudflare.com → **Workers & Pages** → **Create** → tab **Pages** → **Upload assets** → đặt tên dự án (thành địa chỉ `https://<tên>.pages.dev`; **không dùng tên khách**) → kéo thả thư mục `dist/web` → **Deploy site**.
   - Mỗi lần sửa web: chạy lại script, vào dự án → **Create deployment** → kéo thả `dist/web` lại.
   - Không cần đổi gì trên Supabase (đăng nhập bằng mật khẩu không dùng địa chỉ chuyển hướng).
4. Trang có CSP và khoá toàn vẹn (SRI) cho thư viện Supabase từ CDN. Đổi phiên bản thư viện → tính lại mã băm:
   `openssl dgst -sha384 -binary supabase.min.js | openssl base64 -A` rồi sửa thuộc tính `integrity` trong `index.html`.

## 5b. Tạo tài khoản và đặt lại mật khẩu ngay trên web (Edge Function `accounts`)

Tạo tài khoản và đặt mật khẩu cần khoá quản trị của Supabase. Khoá đó **không bao giờ** được đưa vào trang web hay repo, nên việc này làm trong một Edge Function (chỉ tài khoản `maychinh` gọi được) chạy bên Supabase (mã ở `cloud/supabase/functions/accounts/index.ts`). Các việc còn lại (xem danh sách, đổi vai trò, thu hồi) là SQL 011. Làm một lần:

1. Chạy `011_accounts.sql` (mục 2, bước 10).
2. Trang quản trị Supabase → **Edge Functions** → **Deploy a new function** → chọn cách viết trong trình soạn thảo (**Via Editor**) → đặt tên **`accounts`** (đúng như vậy) → xoá mã mẫu, dán toàn bộ nội dung file `cloud/supabase/functions/accounts/index.ts` → **Deploy**.
3. Công tắc **Verify JWT** của hàm: hàm tự kiểm tra người gọi (hỏi máy chủ đăng nhập rồi đọc vai trò trong bảng `profiles`), nên chạy tốt dù công tắc bật hay tắt. Thử để mặc định trước. **Nếu khi bấm Tạo tài khoản trên web báo Supabase từ chối phiên đăng nhập (lỗi 401 / Invalid JWT) thì tắt công tắc này** (trong chi tiết của hàm, mục cài đặt; tên nhãn có thể khác tuỳ phiên bản trang quản trị, bạn chụp ảnh gửi tôi nếu không thấy).
4. Hàm dùng khoá quản trị mà Supabase **tự gắn** cho Edge Function (không phải dán khoá nào). Mã chấp nhận cả hai tên biến mà Supabase đang dùng (`SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`); nếu dự án của bạn không có cả hai, web sẽ báo rõ.
5. Thử trên web (Cài đặt → **Tài khoản**) bằng một **tài khoản thử**: Tạo tài khoản → đăng nhập thử bằng tài khoản đó ở cửa sổ ẩn danh → Đặt lại mật khẩu → Thu hồi quyền → kiểm tra hết xem được. Chưa cài hàm thì web báo "Chưa cài Edge Function «accounts»"; chưa chạy 011 thì báo "cần chạy SQL 011".

Dùng thường ngày: xem [07-tai-khoan-va-mat-khau.md](07-tai-khoan-va-mat-khau.md). Mỗi lần sửa mã hàm trong repo thì dán lại và Deploy lại.

## 5c. Triển khai một lệnh (khi sửa SQL, hàm hoặc trang web nhiều lần)

Thay cho 3 bước tay (chạy SQL, dán lại hàm, tải lại thư mục web): `python -X utf8 scripts/deploy_cloud.py` (hoặc `--only sql`, `--only function`, `--only web`). Cần Node.js và hai khoá truy cập **để ngoài repo**, trong file `.dibekho-deploy.env` trong thư mục người dùng của bạn (mỗi dòng `TÊN=giá trị`):
- `SUPABASE_ACCESS_TOKEN`: supabase.com → Account → Access Tokens → Generate new token (không phải khoá của dự án).
- `CLOUDFLARE_API_TOKEN`: Cloudflare → My Profile → API Tokens → Create Token (mẫu «Edit Cloudflare Workers» hoặc quyền Account › Cloudflare Pages › Edit); `CLOUDFLARE_ACCOUNT_ID`: ở cột phải trang Workers & Pages.
Chạy lại nhiều lần không sao. ⚠ Script chưa chạy thử với khoá thật (nhãn trang Cloudflare/Supabase có thể lệch): lần đầu hãy chạy từng bước `--only sql`, rồi `function`, rồi `web`.

## 6. Sao lưu và khôi phục

Khi bấm Đồng bộ ngay và lúc tắt app (nếu dữ liệu đổi từ lần trước), app tải lên một bản sao đầy đủ `kho.sqlite` **nén gzip** (`…sqlite.gz`, khoảng 1/3 cỡ gốc: dữ liệu thật 13/11/2026 là 550 KB → 165 KB), Cloud giữ **10 bản** gần nhất (từ 0.5.1; trước đó 30 bản không nén — bản `.sqlite` cũ vẫn khôi phục được và tự bị xoá dần).
**Khôi phục:** Cài đặt → Cloud → **Khôi phục từ Cloud…** → chọn bản. App kiểm tra, sao lưu dữ liệu hiện tại, tạo điểm Hoàn tác rồi mới thay.
**File Excel phiếu gốc** (`data/phieu-goc/`, cho Mở file gốc / Khôi phục file) cũng lên Cloud, cùng kho riêng tư, thư mục `phieu-goc/`: mỗi file một lần (tên = mã băm nội dung), tối đa 90 giây mỗi lần Đồng bộ ngay và 4 giây lúc tắt app (phần còn lại để lần sau); không bao giờ bị xoá vì bản sao lưu cũ vẫn trỏ tới. Khôi phục từ Cloud tải về những file máy đang thiếu (kiểm mã băm trước khi ghi). Chỉ tài khoản chủ đọc được; trang web và gói web vẫn **không** có file phiếu gốc. Không cần SQL mới. Các bảng `mirror_*` cũ đã xoá bằng SQL 014.
**Nhật ký thao tác của từng máy chính** (`data/app.log`, gồm các bước chạy chậm `[slow]` và lỗi) cũng lên kho riêng tư này, thư mục `nhat-ky/`, mỗi máy một file nén thay bản cũ, tối đa 10 phút một lần (trong lượt đồng bộ nền). Người phát triển tải về bằng `python -X utf8 scripts/fetch_cloud_logs.py <thư mục>` (dùng đăng nhập Cloud của máy đó). Nhật ký có tên khách và tên file: không đưa ra ngoài. Không cần SQL mới.

**Thay toàn bộ dữ liệu chung** (khôi phục / nhập gói / xoá toàn bộ khi bật dữ liệu chung) là MỘT lần gửi. Đo 13/11/2026 trên bản sao gói thử thật (73 mặt hàng, 97 phiếu, 476 biến động): 2 171 dòng, 459 KB, 0,2 giây trên PGlite. Supabase cho tài khoản đăng nhập tối đa 8 giây mỗi câu lệnh (tài liệu Supabase "Timeouts"), nên còn dư nhiều; dữ liệu nhiều năm mới cần xem lại. Người dùng đã thử thành công trên Supabase thật (13/11/2026).

## 7. Giới hạn gói Free cần nhớ

- Project **tự tạm dừng sau khoảng 1 tuần không có hoạt động** (dữ liệu giữ nguyên). Mở app hằng ngày là đủ giữ tỉnh; sau kỳ nghỉ dài, vào dashboard bấm *Restore project*.
- Cơ sở dữ liệu 500 MB, kho lưu trữ 1 GB. Đo 13/11/2026: các bảng dữ liệu chừng 1–2 MB (sau SQL 014), kho file khoảng 8 MB (bản sao lưu + 64 phiếu gốc ~17 KB/file). Phiếu gốc tăng khoảng 12 MB/năm (2 phiếu/ngày). Kiểm lại bảng giá trên supabase.com/pricing định kỳ.
- Gói Free không có sao lưu tự động của Supabase: bản sao lưu ở mục 6 là cái duy nhất ngoài máy.
