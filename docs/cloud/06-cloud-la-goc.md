# 06 — Cloud làm gốc, app là client (quyết định 11/11/2026, CHƯA làm)

> Đảo lại nguyên tắc "máy chính là nguồn sự thật" của `04-thiet-ke-chot.md` (mục đó coi là **đã bị thay thế** khi bản này được làm xong; trong lúc đó 04 vẫn mô tả đúng phần mềm đang chạy).
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

## Luật nghiệp vụ nằm ở đâu
Đề xuất của reviewer, chưa chốt: **hàm Postgres (RPC, security definer)** là nơi duy nhất cài luật (ghi phiếu, huỷ, chuyển hàng, kiểm kê…), cả app lẫn web đều gọi. Đọc Excel vẫn ở Python trên app, rồi gọi RPC với các dòng đã đọc.

## Cách làm — lát cắt, có kiểm chứng TRƯỚC khi viết lại
0. **Nền (làm ngay, không phụ thuộc quyết định):** mạng ra khỏi luồng giao diện (đo: refresh token 2,1 s + đọc trạng thái 1 s đứng hình mỗi lần mở app, mỗi 3 phút và mỗi lần Quét lại) ✔ xong; nhớ kích thước cửa sổ ✔ xong.
1. **Lược đồ + chuyển dữ liệu một lần** từ một *bản sao* dữ liệu thật; đối chiếu **tồn theo mặt hàng × nơi** với SQLite làm tổng độc lập.
2. **Test song song từng thao tác** (mẫu `tests/test_web_stats.py`): cùng đầu vào chạy qua lõi Python và qua RPC, đòi cùng bộ biến động.
3. **Đổi từng đường ghi của app sang RPC**, mỗi lát đổi cả web cùng lúc, rồi mới gỡ "hộp thư + lệnh của chủ".
4. Hàng đợi offline + xung đột; kéo bản sao SQLite hằng ngày; hoàn tác bằng phiếu đảo.

Ước lượng thật: nhiều tuần, đụng gần hết `core/`. Mỗi lát phải qua test song song trước khi sang lát sau.
