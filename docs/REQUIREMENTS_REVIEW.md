# Đối chiếu yêu cầu — cập nhật 20/10/2026

Đã kiểm tra lại các sửa agent hiện có trước khi bổ sung source. Giữ bản sửa uninstall ở commit `86999a3`.
Các kết luận thiếu chức năng ở bản review trước được thay thế bằng bảng dưới đây.

## Các phần đã bổ sung

| Nhóm | Source hiện tại |
| --- | --- |
| Consent | Checkbox chủ động khi tạo mã; timestamp/version trên enrollment và device; không gán consent cho bản ghi cũ |
| Báo chặn nhầm | Tray → IPC → API → dashboard ghi nhận/từ chối/lời nhắn → command idempotent trả về Tray; sửa rule là thao tác riêng được UI giải thích |
| Xóa dữ liệu | Nút/API xóa hồ sơ và dữ liệu FK; receipt hash cho agent offline; dừng collectors, wipe cục bộ, retry ACK không thu thập lại |
| TLS | CA/hostname, TLS >=1.2, certificate pin cho HTTP/WS trước khi gửi token; HTTPS cần cấu hình pin |
| Mã hóa | AES-GCM email/tên trẻ/tên máy/phản hồi/command payload/control audit; email lookup HMAC; agent state AES-GCM + DPAPI Windows |
| Roles | Parent ownership, child-view chỉ đọc transparency, admin chỉ thống kê vận hành; provision qua CLI |
| Audit | Policy có source IP; audit tạo hồ sơ, consent, ghép máy, command và quyết định yêu cầu; trẻ xem được |
| Offline clock / expiry | Default strict sau reboot; policy fail-closed sau 7 ngày mất heartbeat, cấu hình được |
| Visibility | Tin Tray do watchdog khởi chạy; không xác nhận icon trong 30 giây ở desktop đăng nhập thì dừng và restore mạng |
| Safety | DNS exemptions ưu tiên cao, cấu hình cổng trường, không ghi activity cho tài nguyên được miễn |
| Windows | Sửa ACL kế thừa, từ chối filesystem links, pipe handle retry/race, restore cả adapter disconnected, backup registry trước khi ghi |
| Retention | Request/command/control audit thêm vào cleanup 90 ngày; agent prune theo giờ tin cậy trước upload, kể cả offline |
| Tài liệu/phụ thuộc | PRIVACY, bản trẻ, THREATMODEL, AI_USAGE, agent/requirements.txt, seed/provision CLI, hướng dẫn nâng cấp |

## Kết quả kiểm tra source

Lượt kiểm tra cuối ngày 20/10/2026:

- Server: **76 passed**.
- Agent: **114 passed, 21 skipped**.
- Dashboard JavaScript: **14/14 passed**.
- `git diff --check`: không có lỗi whitespace.

Các test bị skip không được tính là đạt. Bộ Python còn cảnh báo deprecation của
Starlette TestClient/httpx; không có test thất bại. Kết quả này không thay thế
nghiệm thu Windows Service, DNS và Tray trên máy thực tế.

## Không được đánh đồng với hoàn tất nghiệm thu

- Chưa chạy cài mới service/ACL/Tray/DNS trên máy Windows sạch. Named-pipe test thật không thay thế toàn bộ acceptance SCM/OS.
- Safety DNS allowlist không tự bảo đảm website truy cập được khi desktop khóa. Cần cấu hình cổng trường/cứu hộ thực tế và nghiệm thu chức năng khẩn cấp của thiết bị; không tuyên bố NT6 đã hoàn tất thực nghiệm.
- DoH/VPN/direct-IP và ngoại lệ upstream firewall vẫn có giới hạn; không tuyên bố chặn mọi bypass.
- HTTP lab không đáp ứng TLS production. Cần triển khai HTTPS, phân phối CA/pin tin cậy và kiểm chứng renew chứng chỉ.
- Máy offline chưa thể xác nhận xóa cục bộ. Receipt hash giữ tới ACK; backup/CSV ngoài ứng dụng cần xóa riêng.
- AES-GCM là mã hóa trường chọn lọc, không mã hóa toàn database; khóa phải được lưu và sao lưu an toàn.
- Operational state hiện hành / processed command IDs có vòng đời riêng để bảo vệ và chống replay, không phải activity history 90 ngày.
- Evidence M1–M6, performance, capture, video và báo cáo cuối chưa được tạo; không dùng mock hoặc test skipped làm evidence PASS.

## Trước khi chạy bản mới

Đọc [FINAL_CONTROLS.md](FINAL_CONTROLS.md): tạo DATA_ENCRYPTION_KEY một lần, sao lưu DB/khóa rồi chạy migration `f420_privacy`.
Giữ đúng khóa qua các lần khởi động/nâng cấp. SQLite cần >=3.35. `.env` và `ProgramData/OpenGuardKids/agent.env` đang dùng không tự cập nhật theo template.
Không có thay đổi trực tiếp lên DB, DNS hay service đang chạy trong lượt sửa source này.

README cài đặt tổng chưa được tuyên bố là đã nghiệm thu 15 phút trên máy sạch. Hướng dẫn nâng cấp hiện tại là tài liệu để áp dụng thay đổi source và chuẩn bị acceptance.
