# 07 — Tài khoản và mật khẩu: tạo, đổi, thu hồi

Dành cho **người cài đặt hoặc chủ cửa hàng** đang dùng dữ liệu chung qua Cloud. Hướng dẫn chung cho khách nằm ở mục 15 của hướng dẫn sử dụng; cách dựng Supabase nằm ở [05-cai-dat.md](05-cai-dat.md).

Mỗi người dùng trang web (và app khi bật dữ liệu chung) có **một tài khoản riêng**: tên đăng nhập + mật khẩu. Không có chỗ tự đăng ký: tài khoản do **chủ** tạo.

## 0. Cách nhanh: ngay trên trang web (khuyên dùng)

Đăng nhập web bằng tài khoản **`maychinh`** (tài khoản của máy chính) → **Cài đặt** → tab **Tài khoản**. **Chỉ `maychinh` thấy và dùng được tab này**: các tài khoản chủ khác, nhân viên và điện thoại đều không (khách lớn tuổi nên không ai khác làm được; máy chủ Supabase cũng từ chối, không chỉ ẩn nút). Cần làm một lần trước: chạy SQL 011 và cài Edge Function `accounts` ([05-cai-dat.md](05-cai-dat.md), mục 2 bước 10 và mục 5b).

Chọn một dòng trong danh sách rồi bấm nút:
- **Tạo tài khoản…**: gõ tên đăng nhập, tên hiển thị, chọn vai trò, gõ mật khẩu **hai lần**. Mật khẩu do bạn gõ; trang web không lưu và không hiện lại. Tạo vai trò **chủ** thì hỏi xác nhận thêm một lần.
- **Đổi vai trò…** (cả đổi tên hiển thị), **Đặt lại mật khẩu…**, **Xoá tài khoản…** (xoá hẳn, không khôi phục được; các yêu cầu người đó đã gửi vẫn còn nhưng không ghi rõ người gửi; không tự xoá mình được) và **Thu hồi quyền…** (nhân viên nghỉ việc: tài khoản vẫn còn nhưng không xem và không ghi được gì; cấp lại bằng Đổi vai trò).
- Dòng **gạch ngang** là tài khoản chưa có quyền (mới tạo bằng Supabase mà chưa cấp vai trò, hoặc đã thu hồi).

Chốt chặn để không tự khoá mình: **không tự hạ quyền hoặc tự thu hồi quyền của chính mình**, luôn còn ít nhất một chủ. Hạ quyền hay thu hồi một tài khoản chủ khác thì web nhắc: nếu app trên máy chính đang đăng nhập bằng tài khoản đó thì đồng bộ sẽ dừng.

Mật khẩu tối thiểu **8 ký tự** (nên từ 10, có cả chữ và số). Supabase có thể đòi dài hơn: khi đó web hiện đúng lời Supabase báo.

Các mục 1 và 8–10 dưới đây vẫn dùng. Các mục **2–7 là cách làm trong trang quản trị Supabase**, dùng khi chưa cài Edge Function hoặc khi web gặp sự cố.

## 1. Ba vai trò

| Vai trò | Dành cho | Làm được gì |
|---|---|---|
| `desktop` | **Người quản lý / chủ cửa hàng** và app trên máy chính | Xem tất cả, trang web mở vào **Tổng quan**. Tạo file **Phiếu xuất kho** trên web. Trong **app** trên máy chính: ghi mọi thứ (hàng về, chuyển hàng, dùng thử, kiểm kê, huỷ phiếu, mặt hàng, gộp khách, nhập/xuất gói dữ liệu), khôi phục, thay toàn bộ dữ liệu |
| `editor` | **Nhân viên** | Xem tất cả. Tạo file **Phiếu xuất kho** trên web (app trừ tồn khi file vào thư mục phiếu giao hàng). Không thấy Tổng quan |
| `viewer` | Người chỉ cần xem | Chỉ xem |

Lưu ý:
- **Mọi tài khoản đều xem được toàn bộ dữ liệu** (tồn, giá, khách). Chưa có vai trò xem hạn chế.
- Từ 14/11/2026 **trang web chỉ xem** với mọi vai trò (khách yêu cầu): việc ghi làm trên app. Tài khoản `desktop` dùng được cho app trên máy chính nên có toàn quyền ghi kể cả thay toàn bộ dữ liệu. **Chỉ cấp cho chủ / quản lý** (ví dụ sếp cần xem Tổng quan). Nhân viên dùng `editor`.
- Người dùng chỉ gõ tên ngắn, ví dụ `nhanvien1`. Hệ thống tự thêm đuôi `@dibekho.local`. Đây chỉ là "tên kỹ thuật", **không cần email thật** và sẽ không có thư khôi phục nào được gửi.

## 2. Tạo tài khoản mới (làm một lần cho mỗi người)

