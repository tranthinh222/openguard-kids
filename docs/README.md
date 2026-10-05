# OpenGuard Kids Agent — Policy Manager và Screen-Time Counter

Tài liệu này tổng hợp hai chức năng nghiệp vụ được triển khai cho Agent trong
Week 02. Phần giao diện Tkinter không nằm trong phạm vi tài liệu này.

## 1. Policy Manager

### Mục tiêu

Policy Manager nhận policy từ server, kiểm tra tính toàn vẹn và cấu trúc dữ
liệu trước khi cho Agent sử dụng. Agent luôn giữ **last-known-good policy**:
nếu policy mới không hợp lệ thì policy tốt gần nhất vẫn tiếp tục hoạt động.

### Các module đã tạo

```text
agent/service/policy/
├── __init__.py
├── manager.py
├── models.py
└── verifier.py
```

- `manager.py`: điều phối việc kiểm tra, lưu và kích hoạt policy; quản lý SQLite
  và ghi security event.
- `models.py`: định nghĩa model `Policy`, `ScreenTimePolicy` và validate schema.
- `verifier.py`: tạo canonical JSON và xác minh chữ ký HMAC-SHA256.

### Các file đã thêm/sửa và lý do

#### `agent/service/__init__.py` — file mới

Đã thêm package gốc cho tầng business service của Agent.

**Tại sao cần thay đổi:** trước Week 02, nghiệp vụ chủ yếu nằm trong một file
`openguard_agent.py`. Package `service` tạo ranh giới rõ ràng để Policy Manager,
Screen-Time Counter và các service tương lai không bị trộn với CLI hoặc UI.

#### `agent/service/policy/__init__.py` — file mới

Đã export các thành phần chính như `PolicyManager`, `PolicyRepository`,
`Policy`, `ScreenTimePolicy` và các exception liên quan.

**Tại sao cần thay đổi:** các module bên ngoài có thể import từ
`service.policy` qua một API thống nhất, thay vì phụ thuộc trực tiếp vào cấu
trúc file nội bộ.

#### `agent/service/policy/models.py` — file mới

Đã thêm:

- `PolicyValidationError` cho lỗi schema.
- `ScreenTimePolicy` để biểu diễn quota, idle timeout, grace period và warning.
- `Policy` để biểu diễn toàn bộ policy đã parse.
- `Policy.from_envelope()` để validate dữ liệu nhận từ server.
- `is_allowed_at()` để ánh xạ thời gian hiện tại vào một trong 336 schedule
  slot.
- `quota_seconds_at()` để chọn quota ngày thường hoặc cuối tuần.

**Tại sao cần thay đổi:** dữ liệu từ mạng không được tin tưởng ngay. Agent cần
chuyển dữ liệu thô thành model hợp lệ trước khi lưu hoặc áp dụng, tránh policy
thiếu version, signature sai định dạng, lịch sai 336 slot hoặc quota ngoài giới
hạn.

#### `agent/service/policy/verifier.py` — file mới

Đã thêm:

- `canonical_policy_json()` để serialize payload giống phía server.
- `expected_signature()` để tính HMAC-SHA256 từ version và payload.
- `verify_signature()` để so sánh chữ ký bằng `hmac.compare_digest()`.

**Tại sao cần thay đổi:** cùng một payload JSON có thể có nhiều cách trình bày
khác nhau. Canonical JSON bảo đảm Agent và server ký đúng cùng một chuỗi byte.
HMAC giúp Agent phát hiện policy bị chỉnh sửa hoặc được tạo bởi nguồn không có
shared secret.

#### `agent/service/policy/manager.py` — file mới

Đã thêm:

- `PolicyRepository` để tạo và truy cập hai bảng `policies` và
  `security_events` trong SQLite.
- `PolicyManager.accept()` để điều phối validate, verify HMAC, kiểm tra version,
  lưu và kích hoạt policy.
- Logic chống policy downgrade.
- Logic phát hiện cùng version nhưng khác signature.
- Cơ chế last-known-good policy.
- Ghi log và security event khi policy bị từ chối.
- Callback `apply` để có điểm mở rộng áp dụng policy sau khi kích hoạt.

**Tại sao cần thay đổi:** Policy Manager cần một nơi duy nhất quyết định policy
nào được tin tưởng và được phép hoạt động. Nếu rải logic này giữa heartbeat,
UI và bộ đếm thời gian thì dễ bỏ sót bước xác minh hoặc vô tình ghi đè policy
tốt bằng policy lỗi.

#### `agent/openguard_agent.py` — file đã sửa

Đã thêm cho phần Policy Manager:

- Nâng `AGENT_VERSION` lên `0.2.0`.
- Thêm cấu hình `database_path` và `policy_hmac_secret`.
- Đọc `OGK_DATABASE_PATH` và `OGK_POLICY_HMAC_SECRET` từ môi trường.
- Khởi tạo `PolicyRepository` và `PolicyManager` trong `AgentClient`.
- Sau heartbeat, nếu server báo có bản mới thì gọi
  `GET /api/v1/agent/policy`.
