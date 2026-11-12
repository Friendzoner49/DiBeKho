# Cài đặt DiBeKho Cloud từ đầu (tự làm, ~20 phút)

Dùng khi dựng lại project Supabase mới, hoặc chuyển sang tài khoản khác. Thiết kế: `04-thiet-ke-chot.md`.
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
8. `cloud/supabase/009_web_rpc.sql` — **chủ ghi thẳng trên web** (hàng về, chuyển hàng, dùng thử, kiểm kê, huỷ phiếu, nơi lấy hàng, mặt hàng, gộp khách). **Bắt buộc cho trang web mới.** Chạy lại nhiều lần không sao.

## 3. Tạo tài khoản

Authentication → Users → Add user → Create new user, tick *Auto Confirm User*. Email chỉ là "tên đăng nhập kỹ thuật", không cần có thật:

| Tài khoản | Vai trò | Dùng để |
|---|---|---|
| `maychinh@dibekho.local` | `desktop` | app trên máy chính đẩy dữ liệu, kéo hộp thư, sao lưu |
| `khach1@dibekho.local` … | `viewer` (chỉ xem) hoặc `editor` (xem + **gửi yêu cầu**) | trang web — mỗi nhân viên một tài khoản `editor` riêng, để biết ai gửi |

Gán vai trò (SQL Editor), đổi tên/vai trò cho đúng:

```sql
insert into public.profiles (user_id, display_name, role)
select id, 'May chinh', 'desktop' from auth.users where email = 'maychinh@dibekho.local';
insert into public.profiles (user_id, display_name, role)
select id, 'Nguoi xem', 'editor' from auth.users where email = 'khach1@dibekho.local';
```

Quên mật khẩu: không có email khôi phục — vào Authentication → Users, mở tài khoản và đặt lại mật khẩu.

### Trang web giờ làm việc thẳng trên dữ liệu chung (từ 12/11/2026, SQL 009)

Khi máy chính đã **bật Dữ liệu chung** (app → Cài đặt → Cloud), trang web đọc và ghi **bảng thật** trên Cloud (không còn bản gương chờ máy chính đẩy lên). Bố cục web **giống app**: thanh bên trái *Tồn kho · Cần xử lý · Tra cứu · Hàng về · Kiểm kê · Cài đặt*, nút cùng tên, cùng chỗ (Chuyển hàng…/Xuất dùng thử…/Phiếu chuyển hàng… ở Kiểm kê; Đơn hàng/Khách hàng/Thống kê là nút trong Tra cứu; Thêm/Sửa/Gộp mặt hàng ở Cài đặt → Danh mục mặt hàng). Bấm một dòng để chọn, nháy đúp để mở, như app (điện thoại: chạm lần nữa vào dòng đã chọn).

**Chủ (`desktop`, ví dụ `maychinh`)** làm thẳng, **không cần app mở**: nhập/sửa phiếu hàng về, chuyển hàng (cả sửa phiếu), xuất dùng thử, kiểm kê (2 cột vàng Kho tổng/Văn phòng), huỷ phiếu, chọn nơi lấy hàng (ở chi tiết đơn và ở Cần xử lý), thêm/sửa/ngừng dùng/gộp mặt hàng, gộp khách hàng. Mỗi việc là một hàm trong `cloud/supabase/009_web_rpc.sql`, làm đúng như hàm của app và được kiểm song song với app (`tests/test_cloud_web_rpc.py`). App trên máy tính nhận thay đổi ở lần đồng bộ kế tiếp; phiếu hàng về nhập trên web được app tự tạo file Excel trong `output/hang-ve/`.
- Kiểm tra trùng khi thêm mặt hàng trên web chỉ bắt **trùng hẳn** (cùng tên, quy cách, loại/màu, không dấu); kiểu "trông giống" (gợi ý theo tên Trung…) chỉ có trong app.
- Nhập hàng về trên web chưa có "★ Mặt hàng mới": thêm mặt hàng ở Cài đặt → Danh mục mặt hàng trước.
- Giờ trên phiếu theo đồng hồ của cửa hàng (`meta.clock_offset_min`, máy đồng bộ đầu tiên tự ghi; thiếu thì lấy giờ Việt Nam).
- Hoàn tác khi bật dữ liệu chung: chỉ huỷ phiếu hàng về / chuyển hàng / dùng thử / kiểm kê vừa lưu trên máy đó (phiếu vẫn còn, ghi là đã huỷ). Việc khác làm nhầm: Huỷ phiếu / sửa phiếu / sửa tay. Mỗi ngày, sau lần đồng bộ đầu tiên, app chép một bản `sao-luu/DiBeKho_dulieu-chung_<ngày>.sqlite`.
- Chưa bật dữ liệu chung thì mọi việc ghi của chủ trên web bị từ chối kèm lời nhắc (để không ghi vào chỗ không ai đọc).