**Bước 1: tạo tài khoản.** Vào https://supabase.com/dashboard → chọn dự án → **Authentication** → **Users** → **Add user** → **Create new user**.
- **Email:** tên ngắn + `@dibekho.local`, viết thường, không dấu, không cách. Ví dụ `nhanvien1@dibekho.local`, `quanly@dibekho.local`.
- **Password:** mật khẩu cho người đó (xem mục 3).
- Tick **Auto Confirm User** (không tick thì tài khoản chưa đăng nhập được).
- Bấm **Create user**.

**Bước 2: cấp vai trò.** Bước này **bắt buộc**. Thiếu bước này thì đăng nhập được nhưng trang web trống và không có nút nào. Vào **SQL Editor** → **New query**, dán, sửa phần giữa dấu nháy cho đúng người, bấm **Run**:

```sql
insert into public.profiles (user_id, display_name, role)
select id, 'Lan - kho', 'editor' from auth.users where email = 'nhanvien1@dibekho.local';
```

- `'Lan - kho'`: tên hiển thị. App ghi tên này cạnh mỗi yêu cầu nhân viên gửi, nên hãy đặt tên nhìn là biết ai.
- `'editor'`: đổi thành `'desktop'` cho quản lý, `'viewer'` cho người chỉ xem.
- Phải có đúng một dòng cho mỗi tài khoản. Chạy lần hai cho cùng một người sẽ báo lỗi trùng, đó là bình thường: muốn đổi vai trò thì xem mục 5.

**Bước 3: gửi cho người đó** (xem mẫu ở mục 8): địa chỉ trang web, tên đăng nhập (`nhanvien1`, không cần gõ đuôi) và mật khẩu. Nên gửi tên và mật khẩu bằng **hai tin nhắn riêng** hoặc nói trực tiếp.

## 3. Mật khẩu

- **Mỗi người một mật khẩu riêng.** Không dùng chung một tài khoản cho nhiều người: khi một người nghỉ việc thì phải đổi mật khẩu của tất cả.
- Nên dài từ 10 ký tự, trộn chữ và số. Supabase chấp nhận ngắn hơn nhưng không nên.
- Gửi riêng cho từng người, **không đăng vào nhóm chung**. Không ghi mật khẩu vào file trong thư mục dự án hay repo.
- App và web **không lưu mật khẩu**. Ô **Nhớ tôi** trên web chỉ giữ phiên đăng nhập trong trình duyệt đó. App giữ phiên đăng nhập trong cấu hình của máy.
- Không bao giờ đưa **service_role key** hay mật khẩu cơ sở dữ liệu của Supabase vào app, trang web hay repo. Địa chỉ Cloud và **Mã kết nối** (publishable key) thì công khai theo thiết kế, an toàn để để trong app và web.

## 4. Đổi mật khẩu hoặc đặt lại khi quên

Không có nút "quên mật khẩu" gửi email, vì tên đăng nhập không phải email thật. Người quản lý Supabase đặt lại giúp:

**Cách 1 (qua SQL, chắc chắn dùng được):** SQL Editor → **New query**, dán, sửa email và mật khẩu mới, **Run**:

```sql
update auth.users
set encrypted_password = crypt('MatKhauMoi-123', gen_salt('bf'))
where email = 'nhanvien1@dibekho.local';
```

**Cách 2 (qua giao diện):** Authentication → Users → bấm vào tài khoản. Tuỳ phiên bản trang quản trị, có mục đặt lại hoặc đổi mật khẩu cho người dùng. Mục gửi email khôi phục thì **không dùng được** vì email giả.

Sau khi đổi:
- Báo mật khẩu mới cho người đó theo cách ở mục 3.
- Trên trang web: đăng nhập lại bằng mật khẩu mới.
- Trên app: máy đang đăng nhập có thể vẫn chạy thêm một lúc. Khi app báo "cần gõ lại mật khẩu", vào **Cài đặt → Cloud**, gõ mật khẩu mới rồi bấm **Đồng bộ ngay**.

> Các câu SQL ở mục 2, 5, 6, 7 và các nút trên web (đổi vai trò, thu hồi) đã kiểm trên Postgres thử nghiệm; Edge Function được kiểm với một Supabase giả. **Chưa chạy thử trên project Supabase thật của bạn**: tạo tài khoản và đặt lại mật khẩu (cả trên web lẫn bằng SQL `crypt` ở cách 1) hãy thử lần đầu với một **tài khoản thử**.

## 5. Đổi vai trò

Ví dụ nâng nhân viên lên người quản lý, hoặc hạ xuống chỉ xem:

```sql
update public.profiles set role = 'desktop'   -- hoặc 'editor', 'viewer'
where user_id = (select id from auth.users where email = 'nhanvien1@dibekho.local');
```

Người đó đăng xuất rồi đăng nhập lại trên web là thấy các nút mới. Muốn đổi tên hiển thị thì thay `set role = …` bằng `set display_name = 'Tên mới'`.

## 6. Thu hồi quyền (nhân viên nghỉ việc, mất máy)

