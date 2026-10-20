# OpenGuard Kids Agent

Agent gồm Windows Service thực thi chính sách và Tray UI trong phiên người dùng, giao tiếp qua named pipe `\\.\pipe\OpenGuardKids`. Tray không giữ token server và không tự chạy bộ bảo vệ. Hướng dẫn cài cả hệ thống: [README gốc](../README.md).

## Phụ thuộc và cấu hình

Windows 10/11 x64, Python 3.13 x64 có Tcl/Tk, quyền Administrator để cài/gỡ. Tại thư mục gốc source:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r agent/requirements.txt
if (!(Test-Path agent/.env)) { Copy-Item agent/.env.example agent/.env }
```

Bỏ bước tạo venv nếu đã có. `pywin32`, `psutil`, DNS, Tray và thư viện mã hóa được cài từ requirements; không cần cài SQLite riêng.

| Biến trong `agent/.env` | Ý nghĩa |
| --- | --- |
| `OGK_SERVER_URL` | URL server; dùng IP LAN nếu khác máy |
| `OGK_POLICY_HMAC_SECRET` | Phải trùng secret policy phía server |
| `OGK_HEARTBEAT_INTERVAL_SEC` | Chu kỳ heartbeat, mặc định 60 giây |
| `OGK_RELOCK_DELAY_SEC` | Khoảng chờ khóa lại sau đăng nhập, mặc định 5 giây |
| `OGK_DNS_PORT` | Mặc định 53 để dùng DNS hệ thống |
| `OGK_DNS_UPSTREAM` | DNS chuyển tiếp, mặc định 1.1.1.1 |
| `OGK_DNS_AUTOCONFIG` | `auto`: service quản lý DNS/firewall/browser, console không tự đổi; có thể ép `true`/`false` |
| `OGK_DNS_FAILURE_MODE` | `open`: phục hồi DNS khi proxy lỗi; `closed`: giữ chặn DNS |
| `OGK_OFFLINE_CLOCK` | Mặc định `strict`, yêu cầu giờ tin cậy sau reboot offline |
| `OGK_POLICY_OFFLINE_DAYS` | Mặc định 7 ngày, hết hạn khóa screen-time tới khi đồng bộ lại |
| `OGK_TLS_CERT_SHA256` | SHA-256 chứng chỉ server dạng DER, bắt buộc với HTTPS/WSS |
| `OGK_TLS_CA_FILE` | Đường dẫn CA PEM tin cậy nếu dùng CA nội bộ |
| `OGK_SCHOOL_DOMAINS` | Cổng trường được miễn chặn, phân cách bằng dấu phẩy |

Thứ tự ưu tiên: môi trường process → `C:\ProgramData\OpenGuardKids\agent.env` → `agent/.env` → mặc định. Installer lưu cấu hình được bảo vệ vào ProgramData. Sửa `agent/.env` không tự thay bản service đã cài; người quản trị sửa file ProgramData rồi restart service. Không thay signing secret tùy tiện trên hệ thống đang dùng.

HTTPS kiểm tra CA, hostname, TLS ≥1.2 và certificate pin trước khi gửi token. Lấy pin từ chứng chỉ đã xác minh qua kênh quản trị; cập nhật khi đổi chứng chỉ. Không tắt xác minh TLS để xử lý lỗi pin. HTTP chỉ dành cho lab.

## Cài, chạy và ghép đôi

PowerShell Administrator tại thư mục gốc:

```powershell
.\.venv\Scripts\python.exe agent\openguard_service.py install
.\.venv\Scripts\python.exe agent\openguard_service.py status
```

Installer tạo thư mục dữ liệu với ACL SYSTEM/Administrators, đăng ký service LocalSystem tự khởi động và mở Tray trong phiên đăng nhập. Giữ source/interpreter ở thư mục trẻ không sửa được; giới hạn quyền đọc `agent/.env` chứa secret. Tài khoản trẻ không được thuộc Administrators.

Dashboard → hồ sơ trẻ → xác nhận thông báo → tạo mã ghép đôi. Nhập mã vào Tray trước khi hết hạn 10 phút. Máy đã ghép muốn ghép lại cần Administrator. Lệnh ghép qua IPC:

```powershell
.\.venv\Scripts\python.exe agent\openguard_agent.py enroll ABCD1234
```

Tray hiển thị trạng thái, thời gian còn lại, lý do chặn, yêu cầu thêm giờ/báo chặn nhầm và màn hình **Hôm nay / quyền riêng tư**. Ghi nhận báo chặn nhầm không tự mở rule: phụ huynh sửa chính sách riêng.

Đóng cửa sổ thu xuống Tray. Watchdog thử mở lại Tray khi mất; nếu không xác nhận biểu tượng tin cậy trong 30 giây ở desktop đã đăng nhập, service dừng và phục hồi mạng.

## Dừng, khởi động lại và gỡ

PowerShell Administrator:

```powershell
Stop-Service OpenGuardKids
Get-Service OpenGuardKids
Start-Service OpenGuardKids
# Sau khi sửa cấu hình service:
Restart-Service OpenGuardKids
# Gỡ khi không sử dụng nữa:
.\.venv\Scripts\python.exe agent\openguard_service.py remove
```

Khi dừng, runtime phục hồi DNS/firewall/browser từ backup. Lệnh remove thử phục hồi lại cả khi service từng crash, sau đó gỡ đăng ký dịch vụ. Không xóa ProgramData trước bước này vì chứa backup mạng. Gỡ service không đồng nghĩa xóa dữ liệu hồ sơ trên server; dùng chức năng xóa hồ sơ khi agent còn có thể kết nối để hoàn tất xóa cục bộ.

Nếu dừng lâu, xem `sc.exe queryex OpenGuardKids` và log trong ProgramData. Không chạy hai runtime cùng lúc hoặc kill tùy tiện trong lúc đang phục hồi mạng.

## Chạy console để phát triển

Chỉ chạy khi service đã dừng, từ PowerShell Administrator tại thư mục gốc:

```powershell
.\.venv\Scripts\python.exe agent\openguard_agent.py run
```

Runtime Windows tự quản lý Tray; nếu cần mở giao diện thủ công dùng `agent/agent_gui.py`. Chỉ mở GUI mà không có runtime sẽ báo “Dịch vụ bảo vệ chưa chạy”. Console với `OGK_DNS_AUTOCONFIG=auto` không tự đổi DNS adapter. Dừng bằng Ctrl+C để chạy cleanup.

## Kiểm tra DNS và browser

Thêm `example.com` vào blocklist, kiểm tra trực tiếp proxy:

```powershell
Resolve-DnsName example.com -Server 127.0.0.1 -DnsOnly
Get-NetAdapter | Format-Table ifIndex, Name, Status
Get-DnsClientServerAddress
```

Kết quả mong đợi NXDOMAIN và sự kiện `blocked_domain`. Nếu dùng console và cần đổi DNS thủ công, lưu DNS cũ, thay `18` bằng ifIndex đúng và chạy Administrator:

```powershell
Set-DnsClientServerAddress -InterfaceIndex 18 -ServerAddresses '127.0.0.1'
Clear-DnsClientCache
```

Khôi phục DNS tĩnh bằng địa chỉ cũ; chỉ dùng lệnh sau nếu cấu hình trước đó lấy DNS tự động:

```powershell
Set-DnsClientServerAddress -InterfaceIndex 18 -ResetServerAddresses
Clear-DnsClientCache
```

Không thêm DNS phụ ngoài proxy khi thử chặn. Kiểm tra cả IPv4/IPv6, Secure DNS/DoH và VPN. Browser có cache DNS và kết nối đang mở; sửa rule không cắt kết nối HTTPS hiện hữu. Sự kiện chặn chỉ chứng minh truy vấn đó bị từ chối, không chứng minh mọi kết nối đã bị cắt. Truy vấn nền có thể sinh sự kiện lặp sau cửa sổ gộp.

SafeSearch dùng rewrite DNS cho engine hỗ trợ; bật policy, kiểm tra DNS `www.google.com` và trang cài đặt SafeSearch trong browser. Không kiểm tra bằng nội dung không phù hợp thật. Dataset và fixture an toàn: [DOMAIN_CATEGORIES.md](../docs/DOMAIN_CATEGORIES.md).

## Xử lý lỗi thường gặp

| Hiện tượng | Kiểm tra |
| --- | --- |
| Tray không liên lạc dịch vụ | Service status, log ProgramData; tránh service và console giữ cùng pipe |
| SQLite không mở được | Đường dẫn dữ liệu, quyền SYSTEM/Administrators, ACL cả file và thư mục; không cấp quyền Everyone |
| DNS proxy không bind | UDP/TCP 53 bị chiếm, log bind; service phải chạy trước khi trỏ DNS local |
| Server không kết nối | URL, firewall, `/ready`, CA/pin; DNS máy có đang trỏ vào proxy đã dừng không |
| Policy bị từ chối | Secret HMAC hai phía, phiên bản/schema, thời gian và log |
| Offline sau reboot bị khóa | Hành vi strict; đưa server online để xác minh giờ, không xóa DB để reset quota |

Usage dùng monotonic và server anchor; không dùng wall clock để cấp quota mới. State/token mã hóa AES-GCM, khóa Windows được DPAPI bảo vệ. Không xóa/đổi khóa khi còn cần đọc state cũ. Xem [kiến trúc](../docs/ARCHITECTURE.md) và [quyền riêng tư](../docs/PRIVACY.md).
