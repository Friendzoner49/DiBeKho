# Approval Required Before Implementation — các quyết định chờ người dùng

> Ngày: 10/11/2026. Tài liệu LOCAL — chưa commit. Phase 0 dừng tại đây; chưa viết code, chưa tạo dịch vụ nào.

## Quyết định chặn (phải trả lời trước khi làm bất kỳ gì)

1. **⛔ Nhu cầu thật của khách:** cần **XEM** từ xa hay cần **GHI** từ máy thứ hai cùng lúc? (Quyết định chọn phương án A/B/C — xem `02-danh-gia-kha-thi.md`.)
2. **⛔ Chấp nhận phụ thuộc dịch vụ ngoài?** Supabase Free: tự ngủ sau ~1 tuần không dùng, không backup tự động, không cam kết miễn phí vĩnh viễn. Khách hiện được hứa "0₫, chạy trên máy, không cần Internet".
3. **⛔ Nếu chọn C (sync 2 chiều): số phận Undo?** Undo hiện thay nguyên file DB — không sống chung được với sync. Chấp nhận viết lại Undo (mất "hoàn tác mọi thứ" trong thời gian chuyển tiếp) hay từ bỏ C?

## Quyết định không chặn (trả lời khi đã chọn hướng)

4. Tài liệu `docs/cloud/` + `GPT_NextStepPlan.md`: giữ local, hay privacy_scan rồi commit công khai?
5. Nếu làm B: biến thể B1 (upload bản xuất vào storage riêng, web nhỏ đọc) hay B2 (Postgres + Supabase JS)? Khuyến nghị B1.
6. Nếu làm B: tần suất đẩy lên cloud (mỗi lần đóng app? nút bấm? cả hai?); ai được xem (chỉ chủ + 1 tài khoản khách?).
7. Đăng nhập cho khách lớn tuổi: email/mật khẩu Supabase hay link có token? (đánh đổi an toàn ↔ dễ dùng).
8. Có cần tiếng Trung/ba ngôn ngữ trên trang web xem không?
9. Ngân sách thời gian người dùng muốn bỏ ra (B: ~2–4 tuần; C: 3–6 tháng).

## Những gì ĐÃ chốt bởi audit (không cần hỏi lại)

- Giữ nguyên SQLite, gói `.dibekho`, quy tắc tồn = tổng biến động, Undo hiện tại — mọi phương án đều không đụng trong bước đầu.
- Không đưa Service Role Key vào client; backup/export luôn private — nếu có cloud.
- Không migration dữ liệu thật khi chưa có backup + duyệt.