- Policy hợp lệ được lưu và cập nhật `AgentState.policy_version`.
- Policy bị từ chối không làm mất policy cũ.

**Tại sao cần thay đổi:** đây là điểm Agent đã giao tiếp với server và xử lý
heartbeat. Việc nối Policy Manager tại đây giúp hoàn chỉnh flow server báo
version mới → Agent tải policy → kiểm tra → kích hoạt, mà không đưa networking
vào trong Policy Manager.

#### `agent/tests/test_policy_manager.py` — file mới

Đã thêm test cho policy hợp lệ, signature giả mạo, schema sai, last-known-good
và security event.

**Tại sao cần thay đổi:** các nhánh từ chối policy là nhánh bảo mật quan trọng.
Test bảo đảm một thay đổi sau này không vô tình bỏ kiểm tra HMAC hoặc làm mất
policy tốt đang hoạt động.

### Luồng đồng bộ policy

```text
Heartbeat
   ↓
Server báo policy_update_available = true?
   ↓ có
GET /api/v1/agent/policy
   ↓
Parse và validate schema
   ↓
Verify HMAC-SHA256
   ↓
Kiểm tra version/downgrade/collision
   ↓
Lưu SQLite và đánh dấu active
   ↓
Cập nhật local policy_version
```

Việc đồng bộ được nối vào `AgentClient.heartbeat()` trong
`agent/openguard_agent.py`.

### Xác minh HMAC

Agent và server phải dùng cùng secret. Chuỗi được ký có dạng:

```text
<version>.<canonical-policy-json>
```

Canonical JSON được tạo bằng cách sắp xếp key, bỏ khoảng trắng không cần thiết
và giữ Unicode. Chữ ký được tính bằng HMAC-SHA256 và so sánh bằng
`hmac.compare_digest()` để tránh so sánh chuỗi không an toàn.

Biến môi trường cần cấu hình:

```powershell
$env:OGK_POLICY_HMAC_SECRET="<giống POLICY_HMAC_SECRET của server>"
```

### Schema được kiểm tra

Policy bắt buộc có:

- `id`: chuỗi không rỗng.
- `version`: số nguyên dương.
- `signature`: SHA-256 hex gồm 64 ký tự.
- `payload`: object chứa cấu hình policy.
- `weekly_schedule`: đúng 336 giá trị boolean, tương ứng 7 ngày × 48 khung
  nửa giờ.
- `apps` và `domains`: danh sách.
- `screen_time`: quota ngày thường/cuối tuần, idle timeout, grace period và các
  mốc cảnh báo với giới hạn hợp lệ.

Policy có version thấp hơn policy đang chạy bị xem là downgrade. Policy cùng
version nhưng khác signature bị xem là version collision. Cả hai đều bị từ
chối.

### Ý nghĩa các chỉ số screen time

#### Quota

`weekday_minutes` và `weekend_minutes` là tổng thời gian trẻ được phép sử dụng
máy trong một ngày:

- `weekday_minutes`: quota từ thứ Hai đến thứ Sáu.
- `weekend_minutes`: quota cho thứ Bảy và Chủ Nhật.

Ví dụ `weekday_minutes = 180` nghĩa là quota ngày thường là 180 phút, tương
đương ba giờ. Counter chỉ trừ quota khi người dùng active, session mở khóa và
đang trong lịch được phép. Quota thực tế trong ngày được tính như sau:

```text
quota khả dụng = quota policy + bonus_seconds - used_seconds
```

Khi quota khả dụng về 0, Agent yêu cầu khóa workstation. Phần quota này **đã
được thực thi** trong `ScreenTimeCounter`.

#### Idle timeout

`idle_timeout_sec` là số giây không có thao tác chuột hoặc bàn phím để xem người
dùng là idle.

Ví dụ `idle_timeout_sec = 300` nghĩa là sau năm phút không có input, Agent
không tiếp tục cộng screen time. Khi có input trở lại, việc đếm tiếp tục ở các
tick sau. Chỉ số này **đã được thực thi** qua Windows `GetLastInputInfo()`.

#### Grace period

`grace_period_sec` là khoảng thời gian gia hạn ngắn trước khi thực hiện khóa,
thường dùng để trẻ lưu bài hoặc đóng ứng dụng sau khi quota hết hoặc lịch sử
dụng kết thúc.

Ví dụ `grace_period_sec = 60` có nghĩa là cho thêm 60 giây trước khi khóa máy.
Chỉ số này **đã được thực thi** bằng monotonic deadline. Phiên bản hiện tại bắt
đầu grace khi quota về 0 và khóa khi grace kết thúc; ngoài weekly schedule vẫn
khóa ngay để đáp ứng SLA năm giây.

