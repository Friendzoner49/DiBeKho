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

## 3. Tạo tài khoản

Authentication → Users → Add user → Create new user, tick *Auto Confirm User*. Email chỉ là "tên đăng nhập kỹ thuật", không cần có thật:

| Tài khoản | Vai trò | Dùng để |
|---|---|---|
| `maychinh@dibekho.local` | `desktop` | app trên máy chính đẩy dữ liệu, kéo hộp thư, sao lưu |
| `khach1@dibekho.local` | `viewer` (chỉ xem) hoặc `editor` (xem + gửi hàng về) | trang web |

Gán vai trò (SQL Editor), đổi tên/vai trò cho đúng:

```sql
insert into public.profiles (user_id, display_name, role)
select id, 'May chinh', 'desktop' from auth.users where email = 'maychinh@dibekho.local';
insert into public.profiles (user_id, display_name, role)
select id, 'Nguoi xem', 'editor' from auth.users where email = 'khach1@dibekho.local';
```

Quên mật khẩu: không có email khôi phục — vào Authentication → Users, mở tài khoản và đặt lại mật khẩu.

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
