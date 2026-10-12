# Agent Week 03

## Chạy trên Windows

Từ thư mục gốc:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirement.txt
.\.venv\Scripts\python.exe agent/agent_gui.py
```

Giữ `OGK_POLICY_HMAC_SECRET` trùng secret policy của server. Dùng mã ghép đôi
như trước. Runtime chỉ theo dõi process của tài khoản/session đang chạy agent.
Chạy bằng tài khoản của trẻ; quyền terminate phụ thuộc Windows. App hệ thống,
agent và các process cha của agent được bảo vệ khỏi terminate.

Không chạy CLI `run` và GUI cùng database: runtime lease chặn bản thứ hai.
Heartbeat một lần không khởi động monitor hoặc DNS. Khi ghép lại thiết bị, dừng
runtime trước; policy/quota cũ được reset, queue/cache cũ bị cách ly theo device.

Đây là desktop runtime có system tray, chưa phải Windows Service + IPC. Thoát
agent sẽ dừng bảo vệ. Tính năng chống trẻ tự tắt process/đổi DNS/DoH cần lớp quản
trị Windows riêng, không được coi là đã hoàn thành trong tuần 3.

## Cấu hình

`OGK_RELOCK_DELAY_SEC=5`: sau lần khóa của agent, khi phát hiện đăng nhập lại,
chờ ít nhất 5 giây trước khi khóa tiếp nếu lý do khóa vẫn còn. Lần khóa đầu không
bị trì hoãn. Áp dụng cho hết quota, ngoài lịch, clock chưa xác minh và LOCK_NOW;
command đến trong khoảng nghỉ được chấp nhận, counter thực hiện sau khi hết chờ.
Dùng đồng hồ monotonic; heartbeat/WebSocket dùng chung trạng thái trong runtime.
Cấu hình nhận số giây hữu hạn không âm; `0` tắt khoảng nghỉ. Đổi `.env` rồi thoát
agent qua menu tray và chạy lại. Thời điểm khóa thực tế phụ thuộc nhịp polling;
không tạo timer khóa nếu phụ huynh đã gỡ điều kiện khóa trong lúc chờ.
Khi đăng nhập lại mà điều kiện khóa vẫn còn, tray thông báo số giây còn lại một
lần, banner trong cửa sổ cập nhật đếm ngược theo nhịp kiểm tra của agent. Không
tạo popup mới mỗi giây. Đếm ngược và thông báo được kết thúc khi hết thời gian,
khi session khóa lại, hoặc điều kiện khóa đã được gỡ.

| Biến                                 | Mặc định  | Ý nghĩa                                          |
| ------------------------------------ | --------- | ------------------------------------------------ |
| `OGK_APPS_ENABLED`                   | `true`    | Monitor và chặn app                              |
| `OGK_APP_POLL_SEC`                   | `2`       | Polling 0.5–30 giây                              |
| `OGK_DNS_ENABLED`                    | `true`    | Bật DNS proxy loopback                           |
| `OGK_DNS_PORT`                       | `53`      | UDP và TCP cùng cổng                             |
| `OGK_DNS_UPSTREAM`                   | `1.1.1.1` | IP upstream, không dùng loopback                 |
| `OGK_EVENT_SYNC_SEC`                 | `5`       | Upload mỗi 1–60 giây; lỗi backoff tối đa 60 giây |
| `OGK_REPORT_TIMEZONE_OFFSET_MINUTES` | `420`     | Cùng timezone báo cáo server                     |

Các biến môi trường của process ưu tiên hơn `.env`. Không cần sửa secret để test.
Không tự thay DNS của adapter, chạy process thử nghiệm hoặc terminate app khi chạy
bộ test tự động.

## App monitor và usage

`service/apps/monitor.py` đọc PID, process name, executable path, create_time
trong session hiện tại. Path chỉ giữ trong bộ nhớ cho hasher; tên file là subject
gửi server. Tên không phù hợp schema `.exe` của server sẽ bị bỏ qua. Không đọc
window title, document name, command line, keystroke hay nội dung cửa sổ.

Hash dùng SHA-256, cache LRU theo path + size + mtime + ctime + file ID; kiểm tra
metadata trước/sau đọc. Không đọc được hash thì fallback tên process. Hash match
ưu tiên hơn name match, nên đổi `game.exe` thành `renamed.exe` vẫn bị chặn.
Monitor dùng `(PID, create_time)` chống nhầm PID tái sử dụng; recheck trước terminate.
Lỗi terminate báo trên UI và thử lại sau 10 giây; chỉ emit `blocked_app` khi lệnh
terminate thành công, một lần cho mỗi instance process. Đây là xác nhận Windows
chấp nhận terminate, không chờ tiến trình kết thúc mới ghi nhận.

`app_start` là thời điểm agent quan sát thấy process, không hồi tố thời gian trước
khi agent khởi động. `app_stop.duration_sec` được checkpoint mỗi 60 giây, khi
đổi policy, qua ngày hoặc process kết thúc. Phiên qua nửa đêm được tách ngày.
SQLite cập nhật `app_usage_daily` và event trong cùng transaction. Dừng sạch
flush phần cuối; crash có thể mất tối đa một checkpoint. App ngắn hơn khoảng
poll có thể không được quan sát. Thời lượng là thời gian process tồn tại, có thể
gồm chạy nền và nhiều process cùng ứng dụng; không phải foreground time hay
screen time. Không cộng tổng app để thay thế screen time.

## DNS, category và SafeSearch

Proxy bind `127.0.0.1` cả UDP/TCP, giới hạn worker và timeout. Forward UDP tới
upstream IP và fallback TCP nếu response bị truncate. Upstream lỗi trả SERVFAIL;
block trả NXDOMAIN. Không dùng HTTPS interception.

Thứ tự: explicit allow > explicit block > category > default allow. Rule match
hostname chính xác hoặc suffix có ranh giới dấu chấm; `notexample.com` không
match `example.com`. Category lấy `/agent/domain-categories`, cache offline và
refresh mỗi giờ. Có đủ 6 nhóm; dataset server hiện chỉ có 11 domain minh họa,
không phải bộ phân loại Internet đầy đủ. Chưa fetch được dataset thì category
fallback `unknown`, các luật allow/block trực tiếp vẫn hoạt động.

SafeSearch hiện hỗ trợ các host Google được liệt kê trong `dns/safesearch.py`
(gồm google.com, google.com.vn và www tương ứng): A/AAAA rewrite qua
`forcesafesearch.google.com`, bỏ HTTPS/SVCB để tránh IP hint đi đường khác.
Engine/miền ngoài danh sách không được rewrite. Tham khảo
[Google SafeSearch network guidance](https://support.google.com/websearch/answer/186669).

Query thật vẫn giữ hostname để resolve/match. Event chỉ lưu registrable domain
theo Public Suffix List đóng gói sẵn, không fetch PSL qua mạng; ví dụ
`secret.www.youtube.com` → `youtube.com`, `school.edu.vn` giữ nguyên.
Không lưu URL, query string hoặc arbitrary subdomain. A/AAAA và retry được gộp:
tối đa một event cùng loại/domain/policy mỗi 30 giây; report đếm lượt quan sát
đã gộp, không phải từng DNS packet. Block có event `blocked_domain`, allow có
`domain_query`.

### Test DNS cùng máy, chưa đổi adapter

Trong shell chạy agent:

```powershell
$env:OGK_DNS_PORT='15353'
.\.venv\Scripts\python.exe agent/agent_gui.py
```

Phụ huynh thêm `example.com` vào blocklist. Ở shell khác:

```powershell
.\.venv\Scripts\python.exe -c "import dns.message,dns.query; q=dns.message.make_query('example.com','A'); print(dns.query.udp(q,'127.0.0.1',port=15353,timeout=3))"
```

Mong đợi NXDOMAIN, UI giải thích danh sách chặn, Dashboard có blocked_domain.
Tránh dùng 5353 vì có thể đã bị ứng dụng khác giữ. Nếu bind thất bại, UI hiển thị
UDP/TCP, địa chỉ, cổng và mã lỗi. Kiểm tra bằng `netstat -ano | Select-String ':15353\s'`;
chọn cổng khác nếu cần, đồng thời đổi cổng trong lệnh query. Thoát agent bằng menu
tray **Thoát agent** trước khi chạy lại; đóng cửa sổ chỉ thu xuống tray.
Để test TCP thay `dns.query.udp` bằng `dns.query.tcp`. Để test SafeSearch dùng
`www.google.com`; mong đợi CNAME forcesafesearch.google.com khi policy bật.

### Dùng với browser

Cần agent chạy port 53 và cấu hình DNS adapter trỏ về 127.0.0.1. Trước khi đổi,
ghi lại DNS IPv4/IPv6 hiện tại bằng `Get-DnsClientServerAddress`. Chọn đúng
InterfaceIndex rồi chạy PowerShell admin, ví dụ:

```powershell
Set-DnsClientServerAddress -InterfaceIndex 12 -ServerAddresses '127.0.0.1'
Clear-DnsClientCache
```

Thay `12` bằng interface đã xác nhận trên máy. Khi dừng agent, khôi phục DNS đã
ghi lại; nếu ban đầu dùng DHCP có thể dùng:

```powershell
Set-DnsClientServerAddress -InterfaceIndex 12 -ResetServerAddresses
Clear-DnsClientCache
```

Không thêm DNS phụ để test blocking vì client có thể bỏ qua proxy. Browser Secure
DNS/DoH, VPN, DNS IPv6 khác, địa chỉ IP trực tiếp và DNS cache có thể bypass bộ lọc
này. Tắt Secure DNS trong browser test và kiểm tra cấu hình dual stack; bản hiện
tại chỉ listen IPv4 loopback. Kết nối đã mở không bị cắt ngay khi policy đổi.
Docker server publish port 8000 dùng bình thường; DNS proxy vẫn chạy trên host.

## Event queue, command và offline

`events` giữ UUID + payload bất biến + created_at + synced + rejection + owner.
Batch tối đa 100; timeout không đổi ID; chỉ ACK thuộc batch mới được đánh dấu
synced. Các lỗi vĩnh viễn của contract được lưu rejection, không retry vô hạn.
Lịch sử đồng bộ vẫn giữ để trẻ xem, dọn quá 90 ngày khi có đồng bộ server.
Danh tính lấy từ token; không thêm path/hash/free-form text vào event API.
Queue/cache cách ly khi device đổi, không gửi event của trẻ cũ với token mới.

Content protection, screen-time tick, WebSocket và network sync chạy độc lập.
Offline vẫn dùng last-known-good policy và queue SQLite. Khởi động offline vẫn
chặn app/domain; timestamp tạm dùng wall clock cho tới heartbeat đầu tiên, server
kiểm tra drift theo contract. Screen-time trusted-clock bootstrap giữ cơ chế
tuần 2; không tuyên bố lịch sử trước anchor là thời gian đã được xác thực.

`POLICY_UPDATED` xác minh HMAC, schema, version trước khi persist; không gửi
command ACK. Heartbeat báo version thực sự trong DB và gửi quota_date theo timezone
báo cáo. `quota_warning`, `locked`, `unlock_request`, `override_granted` nối vào
các hành động hiện có. Request xin giờ được ghi sau khi server nhận thành công.

Command processing serialize theo database; ADD_TIME cập nhật bonus, marker
processed command và override event trong cùng transaction. Mất ACK không cộng
giờ lần hai. OS lock không thể cùng transaction với SQLite: vẫn có cửa sổ crash
giữa thao tác OS và marker, không tuyên bố exactly-once cho OS side effect.

## Tray và minh bạch

Đóng cửa sổ thu xuống tray; menu mở UI, xem hôm nay hoặc thoát. Có thông báo lý do
app/domain bị chặn. **Hôm nay / quyền riêng tư** đọc cùng summary server mà phụ
huynh thấy, kèm activity, policy đang áp dụng cục bộ, audit cũ/mới và privacy.
Offline ghi rõ ngày cache và trạng thái event cục bộ chưa đồng bộ/bị từ chối.
Screen time cục bộ của máy được phân biệt với tổng server trên mọi thiết bị.
Mở lại mục này để refresh; history server giới hạn 100 event/audit theo contract.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest agent/tests -q
```

Unit tests dùng process/terminate giả; DNS test dùng loopback port tạm và upstream
giả, không đổi adapter. Integration A–D dùng API server thật với SQLite in-memory:
hash block app đổi tên → report; DNS block → report; offline/mất ACK → retry không
duplicate; child transparency summary bằng parent summary. Có test HMAC/schema,
policy downgrade, cache hash, midnight, ACK một phần, privacy, SafeSearch, UDP/TCP,
command concurrency. Test permission POSIX mode bỏ qua trên Windows vì không
chứng minh Windows ACL; ACL hardening cần được kiểm tra riêng khi đóng gói service.
