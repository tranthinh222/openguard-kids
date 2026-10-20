# Nâng cấp các yêu cầu bắt buộc — 20/10/2026

Đây là hướng dẫn source/migration, không phải chứng nhận đã nghiệm thu trên máy sạch.
Không chạy migration trên DB đang dùng trước khi sao lưu. Các test dùng DB và cổng riêng.

## 1. Khóa mã hóa server và migration

Tạo **một lần** khóa 32 byte, lưu giá trị vào `DATA_ENCRYPTION_KEY` trong cấu hình server:

```powershell
.\.venv\Scripts\python.exe -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Không commit khóa, không sinh lại mỗi lần khởi động. Sao lưu khóa riêng với backup DB;
mất khóa thì không đọc được các trường đã mã hóa. Agent không dùng khóa này.
Từ `server/`, sau khi dừng server và sao lưu DB:

```powershell
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Revision `f420_privacy` thêm consent, IP audit, báo chặn nhầm, audit điều khiển và
biên nhận xóa dữ liệu. Migration mã hóa email, tên trẻ, tên thiết bị, phản hồi và payload lệnh bằng
AES-GCM; ciphertext không thay đổi định dạng API. Backend được hỗ trợ là SQLite.
Downgrade cần đúng khóa và chuyển các trường này về plaintext; chỉ dùng trên bản sao kiểm thử.
SQLite phải từ 3.35 trở lên để bỏ cột trực tiếp, tránh rebuild bảng gây cascade dữ liệu.
Đây là mã hóa trường chọn lọc, không phải mã hóa toàn database.

## 2. TLS cho cả HTTP và WebSocket

- HTTPS yêu cầu `OGK_TLS_CERT_SHA256`: SHA-256 của chứng chỉ server ở dạng DER.
- `OGK_TLS_CA_FILE`: CA PEM riêng nếu dùng CA nội bộ; vẫn kiểm tra CA, hostname và TLS ≥1.2.
- Lấy fingerprint từ chứng chỉ đã xác minh qua kênh quản trị, không tự tin chứng chỉ
  vừa tải từ một server chưa được xác minh.
- Cập nhật pin khi đổi chứng chỉ. Pin sai bị chặn trước khi gửi Authorization.
- HTTP vẫn dành cho lab; HTTP không đáp ứng nghiệm thu TLS. Triển khai chính thức dùng HTTPS.
- HTTP transport bỏ proxy môi trường; WebSocket TLS dùng kết nối trực tiếp, không TLS-in-TLS.

Trên Windows, state chứa token được AES-GCM mã hóa; khóa ngẫu nhiên được DPAPI machine-scope
bọc và lưu trong thư mục ACL SYSTEM/Administrators. State JSON cũ được chuyển đổi khi đọc.
`OGK_STATE_ENCRYPTION_KEY` là tùy chọn khóa base64 32 byte do người vận hành cấp.
Dev ngoài Windows dùng file khóa mode 0600; không coi đó là DPAPI.

## 3. Hành vi mới

- Ghép đôi: phụ huynh phải tích xác nhận thông báo; API cần
  `{"consent":true,"privacy_notice_version":"2026-10-20-v1"}`. Không tự đánh dấu consent
  cho dữ liệu ghép đôi cũ.
- Tray có **Báo chặn nhầm**: chỉ nhập hostname hoặc executable basename, không URL/path.
  Dashboard có ghi nhận/từ chối và lời nhắn. Ghi nhận không tự mở mọi hash/domain rule:
  phụ huynh sửa quy tắc ở trang Chính sách; UI nêu rõ điều này.
- Child detail có **Xóa toàn bộ dữ liệu**. Server xóa các hàng liên quan theo FK trong
  một transaction, giữ hash token trong biên nhận để agent offline nhận lệnh xóa.
  Agent kiểm tra mỗi 30 giây, dừng collectors, xóa activity/cache/policy/usage/clock
  và chống lặp, rồi ACK. Mất ACK: retry, không khởi động lại collectors.
  Receipt bị xóa khi ACK; không chứa tên trẻ, tên máy hay lịch sử. Máy không bao giờ
  kết nối lại thì không thể xác nhận xóa cục bộ. Backup ngoài hệ thống cần xử lý riêng.
