# Quyền riêng tư — OpenGuard Kids

Phiên bản 1.1, đối chiếu source 20/10/2026. Đây là mô tả kỹ thuật, không phải chứng nhận pháp lý hoặc evidence nghiệm thu Windows.
Bản dành cho trẻ: [PRIVACY_CHILD.md](PRIVACY_CHILD.md).

## Phạm vi

Chỉ dùng trên thiết bị được phép quản lý, với thông báo rõ cho phụ huynh và trẻ. Không dùng để theo dõi người lớn hoặc chạy bí mật.
Phụ huynh phải chủ động xác nhận thông báo trước khi tạo mã ghép; checkbox không được chọn sẵn. Việc này không thay thế việc giải thích cho trẻ.
Không thu keystroke, screenshot, tin nhắn, email/tài liệu, âm thanh, camera, clipboard, window title hoặc URL đầy đủ. Không có analytics/quảng cáo bên thứ ba. DNS upstream vẫn nhìn thấy truy vấn cần phân giải.

## Bảng dữ liệu

| Trường / nhóm trường | Mục đích | Thời hạn / điều kiện xóa | Ai xem được |
| --- | --- | --- | --- |
| User ID, email, role | Đăng nhập, xác định người quản lý | Vòng đời tài khoản | Phụ huynh sở hữu, dịch vụ xác thực |
| Password hash, email lookup HMAC | Kiểm tra mật khẩu, tìm tài khoản | Vòng đời tài khoản | Server, không trả API |
| WebSession hash, CSRF, expiry, revoked_at | Phiên web, chống CSRF | Hết hạn/thu hồi và cleanup định kỳ | Server, trình duyệt nhận cookie/CSRF cần thiết |
| Child ID, parent ID, display_name, birth_year | Hồ sơ và quyền sở hữu | Tới khi xóa hồ sơ | Phụ huynh sở hữu, trẻ trong phạm vi UI |
| Device ID, child ID, device_name, fingerprint_hash | Ghép và quản lý đúng máy | Tới khi xóa hồ sơ | Phụ huynh sở hữu, agent tương ứng |
| Device status, last_seen, policy_version, quota_used, clock_drift | Trạng thái bảo vệ | Giá trị hiện hành, tới khi xóa hồ sơ | Phụ huynh, agent/Tray |
| Enrollment code hash, expires_at, used_at | Mã một lần, TTL 10 phút | Cleanup sau khi hết hạn/đã dùng hơn một ngày | Server; phụ huynh nhận mã gốc một lần |
| Consent timestamp, privacy_notice_version | Ghi nhận xác nhận thông báo | Bản Device tới khi xóa hồ sơ | Server, người vận hành được phép |
| Access token, refresh token hash | Agent xác thực và refresh | Access 15 phút, refresh 30 ngày theo cấu hình; thu hồi/cleanup | Token gốc chỉ agent; server giữ refresh hash |
| Policy ID/version/signature/payload | Quota, lịch, rule app/domain, toàn vẹn | Vòng đời hồ sơ; policy cache cũ agent dọn sau 90 ngày | Phụ huynh, trẻ qua transparency, agent |
| Audit actor_id, source_ip, timestamp, giá trị cũ/mới | Ai thay đổi gì, khi nào | 90 ngày hoặc xóa hồ sơ | Phụ huynh trong phạm vi quyền, trẻ qua transparency |
| Event ID, device/child ID, type, subject, duration_sec, policy_id | Báo cáo tối thiểu, chống duplicate | 90 ngày hoặc xóa hồ sơ | Phụ huynh sở hữu, trẻ |
| occurred_at, received_at, effective_at, clock_trusted, payload_hash | Giờ nguồn/server và kiểm tra duplicate | Cùng event: 90 ngày | Server; timestamp/trust được công bố cho trẻ |
| ScreenUsageDaily: device/child, date, duration_sec | Screen time theo ngày | 90 ngày hoặc xóa hồ sơ | Phụ huynh, trẻ |
| ChildRequest: type, minutes hoặc subject, status, response, timestamps | Xin thêm giờ / báo chặn nhầm | 90 ngày hoặc xóa hồ sơ | Phụ huynh và trẻ liên quan |
| DeviceCommand: type, payload, sent/ACK/status/error | Điều khiển, retry ACK | 90 ngày hoặc xóa hồ sơ | Server/agent; phụ huynh và trẻ nhận phản hồi |
| Local app_usage_daily: date, basename, SHA-256, duration | Nhận dạng app và thời lượng tiến trình | 90 ngày hoặc erasure | Agent; tổng hợp được hiển thị theo chức năng |
| PID, executable path, process creation time | Hash file, tránh kill nhầm PID | Chỉ bộ nhớ/cache runtime; không upload path | Agent |
| Local policy/clock/remote-lock/grace, processed command IDs | Offline, chống lặp | State vận hành hiện hành; xóa khi erasure | Agent, admin OS có quyền storage |
| Content cache / transparency snapshot | Hiển thị offline | Snapshot quá 90 ngày được dọn; categories không phải dữ liệu cá nhân | Trẻ qua Tray, agent |
| DNS adapter/browser-policy backup | Khôi phục mạng | Xóa khi restore thành công; giữ khi lỗi để retry | Service/admin OS |
| Erasure receipt: random ID, token hash, timestamps | Gửi yêu cầu xóa tới máy offline | Tới khi ACK; không giữ tên/hoạt động/child ID | Endpoint chỉ đối chiếu secret tương ứng |

