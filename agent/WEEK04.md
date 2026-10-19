# Agent Week 04 — Windows Service, chống bypass, DNS/App protection

Mục tiêu tuần 4 (phần Thịnh, A1–A7): biến Agent từ runtime nằm trong process GUI
thành **protection runtime** chạy như Windows Service, khó bypass.

```text
Tray = UI          Service = Protection
Đóng Tray          → Service vẫn chạy
Logout / restart UI → protection vẫn chạy
```

Sơ đồ: [`docs/diagrams/agent-service-tray.mmd`](../docs/diagrams/agent-service-tray.mmd).

## Cài đặt trên Windows 10/11

Chạy PowerShell **Run as administrator** tại thư mục gốc dự án:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirement.txt   # gồm pywin32 trên Windows
Copy-Item .env.example .env   # sửa OGK_SERVER_URL, OGK_POLICY_HMAC_SECRET (trùng server)
.\.venv\Scripts\python.exe agent\openguard_service.py install
.\.venv\Scripts\python.exe agent\openguard_service.py status       # OpenGuardKids: RUNNING
```

`install` làm các việc sau:

1. Kiểm tra cấu hình (`AgentConfig.from_env()`), lỗi thì dừng trước khi cài gì.
2. Tạo `C:\ProgramData\OpenGuardKids`, đặt ACL chỉ SYSTEM + Administrators
   (token, policy cache, event queue, log). Chép các biến `OGK_*` vào
   `agent.env` trong thư mục này — trẻ không đọc được secret.
3. Đăng ký service `OpenGuardKids` (LocalSystem, Automatic). Khi cài từ venv,
   service chạy interpreter gốc và nạp site-packages của venv qua biến
   `OGK_SITE_PACKAGES` trong registry của service (launcher `python.exe` của
   venv tạo process con mà SCM không theo dõi được → lỗi 1053).
4. Recovery: restart sau 5 s, 5 s, 30 s; `failureflag 1` để cả lần thoát mã
   khác 0 cũng được restart. DACL service: user thường chỉ query, không start/stop.
5. Start service. Service tự mở Tray trong session của người đang đăng nhập.

Sau khi cài: **xóa hoặc giới hạn quyền đọc `.env` ở thư mục dự án** (lệnh install
có nhắc), cài dự án ở thư mục mà tài khoản của trẻ không ghi được (ví dụ
`C:\OpenGuardKids`), và tài khoản của trẻ **không** thuộc nhóm Administrators.

Ghép thiết bị: mở Tray → nhập mã 8 ký tự. Lần đầu (chưa ghép) ai cũng ghép được;
khi máy **đã ghép**, ghép lại cần Administrator (chạy Tray bằng Run as
administrator, hoặc `python agent\openguard_agent.py enroll CODE` trong PowerShell
admin — lệnh này gửi qua IPC tới service).

Gỡ cài đặt (Administrator):

```powershell
.\.venv\Scripts\python.exe agent\openguard_service.py remove
```

Service dừng → runtime khôi phục DNS adapter, xóa rule firewall, trả policy trình
duyệt về giá trị cũ; `remove` chạy lại bước khôi phục từ backup trong `agent.db`
phòng trường hợp service đã crash, rồi mới gỡ service. Sự kiện
`SERVICE_STOP` / `SERVICE_UNINSTALL` được ghi vào `security_events`.

### Chạy không cần Windows Service (dev, Linux)

```bash
.venv/bin/python agent/openguard_agent.py run   # cùng AgentRuntime với service
.venv/bin/python agent/agent_gui.py              # Tray, nói chuyện qua IPC
```

`run` dùng `InteractiveHost` (API của session hiện tại) và Unix socket
`agent.sock` cạnh state file (hoặc `/tmp/openguard-<uid>-<hash>.sock` nếu đường
dẫn dài quá giới hạn `sun_path`). Ở chế độ này không tự đổi DNS adapter
(`OGK_DNS_AUTOCONFIG=auto`). Tray không còn tự chạy bảo vệ: thiếu runtime thì
Tray hiển thị “Dịch vụ bảo vệ chưa chạy”.

## A1 — Windows Service thật

| File | Vai trò |
| --- | --- |
| `openguard_service.py` | `ServiceFramework` + `install/remove/status` |
| `service/runtime.py` | `AgentRuntime`: một runtime cho cả service và `run` |
| `service/host.py` | `InteractiveHost` / `ServiceHost`: probe session, khóa máy, liệt kê process |
| `service/windows/session.py` | WTS API: session console, trạng thái khóa, `CreateProcessAsUser` |

Trong session 0, `GetLastInputInfo`, `OpenInputDesktop`, `LockWorkStation` chỉ
thấy desktop của service. `ServiceHost` vì vậy:

- **Session khóa/mở:** `WTSQuerySessionInformation(WTSSessionInfoEx)` trên
  session console đang active. Không có người đăng nhập = coi như khóa (không đếm giờ).
- **Khóa máy:** chạy `rundll32 user32.dll,LockWorkStation` *trong session của trẻ*
  bằng `WTSQueryUserToken` + `CreateProcessAsUser`; lỗi thì `WTSDisconnectSession`
  (về màn hình đăng nhập, ứng dụng vẫn chạy).
- **App monitor:** process của session console, bỏ qua tài khoản hệ thống
  (`NT AUTHORITY\…`, `Window Manager\…`, `Font Driver Host\…`).
- **Idle:** Tray gửi `report_idle` mỗi 5 s. Chỉ chấp nhận từ Tray do service tự
  khởi chạy (PID hoặc process con của nó) — script trẻ tự viết kết nối được pipe
  nhưng không làm service ngừng đếm giờ. Không có báo cáo mới (≤ 15 s) thì coi
  trẻ **đang dùng máy**: mất Tray chỉ làm việc đếm chặt hơn, không bao giờ cho
  thêm giờ.

Heartbeat, policy, screen-time, app/DNS protection, WebSocket và event sync chạy
trong runtime của service (`HeartbeatWorker`, `ProtectionWorker`, `ContentRuntime`
tái sử dụng từ tuần 2–3).

## A2 — Tray ↔ Service IPC

Named pipe `\\.\pipe\OpenGuardKids`, mỗi lời gọi = 1 dòng JSON request + 1 dòng
JSON response (`service/ipc/`). Overlapped I/O với timeout 5 s, tối đa 8 client
đồng thời — client treo không chặn được service.

- DACL `D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x12019b;;;IU)(D;;GA;;;NU)`: Interactive
  users chỉ đọc/ghi dữ liệu, **không có `FILE_CREATE_PIPE_INSTANCE`** nên không
  giả mạo được server pipe; đăng nhập qua mạng bị từ chối; thêm
  `PIPE_REJECT_REMOTE_CLIENTS`. Instance đầu dùng `FILE_FLAG_FIRST_PIPE_INSTANCE`
  để phát hiện pipe đã bị chiếm tên.
- Danh tính caller do OS cung cấp: `GetNamedPipeClientProcessId/SessionId`,
  quyền admin qua `ImpersonateNamedPipeClient` + `CheckTokenMembership` (admin
  chưa elevate dưới UAC = không phải admin).
- Tray không giữ token, secret hay database; chỉ render `status` và gửi yêu cầu.

| Method | Ai được gọi | Ghi chú |
| --- | --- | --- |
| `status`, `events` | mọi user tương tác | `events` theo cursor; Tray mới mở không nhận lại thông báo cũ |
| `heartbeat_now` | mọi user | giới hạn 1 lần / 3 s |
| `request_extra_time` | mọi user | 5–60 phút, 1 lần / 10 s |
| `transparency` | mọi user | 1 lần / 2 s |
| `report_idle` | chỉ Tray do service khởi chạy | xem A1 |
| `enroll` | ai cũng được khi chưa ghép; **Administrator** khi đã ghép | chống trẻ ghép máy vào tài khoản khác |
| `set_sync_paused` | **Administrator** | tạm dừng chỉ heartbeat, bảo vệ vẫn chạy |

Không có method dừng bảo vệ. Menu Tray bỏ mục “Thoát agent”; đóng cửa sổ chỉ ẩn
xuống khay. Kill Tray → `TrayWatchdog` mở lại sau tối đa ~10 s (NT1: biểu tượng
luôn hiển thị khi agent chạy).

## A3 — Persist trusted clock

`service/clock/monitor.py`, bảng `clock_anchor` (1 dòng):
`server_time`, `mono`, `boot_id`, `floor_time`.

| Tình huống khởi động | Mode | Nguồn giờ |
| --- | --- | --- |
| Heartbeat thành công | `server` | anchor server + monotonic |
| Restart process, **cùng boot** (BootId trong registry trùng) | `restored` | anchor cũ + monotonic (đồng hồ monotonic chạy liên tục dù process chết) |
| Sau reboot, chưa có server | `provisional` | `max(đồng hồ Windows, floor_time)`, sau đó chạy theo monotonic |
| Sau reboot, `OGK_OFFLINE_CLOCK=strict` | chưa sẵn sàng | khóa máy sau 30 s như tuần 2 |

`floor_time` = thời điểm tin cậy cuối cùng, ghi mỗi 10 s. Lùi đồng hồ qua reboot
không đưa thời gian về trước floor (ghi `clock_events`). Ở mode `provisional`
đổi đồng hồ sau khi khởi động cũng không có tác dụng (chạy theo monotonic). Heartbeat
đầu tiên thay anchor và **ghi đè** floor bằng giờ server, nên giờ provisional chạy
lố cũng được sửa. Không prune event 90 ngày khi giờ chưa được server xác minh.

Giới hạn: tắt máy, chỉnh đồng hồ **tiến** sang ngày mới, rồi khởi động lại khi
**không có mạng** — agent không phân biệt được với việc máy tắt qua đêm, nên cấp
quota ngày mới cho tới heartbeat đầu tiên. Ai không chấp nhận rủi ro này dùng
`OGK_OFFLINE_CLOCK=strict` (fail-closed).

## A4 — Persist grace state

Bảng `grace_state(date, deadline, started_at)` (`UsageRepository`). Lần đầu hết
quota ghi deadline theo trusted time; restart giữa grace đọc lại deadline và chỉ
còn phần giây còn lại (`GRACE_STARTED` kèm `resumed: true`); restart sau deadline
khóa ngay. Có thêm giờ (ADD_TIME) hoặc sang ngày mới → xóa grace, lần hết giờ
tiếp theo có grace mới. Cảnh báo 10/5/1 phút đã được lưu từ tuần 2 (`warning_state`).

## A5 — Anti-kill / runtime hardening

- **Một runtime:** `agent.host.lock` (khóa file OS tự nhả khi process chết) +
  pipe `FIRST_PIPE_INSTANCE`; service thứ hai hoặc `run` song song bị từ chối.
  `ProtectionWorker` vẫn giữ `agent.runtime.lock` như tuần 3.
- **Kiểm soát stop:** DACL service — trẻ (Interactive/Users) không stop/pause
  được; SCM vẫn cho Administrator stop (hợp pháp, có ghi `SERVICE_STOP`).
- **Crash:** supervisor 2 s khởi động lại `ProtectionWorker`/`HeartbeatWorker`
  chết; `ContentRuntime` tự thử lại app/DNS với backoff 1→60 s. Quá 5 lần
  restart / 5 phút → `os._exit(1)` để SCM recovery khởi động lại cả process.
  Kill process service → SCM restart sau 5 s; trạng thái (enrollment, policy,
  quota, grace, clock anchor, event queue) nằm trong SQLite nên không mất.
- **Dữ liệu:** ACL thư mục ProgramData; trẻ không sửa/xóa được database.
- **Không làm** (danh mục cấm của đề bài): không ẩn process/service, không chặn
  Administrator gỡ cài đặt, không chống gỡ kiểu mã độc.

## A6 — DNS hardening

Bật khi chạy service (`OGK_DNS_AUTOCONFIG=auto`, port phải là 53):

| Đường vòng | Xử lý |
| --- | --- |
| DNS adapter khác proxy | `NetworkGuard` trỏ mọi adapter đang Up về `127.0.0.1` + `::1`; kiểm tra lại mỗi 30 s (adapter mới, VPN, DHCP). Backup cấu hình gốc (DHCP/static theo registry `Tcpip[6]\…\NameServer`) trước lần đổi đầu. |
| IPv6 DNS (RA/DHCPv6) | Proxy listen cả `[::1]:53` UDP/TCP; adapter IPv6 trỏ `::1`. |
| Gõ DNS server trực tiếp (`nslookup x 8.8.8.8`) | Firewall chặn outbound 53 UDP/TCP tới mọi địa chỉ **trừ upstream** của agent; chặn 853 (DoT) mọi nơi. Loopback không bị firewall lọc. |
| DoH trong trình duyệt | Policy HKLM `DnsOverHttpsMode=off` (Chrome, Edge, Brave), `DNSOverHTTPS Enabled=0 Locked=1` (Firefox); proxy trả NXDOMAIN cho canary `use-application-dns.net` và các endpoint DoH phổ biến (`dns.google`, `cloudflare-dns.com`, …, reason `doh_endpoint`). |
| Proxy lỗi | Probe tên nội bộ `ogk-health.invalid` mỗi 15 s; 2 lần lỗi → bind lại. `OGK_DNS_FAILURE_MODE=open` (mặc định): khi proxy không khỏe, trả DNS gốc cho adapter + gỡ firewall để trẻ vẫn vào được trang trường/111 (NT6), bật lại ngay khi proxy khỏe; `closed`: giữ chặn. |
| Service dừng/gỡ | Khôi phục toàn bộ từ backup. |

Giới hạn còn lại (ghi vào báo cáo M3): VPN/proxy cài sẵn bởi admin, ứng dụng tự
mang DoH với IP cứng (không qua policy trình duyệt), truy cập trực tiếp bằng địa
chỉ IP, kết nối đã mở trước khi policy đổi, Safe Mode (service không chạy), khởi
động từ USB. Tài khoản Windows khác: service áp dụng cho **session console đang
active**, kể cả tài khoản của phụ huynh — policy hiện theo thiết bị, chưa theo user.

## A7 — Kiểm thử

Tự động (Linux/Windows, không đụng OS thật):

```bash
.venv/bin/python -m pytest agent/tests -q
```

- `test_week04_persistence.py` — clock restored/provisional/floor, grace qua restart.
- `test_week04_runtime.py` — IPC Unix socket, quyền admin, rate limit, supervisor
  restart + crash loop, idle tin cậy, TrayWatchdog, và **end-to-end với server API
  thật**: enroll qua IPC → heartbeat → đóng Tray → server offline → restart runtime
  vẫn giữ enrollment/clock.
- `test_week04_network.py` — NetworkGuard (backend giả), fail-open/closed, IPv6
  listener, DoH/canary/health, rebind proxy chết.

Acceptance trên Windows thật (thay đổi trạng thái OS, mặc định bị skip):

```powershell
$env:OGK_WINDOWS_ACCEPTANCE='1'; $env:OGK_ACCEPTANCE_BLOCKED_DOMAIN='example.com'
$env:OGK_ACCEPTANCE_BLOCKED_SHA256=(Get-FileHash C:\Windows\System32\notepad.exe).Hash
.\.venv\Scripts\python.exe -m pytest agent/tests/windows -v -rs
powershell -ExecutionPolicy Bypass -File agent\scripts\collect-evidence.ps1
```

Bằng chứng: `%TEMP%\openguard-acceptance.jsonl` và thư mục `evidence\week04-*`.

### Đối chiếu các bài test bắt buộc (phía Agent)

| Scenario | Kỳ vọng | Kiểm chứng |
| --- | --- | --- |
| Đổi Windows clock ± giờ/ngày | Quota/schedule không bị bypass | `test_clock_monitor`, `test_week04_persistence` (rollback qua reboot, đổi giờ khi provisional); thủ công: đổi giờ khi service chạy |
| Restart Agent trong grace | Không nhận grace mới | `test_restart_during_grace_does_not_grant_new_grace`, `test_restart_after_grace_expired_locks_immediately` |
| Đóng Tray | Protection vẫn chạy | `test_tray_closed_and_service_restarted_…`; Windows: `test_closing_tray_keeps_protection_and_tray_returns` |
| Kill/restart Service | Recover, state không mất | `test_supervisor_restarts_…`; Windows: `test_killing_service_recovers_without_losing_state` |
| Server offline | App/DNS/screen-time vẫn enforce | e2e runtime (offline), `test_week03_integration` |
| WebSocket mất | Heartbeat fallback | tuần 3 + supervisor giữ heartbeat |
| ACK mất | Resend nhưng không chạy 2 lần | `test_concurrent_add_time_once_and_atomic_outbox` (tuần 3) |
| Rename blocked executable | SHA-256 vẫn block | tuần 3 + Windows: `test_renamed_blocked_executable_is_terminated_by_hash` |
| DNS blocked domain | NXDOMAIN + event | tuần 3 + Windows: `test_blocked_domain_and_doh_endpoint_get_nxdomain` |
| Revoked device | Không heartbeat/event | server (Bảo, S1); Tray hiển thị “Cần ghép lại” |

Cần người thao tác (ghi video/ảnh cho Security Test Evidence):

1. **LockWorkStation:** phụ huynh bấm Khóa ngay → máy khóa ≤ 5 s; đặt quota 3 phút → khóa sau grace.
2. **Idle:** không chạm máy 6 phút với idle 5 phút → “Còn lại” ngừng giảm; đóng Tray → vẫn đếm (có chủ đích).
3. **Restart/reboot:** reboot khi đang online → service tự chạy, Tray tự hiện, quota hôm nay giữ nguyên;
   rút mạng rồi reboot → mode `provisional`, app/DNS vẫn chặn.
4. **Đổi giờ khi service chạy:** `Set-Date (Get-Date).AddHours(3)` → quota/lịch không đổi; heartbeat sau ghi drift.
5. **Trẻ thử dừng:** tài khoản thường chạy `sc stop OpenGuardKids` → Access denied; Task Manager kill
   `python.exe` của service → Access denied (process SYSTEM).

## Cấu hình mới

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `OGK_OFFLINE_CLOCK` | `provisional` | `strict` = sau reboot không có server thì khóa tới khi xác minh giờ |
| `OGK_DNS_AUTOCONFIG` | `auto` | `auto`: chỉ service đổi adapter/firewall/policy trình duyệt; `true`/`false` ép bật/tắt |
| `OGK_DNS_FAILURE_MODE` | `open` | `open` khôi phục DNS gốc khi proxy lỗi; `closed` giữ chặn |
| `OGK_IPC_ADDRESS` | pipe / `agent.sock` | đổi địa chỉ IPC (test) |
| `OGK_TRAY_COMMAND` | `pythonw.exe agent_gui.py --background` | lệnh service dùng để mở Tray |

## Trạng thái kiểm chứng

Toàn bộ test tự động chạy trên Linux. Các phần chỉ có trên Windows (pywin32
service, named pipe, WTS, PowerShell DNS/firewall, registry) được viết theo API
chính thức nhưng **cần chạy acceptance trên máy Windows 10/11 thật** trước khi
demo; ghi kết quả vào báo cáo cùng thư mục evidence.