#### Warning

`warning_minutes` là danh sách các mốc thời gian còn lại mà Agent nên cảnh báo
người dùng trước khi hết quota.

Ví dụ:

```json
"warning_minutes": [10, 5, 1]
```

nghĩa là hiển thị cảnh báo khi quota còn 10 phút, 5 phút và 1 phút. Các giá trị
được loại bỏ trùng lặp, sắp xếp giảm dần và phải nằm trong khoảng 1–60 phút.
Chỉ số này **đã được thực thi**: counter phát `TIME_WARNING`, lưu trạng thái
chống lặp trong SQLite và desktop GUI hiển thị banner cảnh báo.

Tóm tắt trạng thái hiện tại:

| Chỉ số | Đơn vị | Ý nghĩa | Trạng thái |
|---|---:|---|---|
| `weekday_minutes` | phút/ngày | Quota từ thứ Hai đến thứ Sáu | Đã thực thi |
| `weekend_minutes` | phút/ngày | Quota thứ Bảy và Chủ Nhật | Đã thực thi |
| `idle_timeout_sec` | giây | Ngưỡng không thao tác để ngừng tính usage | Đã thực thi |
| `grace_period_sec` | giây | Thời gian gia hạn trước khi khóa | Đã thực thi |
| `warning_minutes` | phút còn lại | Các mốc hiển thị cảnh báo | Đã thực thi |

### Last-known-good policy

SQLite lưu các policy trong bảng:

```text
policies
--------
version
policy_id
payload_json
signature
activated_at
is_active
```

Mỗi thời điểm chỉ có một policy được đánh dấu `is_active = 1`. Policy mới chỉ
được kích hoạt sau khi vượt qua validate, HMAC và kiểm tra version. Vì vậy
policy sai không ghi đè policy tốt đang sử dụng.

### Security event

Khi policy bị từ chối, Agent:

1. Không kích hoạt policy mới.
2. Tiếp tục dùng last-known-good policy.
3. Ghi log bằng logger `openguard-agent.security`.
4. Lưu sự kiện `POLICY_REJECTED` vào bảng `security_events`.

```text
security_events
---------------
id
event_type
details
created_at
```

Thông tin này phục vụ debug và audit, ví dụ phát hiện policy bị sửa, sai HMAC
secret, sai schema hoặc bị downgrade. Hiện security event chỉ được giữ local,
chưa có chức năng đồng bộ lên server.

## 2. Screen-Time Counter

### Mục tiêu

Screen-Time Counter chỉ cộng thời gian sử dụng thật khi:

- Có policy đang hoạt động.
- Session đang mở khóa.
- Thời điểm hiện tại nằm trong lịch được phép.
- Quota vẫn còn.
- Người dùng đang active, chưa vượt quá idle timeout.

### Các module đã tạo

```text
agent/service/screen_time/
├── __init__.py
├── counter.py
└── platform.py
```

- `counter.py`: tính thời gian, kiểm tra quota/lịch và lưu usage vào SQLite.
- `platform.py`: lớp biên hệ điều hành dùng Windows API để phát hiện idle,
  kiểm tra session và khóa workstation.

### Các file đã thêm/sửa và lý do

#### `agent/service/screen_time/__init__.py` — file mới

Đã export `ScreenTimeCounter`, `TickResult`, `UsageRepository` và các hàm tích
hợp hệ điều hành.

**Tại sao cần thay đổi:** cung cấp một API import ổn định cho Screen-Time
service và che giấu cách tổ chức module bên trong.

#### `agent/service/screen_time/counter.py` — file mới

Đã thêm:

- `DailyUsage` biểu diễn usage của một ngày.
- `TickResult` trả về kết quả của mỗi lần tick.
- `UsageRepository` tạo và thao tác bảng SQLite `usage_daily`.
- `get()`, `get_if_exists()`, `add_usage()` và `set_bonus()`.
- `ScreenTimeCounter` dùng `time.monotonic()` để tính delta.
- Kiểm tra active policy, trạng thái session, weekly schedule, quota và idle.
- Cộng usage không vượt quá phần quota còn lại.
- Yêu cầu khóa khi hết quota hoặc ngoài lịch.
- Tránh gửi yêu cầu khóa liên tục khi một lần khóa vẫn đang chờ xử lý.

**Tại sao cần thay đổi:** screen time là state nghiệp vụ độc lập, phải tồn tại
sau khi Agent restart và không nên phụ thuộc UI. Việc tách repository và
counter cũng cho phép test clock, activity probe và workstation lock bằng các
hàm giả thay vì phải chờ thời gian thật hoặc khóa máy thật.

#### `agent/service/screen_time/platform.py` — file mới

Đã thêm:

- `idle_seconds()` dùng Windows `GetLastInputInfo()`.
- `is_user_active()` so sánh idle time với `idle_timeout_sec` của policy.
- `is_session_unlocked()` dùng `OpenInputDesktop()`.
- `lock_workstation()` dùng Windows `LockWorkStation()`.
- Fallback an toàn để code có thể chạy/test trên hệ điều hành không phải
  Windows.

**Tại sao cần thay đổi:** phần tính quota không nên gọi trực tiếp Windows API.
Tách lớp platform giúp nghiệp vụ không phụ thuộc chặt vào hệ điều hành, dễ test
và có thể bổ sung implementation cho nền tảng khác sau này.

#### `agent/openguard_agent.py` — file đã sửa

Đã thêm cho phần Screen-Time Counter:

- Cấu hình `usage_tick_sec`, đọc từ `OGK_USAGE_TICK_SEC`.
- Khởi tạo `UsageRepository` dùng chung SQLite database với policy cache.
- Thêm `screen_time_counter()` để ghép repository, policy provider và Windows
  platform probes.
- Sửa `run_forever()` để screen-time tick độc lập mỗi giây trong khi heartbeat
  vẫn chạy theo chu kỳ riêng.
- Đọc usage của ngày hiện tại và gửi lên server qua `quota_used_sec`.
- Ghi log khi Agent yêu cầu khóa workstation hoặc khi tick gặp lỗi lưu trữ.

**Tại sao cần thay đổi:** vòng lặp heartbeat 60 giây là quá thưa để đạt độ
chính xác screen-time mong muốn. Agent cần tick nhanh nhưng vẫn không được gửi
heartbeat mỗi giây, nên hai lịch chạy được tách ra trong cùng service loop.

#### `agent/tests/test_screen_time.py` — file mới

Đã thêm test cho quota ba phút, thời gian idle, session bị khóa và thời gian
ngoài weekly schedule.

**Tại sao cần thay đổi:** test sử dụng monotonic clock giả để mô phỏng chính
xác 180 giây mà không phải chờ ba phút thật, đồng thời bảo đảm chỉ active usage
mới được cộng.

#### `agent/README.md` — file đã sửa

Đã thêm hướng dẫn ngắn về biến môi trường HMAC, policy cache, security event,
screen-time counter và bảng `usage_daily`.

**Tại sao cần thay đổi:** người chạy Agent cần biết secret là bắt buộc đối với
chế độ service và cần hiểu dữ liệu local được lưu ở đâu.

### Luồng xử lý mỗi tick

```text
tick
  ↓
có active policy?
  ↓
session unlocked?
  ↓
inside weekly schedule?
  ↓
quota available?
  ↓
user active?
  ↓
cộng monotonic delta
  ↓
hết quota? → LockWorkStation()
```

Khi chạy `python agent/openguard_agent.py run`, Agent tick mặc định mỗi một
giây và heartbeat theo chu kỳ cấu hình riêng.

### Tính thời gian bằng monotonic clock

Counter dùng `time.monotonic()` thay vì đồng hồ hệ thống:

```python
delta = current_monotonic - previous_monotonic
```

Do đó việc người dùng hoặc hệ thống chỉnh ngày/giờ không làm delta bị âm hoặc
nhảy sai. Delta chỉ được ghi khi các điều kiện active, unlocked, schedule và
quota đều hợp lệ. Khi gần hết quota, số giây được cộng bị giới hạn đúng bằng
phần quota còn lại, tránh vượt quota do một tick dài.

Chu kỳ tick được cấu hình bằng:

```text
OGK_USAGE_TICK_SEC
```

Giá trị mặc định là `1` giây và chỉ chấp nhận từ `0.1` đến `30` giây.

### Dữ liệu usage trong SQLite

Thời gian sử dụng được lưu theo từng ngày:

```text
usage_daily
-----------
date
used_seconds
bonus_seconds
updated_at
```

- `used_seconds`: tổng số giây active đã sử dụng trong ngày.
- `bonus_seconds`: thời gian được cộng thêm.
- `updated_at`: lần cập nhật gần nhất.

SQLite chạy ở chế độ WAL. Việc cộng usage được bảo vệ bằng mutex trong process
và dùng UPSERT để cập nhật nguyên tử.

Khi heartbeat, `used_seconds` của ngày hiện tại được gửi lên server qua trường
`quota_used_sec`.

### Quota và weekly schedule

- Thứ Hai đến thứ Sáu dùng `weekday_minutes`.
- Thứ Bảy và Chủ Nhật dùng `weekend_minutes`.
- Quota thực tế bằng quota policy cộng `bonus_seconds`.
- Weekly schedule gồm 336 slot; mỗi slot đại diện 30 phút.
- Ngoài lịch cho phép, Agent không cộng usage và yêu cầu khóa workstation.
- Khi quota về 0, Agent yêu cầu khóa workstation.

### Tích hợp Windows

`platform.py` sử dụng:

- `GetLastInputInfo()` để tính số giây idle.
- `OpenInputDesktop()` để xác định session có đang ở secure desktop/lock screen.
- `LockWorkStation()` để khóa máy.