Subject activity là executable basename hoặc registrable domain. SHA-256 không phải trường của mọi activity upload. Báo chặn nhầm dùng hostname cụ thể hoặc tên .exe để chỉ đúng rule; không nhận URL/path.
Truy vấn tới safety exemptions không được ghi activity. DNS khác có thể do app nền; không suy ra đó là hành động chủ động của trẻ.

## Bảo vệ và quyền xem

Server mã hóa email, tên trẻ, tên máy và phản hồi phụ huynh bằng AES-GCM. Khóa DATA_ENCRYPTION_KEY lấy từ môi trường, không có khóa hardcode. Email lookup dùng HMAC, mật khẩu dùng Argon2id, mã ghép/refresh secret dùng hash. Metadata và activity khác vẫn đọc được trong DB; đây không phải full-disk encryption.
State agent chứa token được AES-GCM mã hóa. Trên Windows khóa được DPAPI bọc, thư mục đặt ACL SYSTEM/Administrators. DPAPI machine scope phụ thuộc ACL và không chống admin/SYSTEM đã bị chiếm quyền. Dev ngoài Windows dùng file key 0600.
HTTPS/WSS kiểm tra CA, hostname, TLS >=1.2 và certificate pin trước khi gửi token. HTTP chỉ phục vụ lab, không đạt nghiệm thu TLS.

Parent chỉ quản lý hồ sơ thuộc quyền sở hữu. Child-view chỉ đọc transparency của child gắn với device, không được upload hay điều khiển. Admin API chỉ thống kê vận hành, không tự vượt ownership để đọc hồ sơ trẻ. Quyền OS/DB/backup có thể vượt kiểm soát API; cần giới hạn người vận hành.
Tray hiển thị usage, hoạt động, policy và audit. API giới hạn mỗi danh sách gần đây, không phải bản tải toàn bộ lịch sử. Không xác nhận icon trong 30 giây ở desktop đang đăng nhập thì runtime dừng bảo vệ.

## Xóa và offline

Nút Xóa toàn bộ dữ liệu xóa hồ sơ và dữ liệu FK liên quan trên server trong một transaction. Receipt hash tối thiểu cho phép máy offline nhận yêu cầu sau đó. Agent dừng collectors trước khi xóa cache/queue/usage/policy/clock; mất ACK thì retry mà không thu thập lại. Không thể xác nhận máy offline đã xóa ngay cùng thời điểm server.
State vận hành không tự hết hạn sau 90 ngày nếu vẫn cần cho policy, chống lặp hoặc khôi phục mạng. Cleanup activity dùng giờ đã xác minh. Backup, CSV tải xuống, OS logs và bản sao ngoài ứng dụng cần quy trình xóa riêng. SQLite secure-delete/VACUUM không chứng minh xóa vật lý mọi byte trên SSD/backup.

Chi tiết khóa, migration và giới hạn: [hướng dẫn server](../server/README.md) và [hướng dẫn agent](../agent/README.md).