**Nhân viên (`editor`)** vẫn **gửi yêu cầu chờ duyệt** từ cùng các nút (＋ Nhập hàng về…, Lưu kiểm kê, Gửi phiếu giao hàng (file Excel)…); chủ duyệt trong app → **Cần xử lý** → *Yêu cầu từ nhân viên (web)*, như trước:
- **Hàng về**: xem tóm tắt, *Vào sổ…*. **Phiếu giao hàng**: *Vào sổ…* đặt file vào thư mục phiếu giao hàng, app đọc như mọi phiếu.
- **Kiểm kê**: chênh lệch tính theo **lúc nhân viên gửi**; đếm cả 2 nơi thì thành 2 yêu cầu (mỗi nơi một). Phiếu giao vào sổ sau lúc đó hiện ở *đơn đọc sau kiểm kê*.
- Nhân viên thấy trạng thái ở trang **Cần xử lý** của web (chờ duyệt / đã vào sổ / bị từ chối).
- Tất cả tài khoản đăng nhập xem được toàn bộ dữ liệu (tồn, giá, khách). Muốn hạn chế thì cần vai trò riêng — chưa làm.

**Lệnh của chủ kiểu cũ** (`cmd_*` qua hộp thư, SQL 006): web không gửi nữa. App vẫn còn đoạn xử lý các lệnh cũ còn sót; sẽ gỡ sau khi người dùng xác nhận bản mới chạy ổn.

### Web xem được những gì (giống app)

- **Tồn kho**: nháy đúp một mặt hàng → tồn theo nơi, **lịch sử vào ra** có số dư sau từng dòng, khách lấy nhiều nhất, xuất file CSV.
- **Tra cứu → Đơn hàng / Khách hàng / Thống kê**: như app; Chi tiết đơn mở thành cửa sổ (chủ có Huỷ phiếu, Lấy hàng từ, Sửa phiếu…).
- Số liệu Thống kê trên web được kiểm tự động bằng `tests/test_web_stats.py` (chạy `webapp/stats.js` dưới `node` và so với `core/stats.py`), nên hai nơi luôn khớp.
- `tests/test_web_contract.py` cho Chrome thật bấm mọi cửa sổ của chủ (và của nhân viên), chạy đúng các lệnh trang gửi đi trên Postgres thử, rồi app kéo về và kiểm kết quả: tên trường hai bên mà lệch là test đỏ.

## 4. Nối app trên máy chính

Project Settings → API: lấy **Project URL** và **publishable (anon) key** (hai thứ này công khai theo thiết kế).
App → Cài đặt → tab **Cloud**: dán URL, mã kết nối, tên đăng nhập `maychinh`, mật khẩu → **Đồng bộ ngay**.
Từ đó: tắt app tự đẩy, mở app tự kéo phiếu từ web. Mật khẩu không được lưu; app giữ phiên đăng nhập trong `config.json`.

## 5. Trang web (`webapp/`)

1. Sao `webapp/config.example.js` thành `webapp/config.js`, điền URL + publishable key (file này nằm trong `.gitignore`).
2. Thử trên máy: `python -m http.server 8808 --directory webapp` rồi mở http://localhost:8808.
3. Đưa lên mạng (Cloudflare Pages, miễn phí): Workers & Pages → Create → Pages → **Upload assets** → kéo thả thư mục `webapp` (gồm cả `config.js`). Mỗi lần sửa web: tải lên lại.
4. Trang có CSP và khoá toàn vẹn (SRI) cho thư viện Supabase từ CDN. Đổi phiên bản thư viện → tính lại mã băm:
   `openssl dgst -sha384 -binary supabase.min.js | openssl base64 -A` rồi sửa thuộc tính `integrity` trong `index.html`.

## 6. Sao lưu và khôi phục

Sau mỗi lần đẩy thành công, app tải lên một bản sao đầy đủ `kho.sqlite` (khoảng 300 KB), Cloud giữ 30 bản gần nhất.
**Khôi phục:** Cài đặt → Cloud → **Khôi phục từ Cloud…** → chọn bản. App kiểm tra, sao lưu dữ liệu hiện tại, tạo điểm Hoàn tác rồi mới thay.
Bản sao lưu **không** chứa file Excel phiếu gốc. Các bảng `mirror_*` chỉ là bản chiếu cho web, **không** dùng để khôi phục.

## 7. Giới hạn gói Free cần nhớ

- Project **tự tạm dừng sau khoảng 1 tuần không có hoạt động** (dữ liệu giữ nguyên). Mở app hằng ngày là đủ giữ tỉnh; sau kỳ nghỉ dài, vào dashboard bấm *Restore project*.
- Cơ sở dữ liệu 500 MB, kho lưu trữ 1 GB: dữ liệu DiBeKho dùng dưới 1% — kiểm lại bảng giá trên supabase.com/pricing định kỳ.
- Gói Free không có sao lưu tự động của Supabase: bản sao lưu ở mục 6 là cái duy nhất ngoài máy.