Trên hệ điều hành không phải Windows, các hàm được thiết kế để code vẫn chạy
và test được, nhưng thao tác khóa workstation trả về `False`.

## Các chức năng Week 02 đã triển khai tiếp theo

Các mục 3–9 dưới đây đã được nối vào Agent service và desktop GUI. Mỗi mục ghi
rõ file đã thêm/sửa, trách nhiệm và acceptance test tương ứng.

## 3. Idle Detection

### Mục tiêu

Ngừng cộng screen time khi không có keyboard/mouse input từ 300 giây trở lên và
tự động đếm tiếp khi người dùng hoạt động trở lại.

```text
idle_seconds < idle_timeout_sec  → cộng monotonic delta
idle_seconds >= idle_timeout_sec → không cộng
input trở lại                    → tiếp tục cộng từ tick hiện tại
```

Wall clock chỉ dùng để xác định ngày và schedule. `time.monotonic()` chỉ dùng
để tính elapsed active time; tuyệt đối không lấy hiệu hai wall-clock timestamp
để cộng usage.

### File đã sửa

#### `agent/service/screen_time/platform.py`

- Giữ wrapper `GetLastInputInfo()` hiện có.
- Bổ sung kiểu kết quả/probe rõ ràng nếu cần để phân biệt active, idle và lỗi
  Windows API.
- Không coi lỗi gọi API là active một cách im lặng; ghi diagnostic phù hợp.

**Tại sao:** mọi chi tiết Windows API phải nằm ở platform boundary, không đưa
`ctypes` vào counter.

#### `agent/service/screen_time/counter.py`

- Giữ wall clock và monotonic clock dưới hai dependency riêng.
- Làm rõ state chuyển `active → idle → active`.
- Khi idle, vẫn cập nhật mốc monotonic của tick nhưng không ghi delta vào
  `usage_daily`; nhờ đó thời gian idle không bị cộng bù khi resume.

**Tại sao:** nếu không cập nhật mốc monotonic trong lúc idle, toàn bộ khoảng
idle có thể bị cộng nhầm khi người dùng hoạt động trở lại.

#### `agent/tests/test_idle_detection.py` — file mới

- Test idle ở 299 giây vẫn tính.
- Test idle từ 300 giây không tính.
- Test input trở lại thì chỉ tính delta mới, không cộng thời gian idle trước đó.
- Test thay đổi wall clock không làm sai elapsed usage.

### Acceptance criteria

- `idle >= 300s` dừng cộng usage ở tick kế tiếp.
- Resume không cộng bù khoảng idle.
- Sai số usage không quá ±30 giây/giờ trong điều kiện tick bình thường.

## 4. Weekly Schedule Enforcement

### Mục tiêu

Dùng một mảng phẳng 336 boolean, tương ứng 7 ngày × 48 slot nửa giờ. Công thức
chọn slot:

```text
slot = weekday * 48 + hour * 2 + (1 nếu minute >= 30, ngược lại là 0)
```

Python `datetime.weekday()` trả thứ Hai là `0` và Chủ Nhật là `6`, phù hợp với
công thức này.

### File đã sửa/thêm

#### `agent/service/policy/models.py`

- Giữ validation bắt buộc đúng 336 boolean.
- Thêm helper có tên rõ nghĩa như `schedule_slot_at()` để có thể test trực tiếp
  phép ánh xạ thời gian → slot.
- Tiếp tục dùng `is_allowed_at()` làm API nghiệp vụ.

**Tại sao:** gom công thức slot vào model tránh việc counter, UI và test tự tính
theo nhiều cách khác nhau.

#### `agent/service/enforcement/workstation.py` — file mới

- Nhận lý do enforcement, ví dụ `SCHEDULE_DISALLOWED`.
- Yêu cầu khóa workstation qua wrapper Windows duy nhất.
- Ghi thời điểm phát hiện và thời điểm gọi lock để đo SLA 5 giây.

**Tại sao:** schedule chỉ quyết định có được sử dụng hay không; thao tác khóa
thuộc enforcement service dùng chung với quota và remote command.

#### `agent/service/screen_time/counter.py`

- Khi slot là `False`, không cộng usage.
- Gửi enforcement request ngay, không chờ heartbeat.
- Duy trì trạng thái để không spam `LockWorkStation()` mỗi tick.

#### `agent/tests/test_weekly_schedule.py` — file mới

- Test ranh giới 00 và 30 phút.
- Test chuyển ngày, đặc biệt Chủ Nhật → thứ Hai.
- Test toàn bộ 336 index nằm đúng khoảng `0..335`.
- Test từ lúc phát hiện slot `False` đến lock không vượt năm giây.

### Acceptance criteria

- Slot `False` không được cộng usage.
- Máy được yêu cầu khóa trong vòng năm giây, độc lập với heartbeat 60 giây.

