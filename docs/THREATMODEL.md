# Mô hình mối đe dọa

Phạm vi: parent dashboard, FastAPI/SQLite, Windows Service, Tray/IPC, DNS upstream.
Tài sản: token, khóa ký/mã hóa, dữ liệu trẻ, tính đúng của quota và policy.
Biên tin cậy: browser ↔ server, agent ↔ server, user session ↔ SYSTEM, OS clock ↔ server time.
Giả định: trẻ không có quyền administrator; parent/operator có thể dừng hoặc gỡ hợp pháp.
Không tuyên bố chống một administrator đã chiếm toàn bộ thiết bị.

## STRIDE

| # | Nhóm | Kịch bản | Kiểm soát trong source | Giới hạn / kiểm chứng cần thiết |
| --- | --- | --- | --- | --- |
| 1 | Spoofing | Người lạ đoán mã ghép | Mã 8 ký tự, hash, TTL 10 phút, one-time, rate limit | Đo giới hạn thử trong lab |
| 2 | Spoofing | Server giả lấy token | CA/hostname + TLS pin trước request HTTP/WS | Phân phối pin qua kênh tin cậy; HTTP lab không được bảo vệ |
| 3 | Tampering | Trẻ sửa policy hoặc phát lại bản cũ | HMAC, version, last-known-good, ACL | Người biết signing secret có thể tạo policy hợp lệ |
| 4 | Tampering | Chính trẻ chỉnh clock, restart để tăng quota | Monotonic, server anchor, persistent usage/grace, strict offline | Nghiệm thu reboot/clock thật; provisional chỉ lab |
| 5 | Repudiation | Phụ huynh phủ nhận thay đổi | Policy/control audit actor, IP, thời điểm, trước/sau | Admin DB có thể sửa audit; chưa có kho append-only ngoài máy |
| 6 | Information disclosure | IDOR xem trẻ của người khác | Ownership tại truy vấn, child-view giới hạn device/child | Cần test mọi endpoint mới |
| 7 | Information disclosure | Sao chép DB/state để lấy dữ liệu | AES-GCM trường định danh, hash secret, DPAPI + ACL agent | Không mã hóa toàn DB; backup/OS admin cần kiểm soát riêng |
| 8 | Denial of service | IPC client giữ pipe hoặc DNS flood | Timeout, worker bounded, giới hạn kích thước, health/rebind | Đo tài nguyên/khôi phục trên máy thử |
| 9 | Elevation of privilege | Client IPC giả báo idle/quản trị | Caller OS identity, trusted Tray PID/create-time, admin-only actions | Không tin caller tự khai PID; bảo vệ source/interpreter khỏi sửa |
| 10 | Tampering | Mất mạng/mất ACK gây cộng giờ hai lần | Command ID, SQLite transaction, retry cùng ID | Crash/reboot và concurrent delivery cần kiểm chứng |
| 11 | Information disclosure | Sản phẩm bị dùng làm stalkerware theo dõi người lớn | Consent rõ, icon, startup notice, tự dừng khi không có icon, privacy/child UI | Consent checkbox không chứng minh quan hệ giám hộ; operator phải kiểm soát phạm vi sử dụng |
| 12 | Tampering | DoH/VPN/direct IP bỏ DNS filtering | Browser policy, DNS guard, canary và endpoint list | Không chặn mọi VPN/DoH/direct-IP; ngoại lệ upstream firewall còn có giới hạn |
| 13 | Information disclosure | Trẻ tìm trợ giúp bị ghi vào report | Safety exemptions ưu tiên cao, không emit activity cho chúng | Cấu hình cổng trường/cứu hộ và nghiệm thu khi desktop khóa |
| 14 | Tampering | Xóa dữ liệu nhưng queue cũ upload trở lại | Xóa FK server, receipt hash, dừng collectors trước wipe, retry ACK | Máy không kết nối lại không thể xác nhận; backup xử lý riêng |

## Checklist ứng dụng theo nhóm ASVS

Đây là 22 điểm kiểm tra nội bộ, **không phải** tuyên bố đạt ASVS Level 1 hoặc mã requirement chính thức.
“Source” nghĩa là đã có cơ chế; acceptance cần ghi evidence riêng.

| # | Điểm kiểm tra | Trạng thái |
| --- | --- | --- |
| 1 | Password hash Argon2id | Source |
| 2 | Validation mật khẩu theo rubric | Source; không đồng nghĩa chính sách mật khẩu hiện đại đầy đủ |
| 3 | Khóa sau số lần sai / rate IP | Source + API tests |
| 4 | Session có expiry/revoke | Source |
| 5 | Cookie HttpOnly, SameSite | Source |
| 6 | Cookie Secure khi production | Config validation; cần TLS deployment |
| 7 | CSRF cho cookie-backed writes | API tests |
| 8 | Logout thu hồi session | Source |
| 9 | JWT kiểm tra signature/type/expiry | API tests |
| 10 | Device revoked bị từ chối | API tests |
| 11 | Parent ownership trong query | API tests |
| 12 | Child-view không ghi/control | API tests |
| 13 | Admin không tự đọc child reports | API tests |
| 14 | Request body/schema/size bounds | Source + API tests |
| 15 | SQL parameters, không ghép input vào query | Source review |
| 16 | DOM textContent và CSV formula neutralization | Source + dashboard tests |
| 17 | TLS >=1.2 và hostname/CA | Source; cần HTTPS deployment |
| 18 | Pin sai không gửi token HTTP/WS | Local TLS tests |
| 19 | AES-GCM và khóa ngoài source | Source + ciphertext tests |
| 20 | Không trả token/key qua IPC/child UI | Source review |
| 21 | Retention/xóa và offline retry | Source + regression tests |
| 22 | Audit và dữ liệu tối thiểu | Source; cần review endpoint mới |

Các bài test giả lập không thay thế test ACL/SCM/Tray/DNS trên Windows thật.
Không tạo evidence an toàn mạng, performance hay video khi chưa chạy phép đo.
