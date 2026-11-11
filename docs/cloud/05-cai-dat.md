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

### Nhân viên gửi yêu cầu, chủ duyệt cuối ngày

Nhân viên (`editor`) vào trang web → tab **Gửi yêu cầu**: **Hàng về**, **Phiếu giao hàng** (tải file Excel .xlsx, tối đa 2 MB), **Kiểm kê** (đếm xong mới gửi; có nút điền sẵn toàn bộ mặt hàng, ô trống = không đếm).
Chủ mở app trên máy chính (hoặc bấm **Quét lại phiếu**) → **Cần xử lý** → mục **Yêu cầu từ nhân viên (web)**, có tên người gửi:

- **Hàng về**: xem tóm tắt, *Vào sổ…*. **Phiếu giao hàng**: *Vào sổ…* đặt file vào thư mục phiếu giao hàng, app đọc như mọi phiếu (hàng lạ hiện ở Cần xử lý, "Mở file gốc" dùng được, đọc trùng bị chặn theo nội dung file).
- **Kiểm kê**: hộp duyệt cho xem đếm được / tồn máy lúc nhân viên gửi / chênh lệch từng mặt hàng. Chênh lệch tính theo **lúc nhân viên gửi**, không phải lúc chủ duyệt; phiếu giao vào sổ sau lúc đó (ngày ≤ ngày đếm) hiện ở mục *đơn đọc sau kiểm kê* để chủ quyết (Giữ số đã kiểm kê / Trừ thêm đơn này).
- Nút **Vào sổ tất cả hàng về và phiếu giao hàng** duyệt một lượt; kiểm kê luôn duyệt từng phiếu. Phiếu hỏng được liệt kê lại, không làm dừng cả lượt.
- Nhân viên thấy trạng thái từng yêu cầu ngay trên web (chờ duyệt / đã vào sổ / bị từ chối). Hoàn tác trên máy chính một phiếu hàng về hoặc kiểm kê đã duyệt thì yêu cầu đó quay về hàng chờ.
- Tất cả tài khoản đăng nhập xem được toàn bộ dữ liệu (tồn, giá, khách). Muốn hạn chế thì cần thêm vai trò riêng và lớp xem (view) — chưa làm.

### Web xem được những gì (giống app)

- **Tồn kho**: bấm một mặt hàng → tồn theo nơi, **lịch sử vào ra** có số dư sau từng dòng, khách lấy nhiều nhất, xuất file CSV.
- **Đơn hàng**: lọc theo loại phiếu; bấm một dòng → đầu phiếu (khách, nơi lấy hàng, nguồn, phí, tổng tiền, file gốc) + các dòng hàng có giá.
- **Khách hàng**: bấm một khách → doanh thu và phí theo kỳ chọn, mặt hàng hay mua (giá thấp–cao), các đơn.
- **Thống kê**: kỳ (ngày/tháng/quý/năm/khoảng), phạm vi (tất cả/nhóm/một mặt hàng/một khách), chia theo ngày/tháng; tồn đầu–nhập–xuất–điều chỉnh–tồn cuối, doanh thu, top xuất nhiều, biểu đồ, xuất CSV.
- Số liệu Thống kê trên web được kiểm tự động bằng `tests/test_web_stats.py` (chạy `webapp/stats.js` dưới `node` và so với `core/stats.py` ở nhiều bộ lọc), nên hai nơi luôn khớp.
- File CSV (UTF-8 có BOM) mở thẳng bằng Excel. Dữ liệu web chỉ mới bằng lần đồng bộ gần nhất của máy chính.

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