## 5. Warning và Grace Period

### Mục tiêu

Hiển thị cảnh báo một lần tại các mốc còn 10, 5 và 1 phút. Khi quota về 0,
hiển thị:

```text
Thời gian sử dụng hôm nay đã hết.
Em có 60 giây để lưu bài.
```

Sau `grace_period_sec`, Agent khóa workstation.

### File đã thêm/sửa

#### `agent/service/screen_time/counter.py` — đã bổ sung warning state machine

- Tính các threshold được vượt qua giữa hai tick.
- Phát event `TIME_WARNING`, `GRACE_STARTED` và `GRACE_TICK`.
- Mỗi warning chỉ phát một lần cho mỗi ngày/policy session.

**Tại sao:** warning là state machine riêng, không nên nhét logic UI vào
`ScreenTimeCounter`.

- Trả thêm event khi remaining time đi qua warning threshold.
- Khi quota về 0, bắt đầu grace period thay vì khóa ngay.
- Dùng monotonic deadline cho 60 giây grace để chỉnh wall clock không thể kéo
  dài hoặc rút ngắn grace period.
- Hết grace thì gửi enforcement request.

#### SQLite `warning_state` — bảng mới

```text
warning_state
-------------
date
policy_version
warning_minute
sent_at
```

**Tại sao:** nếu Agent restart trong ngày, các cảnh báo 10/5/1 phút không được
hiển thị lặp lại.

#### `agent/agent_gui.py`

- Nhận event từ service qua queue hiện có.
- Hiển thị nội dung warning và countdown grace period trên tray/status UI.
- UI chỉ render event, không tự tính quota.

#### `agent/tests/test_warning_grace.py` — file mới

- Test tick nhảy qua nhiều threshold vẫn phát đủ warning cần thiết một lần.
- Test restart không phát lại warning đã lưu.
- Test quota bằng 0 bắt đầu grace.
- Test lock đúng sau monotonic 60 giây.

### Acceptance criteria

- Mỗi mốc warning chỉ hiển thị một lần trong ngày/session.
- Grace period không bị ảnh hưởng bởi thay đổi wall clock.
- Không khóa trước grace; khóa ngay khi grace kết thúc.

## 6. Windows Lock

### Mục tiêu

Có một wrapper enforcement duy nhất gọi Windows `LockWorkStation()` khi:

- Quota exhausted và grace đã kết thúc.
- Weekly schedule không cho phép.
- Nhận command `LOCK_NOW`.

Không kill process, shutdown hoặc restart máy.

### File đã thêm/sửa

#### `agent/service/enforcement/__init__.py` — file mới

Export API enforcement dùng chung cho screen time và command handler.

#### `agent/service/enforcement/workstation.py` — file mới

- Chuyển logic `LockWorkStation()` từ `screen_time/platform.py` sang đây.
- Định nghĩa các reason: `QUOTA_EXHAUSTED`, `SCHEDULE_DISALLOWED`,
  `REMOTE_LOCK`.
- Trả kết quả thành công/thất bại để command ACK đúng trạng thái.
- Chống gọi lock lặp liên tục nhưng cho phép khóa lại sau khi session được mở.

**Tại sao:** khóa máy là hành động enforcement dùng bởi nhiều nguồn trigger,
không chỉ Screen-Time Counter.

#### `agent/service/screen_time/platform.py`

- Chỉ giữ activity/session detection.
- Bỏ trách nhiệm enforcement sau khi migration hoàn tất.

#### `agent/tests/test_workstation_enforcement.py` — file mới

- Mock Windows API để test ba trigger.
- Test API thất bại trả trạng thái lỗi thay vì báo completed.
- Test không có code path shutdown/kill process.

### Acceptance criteria

- Cả ba trigger đi qua cùng một wrapper.
- `LockWorkStation()` được gọi tối đa trong SLA yêu cầu.
- Kết quả lock có thể dùng để tạo ACK `completed` hoặc `failed`.

## 7. Clock Tampering Detection

### Mục tiêu

Dùng ba nguồn thời gian đúng vai trò:

| Nguồn | Mục đích |
|---|---|
| `time.monotonic()` | Tính elapsed active usage và grace deadline |
| Local wall clock | Chọn ngày, weekday và schedule slot |
| `server_time` | Đối chiếu độ lệch của local wall clock |

Sau heartbeat:

```text
drift = abs(local_utc_time - server_time)
drift > 120 giây → ghi CLOCK_DRIFT_DETECTED
```

Khi phát hiện drift, Agent không reset ngày usage, không tăng quota và không
chuyển sang schedule/quota của ngày khác chỉ vì local clock vừa bị chỉnh.

### File đã thêm/sửa

#### `agent/service/clock/monitor.py` — file mới