- Dữ liệu đang lưu trong SQLite agent được xóa với `secure_delete`, checkpoint và VACUUM;
  không tuyên bố xóa vật lý mọi bản sao trên SSD/backup.
- Giữ backup DNS/browser nếu phục hồi OS thất bại để admin có thể khôi phục mạng.
- Retention activity, usage, audit, request, command là 90 ngày; cleanup agent chạy
  theo giờ tin cậy cả khi upload offline. State vận hành đang dùng và receipt chưa
  ACK có vòng đời riêng, không tự xóa khiến mất khả năng bảo vệ/hoàn tất erasure.

## 4. Clock, visibility và an toàn

- `OGK_OFFLINE_CLOCK=strict`: sau reboot offline không lấy wall clock để mở quota ngày mới.
  Restart trong cùng boot có thể phục hồi anchor. Chế độ `provisional` vẫn là tùy chọn lab
  và có giới hạn chống chỉnh giờ; cấu hình `.env` cũ không tự đổi theo default mới.
- `OGK_POLICY_OFFLINE_DAYS=7`: hết hạn thì khóa screen-time cho tới khi heartbeat thành công;
  bộ lọc nội dung giữ policy đã xác minh. Đây là lựa chọn fail-closed.
- Service chỉ tin báo cáo hiển thị/idle từ Tray do watchdog khởi chạy.
  Không xác nhận icon trong 30 giây ở desktop đang đăng nhập: tự dừng, phục hồi DNS.
  Cần restart service sau khi xử lý lỗi Tray. Không dùng vòng crash-restart để chạy ẩn.
- DNS luôn miễn chặn `tongdai111.vn`, `moet.gov.vn`; cấu hình cổng trường thực tế qua
  `OGK_SCHOOL_DOMAINS` (phân cách dấu phẩy). Policy thường không ghi đè được lớp này.
  Nguồn: [Tổng đài 111](https://tongdai111.vn/thu-vien),
  [Bộ GD&ĐT](https://tuyensinh.moet.gov.vn/ts/).
  Không ghi activity cho các truy vấn được miễn chặn an toàn.
- Agent dùng LockWorkStation chuẩn, không thay thế màn hình đăng nhập hay hook cuộc gọi.
  Khả năng truy cập dịch vụ khẩn cấp trên thiết bị thực cần nghiệm thu riêng; DNS allow
  không tự biến website thành khả dụng khi desktop đang khóa.

## 5. Vai trò và tài khoản thử

Parent: quản lý trẻ của mình; child-view: chỉ đọc transparency của child gắn với device;
admin: thống kê vận hành, không tự có quyền đọc hồ sơ trẻ của parent khác.
Parent cấp token child-view 15 phút qua
`POST /api/v1/children/{child}/devices/{device}/child-view-token`.
Device token vẫn phục vụ agent; token child-view không được upload hoặc gửi yêu cầu.

Từ `server/`:

```powershell
# Mật khẩu được hỏi tương tác, không in ra log. Demo chỉ dùng development/test.
..\.venv\Scripts\python.exe -m app.seed --email demo@example.com --demo-child
# Provision admin qua quyền vận hành server, không qua đăng ký công khai.
..\.venv\Scripts\python.exe -m app.seed --email operator@example.com --role admin
```

Đăng nhập demo bằng email trên và mật khẩu vừa chọn. Admin dùng `/api/v1/auth/token`
rồi `/api/v1/admin/summary`. Không có mật khẩu demo hardcode.

## 6. Kiểm chứng

Tests mới bao phủ consent, báo chặn nhầm, role, erasure/ACK retry, ciphertext,
TLS pin mismatch không gửi credentials, named pipe nhiều kết nối, safety exemptions,
watchdog và policy expiry. Windows Service/ACL/DNS/Tray thực, browser SafeSearch,
latency và phép đo M1–M6 vẫn cần môi trường nghiệm thu; không lấy mock PASS thay evidence.