**Cách đúng: xoá dòng vai trò.** Tài khoản không còn vai trò thì không đọc được dữ liệu và không ghi được gì nữa, ngay từ lần tải dữ liệu kế tiếp:

```sql
delete from public.profiles
where user_id = (select id from auth.users where email = 'nhanvien1@dibekho.local');
```

Rồi đổi mật khẩu tài khoản đó sang một chuỗi ngẫu nhiên (mục 4 cách 1) để người cũ không đăng nhập được nữa.

**Xoá hẳn tài khoản**: dùng nút **Xoá tài khoản…** trên web (tài khoản `maychinh`, mục 5b của `05-cai-dat.md`). Chỉ muốn tạm khoá thì xoá dòng vai trò như trên là đủ.

Muốn cho phép lại: chạy lại câu cấp vai trò ở mục 2 bước 2.

## 7. Xem danh sách tài khoản và vai trò

```sql
select u.email, p.display_name, p.role
from auth.users u
left join public.profiles p on p.user_id = u.id
order by u.email;
```

Dòng nào cột `role` trống là tài khoản **chưa được cấp vai trò** (không dùng được, xem mục 2 bước 2).

## 8. Mẫu tin nhắn gửi cho nhân viên

> Anh/chị mở trang **https://\<địa chỉ web người cài đặt gửi\>** trên điện thoại hoặc máy tính.
> Tên đăng nhập: `nhanvien1` (không cần gõ gì thêm). Mật khẩu: tôi gửi riêng.
> Tick **Nhớ tôi** nếu đây là máy của anh/chị. **Không tick** nếu dùng máy chung.
> Trên điện thoại anh/chị chỉ xem được bảng Tồn kho. Muốn gửi phiếu hàng về, kiểm kê hoặc phiếu giao hàng thì dùng máy tính. Anh/chị gửi xong, người quản lý sẽ duyệt trong app, bên **Cần xử lý** của web sẽ hiện "chờ duyệt", "đã vào sổ" hoặc "bị từ chối".
> Quên mật khẩu hay đăng nhập không được: nhắn cho tôi, tôi đặt lại.

## 9. Thêm máy chính thứ hai

App trên mỗi máy chính tự đăng nhập bằng tài khoản `desktop`. Trên **từng máy**: **Cài đặt → Cloud**, điền địa chỉ Cloud, mã kết nối, tên đăng nhập, mật khẩu, bấm **Đồng bộ ngay**, rồi **Bật dùng dữ liệu chung** (xem mục 15 của hướng dẫn sử dụng). Hai máy có thể dùng chung một tài khoản `desktop`, hoặc mỗi máy một tài khoản (`maychinh`, `maychinh2`, cấp vai trò `desktop` cho cả hai) nếu muốn tách bạch. Cách nào cũng được.

## 10. Sự cố thường gặp

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Đăng nhập báo sai tên hoặc mật khẩu | Gõ hoa/thường hoặc có dấu cách; mật khẩu đã đổi | Gõ lại tên viết thường không dấu; nếu vẫn sai, đặt lại mật khẩu (mục 4) |
| Đăng nhập được nhưng trang trống, không có nút nào | Tài khoản **chưa có vai trò** | Cấp vai trò (mục 2 bước 2); kiểm tra bằng mục 7 |
| Không thấy nút Chuyển hàng, Xuất dùng thử, Thêm mặt hàng trên web | Đúng thiết kế: từ 14/11/2026 trang web chỉ xem (với mọi vai trò) | Làm việc đó trên app ở máy chính |
| Không thấy trang **Tổng quan** | Tài khoản không phải vai trò `desktop` | Nâng lên `desktop` (mục 5) nếu người đó là quản lý |
| Không thấy nút **📤 Phiếu xuất kho…** | Vai trò `viewer` (chỉ xem), hoặc đang mở trên điện thoại | Đổi sang `editor` nếu người đó cần tạo phiếu; dùng máy tính |
| App báo "cần gõ lại mật khẩu" | Phiên đăng nhập hết hạn hoặc mật khẩu vừa đổi | Cài đặt → Cloud, gõ mật khẩu, **Đồng bộ ngay** |
| Web báo «Chưa cài Edge Function accounts» / «cần chạy SQL 011» | Chưa làm [05-cai-dat.md](05-cai-dat.md) mục 5b / chưa chạy 011 | Làm theo 05; trong lúc chờ dùng cách trong trang quản trị Supabase (mục 2–7) |
| Web báo Supabase từ chối phiên đăng nhập khi Tạo tài khoản | Công tắc Verify JWT của hàm | Tắt công tắc đó (05 mục 5b bước 3) |
| Tạo xong tài khoản nhưng đăng nhập không được | Quên tick **Auto Confirm User** | Authentication → Users, mở tài khoản và xác nhận (hoặc xoá tài khoản mới tạo rồi tạo lại có tick) |
| Chạy câu cấp vai trò báo trùng | Tài khoản đó đã có vai trò | Dùng mục 5 để đổi |