- Parse `server_time` bắt buộc timezone-aware.
- Tính signed drift và absolute drift.
- Quản lý trạng thái `trusted`, `drifted`, `recovered`.
- Cung cấp trusted date/schedule time dựa trên lần đồng bộ server gần nhất cộng
  monotonic elapsed.

**Tại sao:** chỉ ghi log drift chưa đủ; counter cần một nguồn thời gian đáng
tin để tránh reset quota khi wall clock bị tua sang ngày khác.

#### `agent/openguard_agent.py`

- Chuyển `server_time` từ heartbeat vào Clock Monitor.
- Không trực tiếp quyết định reset quota trong networking layer.

#### `agent/service/screen_time/counter.py`

- Lấy schedule date/time từ Clock Monitor thay vì dùng local wall clock trực
  tiếp khi clock đang drift.
- Usage delta vẫn luôn đến từ monotonic clock.

#### SQLite `clock_events` — bảng mới

Lưu local time, server time, signed drift, threshold và thời điểm phát hiện để
audit.

#### `agent/tests/test_clock_tampering.py` — file mới

- Test drift 119 giây không cảnh báo, 121 giây có cảnh báo.
- Test tua local clock về trước/sau không tăng hoặc reset quota.
- Test server time cộng monotonic elapsed vẫn chọn đúng schedule slot.

### Acceptance criteria

- Drift trên 120 giây được ghi nhận.
- Chỉnh local clock không cấp thêm quota.
- Usage monotonic không bị âm, reset hoặc tăng đột biến.

## 8. Extra-Time Request

### Mục tiêu

Tray UI có nút `Xin thêm 15 phút`. Agent gửi:

```http
POST /api/v1/agent/requests
Authorization: Bearer <device token>
Content-Type: application/json

{
  "type": "extra_time",
  "requested_minutes": 15
}
```

API server hiện đã tồn tại và chấp nhận từ 5 đến 120 phút. Khi phụ huynh duyệt,
server phát command `ADD_TIME`; Agent cộng số phút được duyệt vào
`bonus_seconds` của ngày hiện tại.

### File đã thêm/sửa

#### `agent/service/requests/client.py` — file mới

- Gửi extra-time request bằng device access token.
- Validate `requested_minutes` trước khi gửi.
- Xử lý refresh token theo cùng cơ chế của `AgentClient`.
- Trả request id/status cho UI.

#### `agent/agent_gui.py`

- Thêm nút `Xin thêm 15 phút`.
- Disable nút trong lúc request đang gửi.
- Hiển thị trạng thái chờ duyệt, đã gửi hoặc lỗi.

#### `agent/service/commands/handler.py` — file mới

- Xử lý `ADD_TIME`.
- Validate minutes trong payload.
- Gọi `UsageRepository.set_bonus()` theo ngày tin cậy.
- Thiết kế idempotent để command được gửi lại không cộng bonus hai lần.

#### SQLite `processed_commands` — bảng mới

Lưu `command_id`, type, status, processed_at và error để chống xử lý trùng sau
reconnect/restart.

#### `agent/tests/test_extra_time.py` — file mới

- Test POST đúng payload và authorization.
- Test `ADD_TIME 15` cộng chính xác 900 giây.
- Test cùng `command_id` gửi hai lần chỉ cộng một lần.

### Acceptance criteria

- Request 15 phút được server tiếp nhận.
- `ADD_TIME 15` tăng bonus đúng 900 giây.
- Command duplicate không làm tăng bonus lần hai.

## 9. WebSocket Client

### Mục tiêu

Duy trì kết nối WebSocket đến `/api/v1/agent/ws` với device bearer token để
nhận command thời gian thực:

- `LOCK_NOW`
- `UNLOCK`
- `ADD_TIME`

Server hiện gửi command có dạng:

```json
{
  "command_id": "...",
  "type": "LOCK_NOW",
  "payload": {}
}
```

Agent ACK theo protocol server hiện tại:

```json
{
  "type": "ack",
  "command_id": "...",
  "status": "completed",
  "error": null
}
```

### File đã thêm/sửa

#### `agent/service/commands/handler.py` — file mới

- Validate `command_id`, command type và payload qua command handler.
- Định nghĩa `CommandResult` với kết quả `completed`/`failed` dùng để tạo ACK.
- Route `LOCK_NOW` đến Workstation Enforcer.
- Route `ADD_TIME` đến Usage Repository.
- Xử lý `UNLOCK` như bỏ trạng thái khóa do policy/remote command; lưu ý Windows
  không cung cấp API an toàn để tự mở khóa một session đang ở lock screen.
- Bảo đảm xử lý idempotent bằng `processed_commands`.

#### `agent/service/realtime/websocket_client.py` — file mới

- Kết nối `ws://` hoặc `wss://` tương ứng server URL.
- Gửi bearer token trong handshake.
- Reconnect với exponential backoff và jitter.
- Khi token hết hạn, yêu cầu refresh rồi kết nối lại.
- Nhận command, gọi handler và gửi ACK sau khi xử lý xong.
- Không ACK `completed` trước khi side effect thành công.

#### `agent/openguard_agent.py`

- Khởi động/dừng WebSocket worker cùng vòng đời service.
- Vẫn xử lý `commands` trả về từ heartbeat làm fallback khi WebSocket offline.
- Dùng chung Command Handler cho cả WebSocket và heartbeat để tránh hai logic
  khác nhau.

#### `agent/tests/test_websocket_client.py` — file mới

- Test ba loại command và ACK tương ứng.
- Test command lỗi gửi ACK `failed` kèm error ngắn.
- Test reconnect, token refresh và queued command sau reconnect.
- Test WebSocket và heartbeat cùng nhận một command nhưng chỉ thực thi một lần.

### Acceptance criteria

- Command online được xử lý gần thời gian thực.
- Mỗi command được thực thi tối đa một lần theo `command_id`.
- ACK phản ánh đúng kết quả side effect.
- Mất WebSocket không làm mất command vì heartbeat/queued commands là fallback.

### Thứ tự đã triển khai

```text
3. Hoàn thiện Idle Detection
        ↓
4. Weekly Schedule + 6. Workstation Enforcer
        ↓
5. Warning + Grace Period
        ↓
7. Clock Tampering Detection
        ↓
9. Command Handler + WebSocket nền tảng
        ↓
8. Extra-Time Request + ADD_TIME
```

Workstation Enforcer được làm cùng Weekly Schedule vì đây là dependency trực
tiếp để đạt yêu cầu khóa trong năm giây. Command Handler được tách khỏi
WebSocket để transport chỉ chịu trách nhiệm truyền nhận, không chứa nghiệp vụ.

## 10. Cấu hình và chạy Agent

Server và Agent cùng đọc file `.env` ở thư mục gốc dự án. File thật đã được
thêm vào `.gitignore`; `.env.example` là template có thể commit. Hai giá trị
`POLICY_HMAC_SECRET` và `OGK_POLICY_HMAC_SECRET` trong `.env` phải giống nhau.

Với cấu hình local mặc định, không cần chạy `export` hoặc gán `$env:` thủ công.
Các biến môi trường hệ thống vẫn được ưu tiên hơn giá trị trong file nếu cần
override khi deploy.

Chạy Agent trên Windows PowerShell:

```powershell
python agent/openguard_agent.py run
```

Muốn đổi server, tick interval hoặc vị trí SQLite thì chỉnh `.env`, ví dụ:

```dotenv
OGK_SERVER_URL=http://192.168.1.10:8000
OGK_USAGE_TICK_SEC=1
OGK_DATABASE_PATH=C:\ProgramData\OpenGuardKids\agent.db
```

Nếu không cấu hình, `agent.db` được đặt cạnh file trạng thái Agent.

## 11. Kiểm thử đã bổ sung

Các test mới nằm tại:

```text
agent/tests/test_policy_manager.py
agent/tests/test_screen_time.py
agent/tests/test_clock_monitor.py
agent/tests/test_commands.py
agent/tests/test_extra_time.py
agent/tests/test_idle_detection.py
agent/tests/test_warning_grace.py
agent/tests/test_websocket_client.py
agent/tests/test_weekly_schedule.py
```

Các trường hợp chính đã được kiểm tra:

- Policy hợp lệ được lưu và kích hoạt.
- Policy sai HMAC bị từ chối.
- Policy sai schema bị từ chối.
- Last-known-good policy không bị thay thế khi policy mới sai.
- Security event được ghi vào SQLite.
- Quota ba phút khóa máy sau 180 giây active usage.
- Thời gian idle và session bị khóa không được tính.
- Ngoài weekly schedule thì không cộng usage và yêu cầu khóa.
- Clock drift vượt 120 giây được ghi nhận và trusted time đi theo monotonic.
- Warning không lặp lại sau khi tạo counter mới.
- Grace period khóa đúng theo monotonic deadline.
- `ADD_TIME` idempotent và cộng đúng bonus seconds.
- `LOCK_NOW`/`UNLOCK` đi qua command handler và Workstation Enforcer.
- WebSocket command tạo ACK đúng protocol.

## 12. Phần chưa triển khai trong phạm vi hiện tại

- Đồng bộ `security_events` từ Agent lên server.
- Enforcement cho danh sách `apps` và `domains`.
- Windows không cho ứng dụng tự mở khóa secure desktop; `UNLOCK` chỉ gỡ trạng
  thái enforcement nội bộ, người dùng vẫn phải xác thực vào Windows.
- Grace deadline đang giữ trong memory; nếu Agent restart đúng lúc grace đang
  chạy, phiên grace sẽ bắt đầu lại.

Các field trên đã được model/validate khi phù hợp, nhưng cần thêm service xử lý
riêng để hoàn thiện toàn bộ yêu cầu Week 02.
