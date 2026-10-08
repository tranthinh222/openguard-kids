# Week 03 — Server và Dashboard

Phạm vi: chỉ `server/`. Không triển khai process monitor, DNS proxy, Windows Service,
IPC hay giao diện Tray trong bản thay đổi này.

## Chạy và nâng database

Từ thư mục project, dùng môi trường Python đang có:

```powershell
cd server
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Migration mới: `e31008a1`, sau `c8d1f2a7b901`. Thêm `activity_events`,
`screen_usage_daily`, `policy_audits`; không sửa nội dung/chữ ký policy đã lưu.
Migration đã được kiểm thử nâng/hạ/nâng trên SQLite tạm. Không tự migrate database
đang sử dụng khi chạy test. Downgrade xóa các bảng Week 03 và dữ liệu trong đó.

`REPORT_TIMEZONE_OFFSET_MINUTES` mặc định 420 (UTC+7). Đây là timezone chung cho
ngày báo cáo và quota_date; hiện chưa hỗ trợ timezone/DST riêng cho từng trẻ.

## Policy ứng dụng và website

Giữ các endpoint đã có:

- `GET /api/v1/children/{child_id}/policy`
- `PUT /api/v1/children/{child_id}/policy`
- `GET /api/v1/agent/policy`

PUT gửi toàn bộ `payload`, bao gồm screen_time và weekly_schedule. Mỗi lần lưu tạo
version mới, HMAC mới và audit chứa giá trị cũ/mới, người thay đổi và giờ server.
Dashboard tại `/policies/{child_id}` cho thêm, sửa, xóa luật. App action Default
có nghĩa loại bỏ luật khỏi danh sách khi lưu.

```json
{
  "apps": [
    {"name": "game.exe", "sha256": null, "action": "block"}
  ],
  "domains": {
    "allow": ["school.edu.vn"],
    "block": ["example.com"],
    "blocked_categories": ["social", "games", "age_inappropriate"],
    "safe_search": true
  }
}
```

App name là basename `.exe`, không nhận executable path. Hash tùy chọn, 64 ký tự
hex, lưu lowercase. Không được trùng tên hoặc hash trong cùng policy. Agent tuần 3
cần ưu tiên hash trước, rồi fallback tên tiến trình. App group/daily budget là
phần tùy chọn trong plan, chưa được bổ sung.

Domain nhận hostname, không URL/path/port/wildcard/IP. Server chuẩn hóa lowercase,
IDNA và bỏ dấu chấm cuối. Không bỏ tùy tiện subdomain. Luật trùng sau chuẩn hóa
hoặc cùng domain xuất hiện cả allow và block bị từ chối.
Quy tắc match cho agent: explicit allow > explicit block > category > default allow;
match bằng domain chính xác hoặc suffix có ranh giới dấu chấm, không match chuỗi con.
Ví dụ cho phép `school.example.com` có thể ghi đè chặn `example.com`.

`domains: []` của client tuần 2 được chấp nhận khi PUT và chuẩn hóa sang object.
Policy đã lưu trước migration vẫn trả nguyên payload và chữ ký; không chuẩn hóa khi GET.
Policy mới mặc định bật SafeSearch và chặn social/games/age_inappropriate.

**Tương thích agent:** parser tuần 2 hiện chỉ nhận `domains` dạng list, nên sẽ từ chối
policy dạng object và giữ last-known-good. Người làm agent cần cập nhật parser và
enforcer theo contract này trước demo tích hợp. Không có thay đổi agent trong bản này.

## Cập nhật policy qua WebSocket

Sau khi PUT policy commit thành công, server gửi tới mọi device active/chưa thu hồi
của trẻ có WebSocket đang kết nối:

```json
{
  "type": "POLICY_UPDATED",
  "payload": {"id": "policy-uuid", "version": 2, "payload": {}, "signature": "hmac-sha256"}
}
```

`payload` ngoài cùng là nguyên PolicyResponse, giống GET /agent/policy, gồm đầy đủ
screen_time, weekly_schedule, apps và domains trong payload bên trong. Đây là
notification, không phải DeviceCommand: không có command_id, không gửi command ACK.
Agent tuần 3 cần phân nhánh POLICY_UPDATED trước command handler, kiểm tra HMAC,
version/downgrade và lưu last-known-good bằng cùng logic như khi fetch policy.
Chỉ cập nhật policy_version trong state/heartbeat sau khi nhận và áp dụng hợp lệ.

Server không coi gửi WebSocket thành công là đã áp dụng và không tự tăng
device.current_policy_version. Heartbeat vẫn so phiên bản; nếu push mất, socket đứt,
agent offline hoặc chưa áp dụng, agent fetch policy như cũ. Push giới hạn 2 giây
mỗi thiết bị, gửi song song; lỗi push không làm thất bại việc lưu policy. Không xếp
notification vào command queue vì policy version hiện tại đã là nguồn dữ liệu bền vững.
ConnectionManager hiện lưu socket trong bộ nhớ: chạy một Uvicorn worker để push
đúng mọi socket; triển khai nhiều worker cần shared pub/sub. Heartbeat vẫn hoạt động.

Agent tuần 2 hiện chưa xử lý notification này; phần server đã push được nhưng cần
phía agent bổ sung handler để việc áp dụng cũng diễn ra ngay. Không sửa agent trong task này.

## Command delivery và ACK khi mất kết nối

Command được lưu DB trước khi gửi. `sent_at` chỉ ghi lần đánh dấu gửi đầu tiên,
không chứng minh agent đã nhận/thực thi. Với heartbeat, nó có thể được ghi trước
khi HTTP response tới agent. `ack_at` ghi khi server nhận kết quả cuối từ agent.

- `pending` và `sent` đều được gửi lại qua heartbeat hoặc ngay khi WebSocket
  kết nối lại, tối đa 20 command/lần, giữ nguyên command_id và payload.
- Mất command sau sent_at: agent nhận lại cùng ID ở lần đồng bộ sau.
- Agent thực thi rồi mất ACK: agent nhận lại ID, tra processed_commands và gửi
  lại kết quả đã lưu. ACK đã tới server nhưng HTTP response mất cũng retry an toàn.
- Server dùng SQL compare-and-set: mark_sent chỉ chuyển pending → sent; không
  ghi đè completed/failed dù ORM object cũ. ACK đầu tiên chuyển pending/sent →
  completed/failed; ACK lặp hoặc mâu thuẫn không thay kết quả/ack_at đầu tiên.
- Khi ACK tới rất nhanh trước mark_sent, trạng thái cuối và ack_at được giữ;
  sent_at có thể null trong trường hợp này và không có nghĩa chưa thực thi.
- ACK HTTP và WebSocket đều chỉ nhận completed/failed, error tối đa 255 ký tự.
  ACK phải thuộc device đang xác thực. ACK WebSocket sai schema đóng socket 1008.
- Lỗi/timeout push (2 giây) không làm mất command đã lưu hoặc khiến API tạo lệnh
  báo thất bại; heartbeat vẫn phục hồi. failed là kết quả thực thi cuối, không phải
  lỗi transport và không tự retry lệnh failed; muốn thử lại cần tạo command mới.

Đây là giao lệnh ít nhất một lần (at-least-once), không phải exactly-once toàn hệ
thống. Agent hiện có cache kết quả theo ID, nhưng kiểm tra ID, thực thi và ghi kết
quả chưa là một thao tác nguyên tử. Crash giữa thực thi/lưu kết quả hoặc hai worker
đồng thời có thể thực thi trùng; phía agent cần serialize command processing và
transaction cho các hiệu ứng SQLite như ADD_TIME để khép giới hạn này. Task này
chỉ sửa server. Khi offline lâu, các lệnh chưa ACK vẫn còn hiệu lực và có thể được
gửi lại; expiry/supersession là chính sách riêng, chưa được thêm.

## Domain categories

- Phụ huynh: `GET /api/v1/domain-categories`
- Thiết bị: `GET /api/v1/agent/domain-categories`

Trả dataset version, 6 category, mapping domain, unknown fallback và thứ tự ưu tiên.
Dataset khởi đầu có 11 mục minh họa, gồm domain `.test` trung tính cho nhóm
age_inappropriate. Đây chưa phải bộ phân loại 200 mục của toàn bộ rubric.
Dataset hiện là dữ liệu versioned trong code, chưa có màn hình sửa taxonomy.
Endpoint chỉ cung cấp luật/dữ liệu; DNS rewrite và SafeSearch được thực thi phía agent.

## Event batch và ACK

`POST /api/v1/agent/events/batch` dùng Bearer device token; tối đa 500 event/batch.

```json
{
  "events": [
    {
      "event_id": "f1a38e97-5423-4fa6-94ce-a01314cbeb56",
      "ts": "2026-10-08T10:00:00+07:00",
      "type": "app_stop",
      "subject": "game.exe",
      "duration_sec": 120,
      "policy_id": null
    }
  ]
}
```

Chín type: app_start, app_stop, domain_query, blocked_app, blocked_domain,
quota_warning, locked, unlock_request, override_granted.

- UUID event_id do agent tạo, giữ nguyên khi retry.
- `ts` bắt buộc có timezone.
- Chỉ app_stop chứa duration khác 0, integer 0–86400. Phiên dài hơn phải chia thành
  các đoạn có ID riêng. App_start không được tính thêm thời lượng.
- App events chỉ chứa executable basename; domain events chỉ chứa hostname.
- Các event còn lại để subject null, không gửi thông điệp tự do.
- Trường ngoài schema bị từ chối, gồm URL, title, screenshot, content.
- Server suy ra child_id/device_id từ token. Nếu client gửi hai trường tùy chọn
  này thì chúng phải khớp. policy_id, nếu có, phải thuộc đúng trẻ.

```json
{
  "accepted": ["f1a38e97-5423-4fa6-94ce-a01314cbeb56"],
  "duplicates": [],
  "rejected": [{"index": 1, "event_id": null, "reason": "invalid_event"}]
}
```

Accepted gồm cả duplicate hợp lệ để agent có thể xóa khỏi queue sau ACK. Cùng ID
nhưng khác nội dung hoặc khác thiết bị: event_id_conflict. Schema lỗi được báo theo
index, không phản chiếu nội dung nhạy cảm. Một event lỗi không hủy các event hợp lệ
khác. Sai cấu trúc envelope hoặc quá 500 item trả 422 toàn request.

Chỉ retry lỗi mạng/server. Event invalid_event, identity_mismatch, invalid_policy,
event_id_conflict, outside_retention cần đưa vào trạng thái lỗi cục bộ, tránh retry vô hạn.

## Clock và event offline

Lưu ba thời điểm: occurred_at (agent khai báo), received_at (server), effective_at
(dùng lọc/báo cáo), tất cả UTC. Giữ nguyên ngày lịch sử khi batch offline được gửi
lại và timestamp nằm trong 90 ngày, không bị đánh dấu clock sai.

Nếu timestamp vượt giờ server quá ngưỡng drift, hoặc heartbeat mới trong 120 giây
cho biết clock sai, `clock_trusted=false` và effective_at dùng received_at. Có clock
sai đã biết thì cả timestamp quá khứ rất xa cũng được nhận và quy về received_at.
Nếu không có bằng chứng clock sai, timestamp cũ hơn 90 ngày bị từ chối.
Timestamp tương lai trong khoảng dung sai được chặn trên ở received_at.

`clock_trusted` là kết quả kiểm tra tính hợp lý phía server, không phải chứng thực
thời điểm thực tế: contract hiện chưa có monotonic anchor/sequence để xác minh
chính xác lịch sử offline. Không sửa ngược timestamp server theo giờ agent.

## Screen time và báo cáo

Heartbeat hỗ trợ trường tùy chọn **quota_date** (`YYYY-MM-DD`) đi cùng
quota_used_sec (0–86400). Agent tuần 3 phải lấy ngày này từ trusted clock theo
timezone báo cáo. Ngày trong 90 ngày gần đây mới được ghi nhận.

```json
{
  "policy_version": 2,
  "agent_version": "0.4.0",
  "agent_wall_clock": "2026-10-08T10:00:00+07:00",
  "quota_date": "2026-10-08",
  "quota_used_sec": 7200
}
```

Server lưu giá trị lớn nhất mỗi device/ngày để heartbeat lặp không cộng trùng.
Heartbeat cũ thiếu quota_date vẫn được xử lý nhưng không tạo dữ liệu screen time
lịch sử. Nếu chưa có dữ liệu này, UI ghi rõ “Chưa có dữ liệu”. Không thay bằng tổng
thời lượng app: app có thể chạy đồng thời. Các thiết bị dùng đồng thời được cộng
riêng, chưa khử trùng thời gian sử dụng giữa thiết bị.

- `GET /api/v1/children/{id}/reports/summary`
- `GET /api/v1/children/{id}/reports/apps`
- `GET /api/v1/children/{id}/reports/domains`
- `GET /api/v1/children/{id}/reports/blocks`
- `GET /api/v1/children/{id}/reports/export.csv`

Các endpoint hỗ trợ start/end ngày (inclusive), 1–90 ngày, mặc định 7 ngày tới hôm nay.
Parent token/session và kiểm tra ownership bắt buộc. Summary chứa daily series,
screen_time_sec, app_duration_sec, top_apps/top_domains, blocked_count và số event
không tin cậy. Apps lấy tổng app_stop.duration_sec; domains đếm domain_query;
blocks đếm blocked_app/blocked_domain. Top lists tối đa 10 mục. Duration được quy
vào ngày effective_at của đoạn app_stop; agent nên chia đoạn ở ranh giới ngày.

Dashboard `/reports`: chọn trẻ, hôm nay/7/30 ngày hoặc khoảng tùy chỉnh; biểu đồ
thanh bằng DOM, không tải thư viện chart bên ngoài; tự cập nhật mỗi 15 giây,
empty/error states, CSV. CSV tối đa 10.000 event/lần; vượt giới hạn yêu cầu thu hẹp
ngày thay vì âm thầm cắt dữ liệu. Có UTF-8 BOM và vô hiệu hóa spreadsheet formula.

## Minh bạch và retention

`GET /api/v1/agent/transparency?start=...&end=...` trả cùng summary của trẻ như
phụ huynh, policy hiện hành, tối đa 100 event gần nhất, tối đa 100 audit đổi policy
trong khoảng ngày và giải thích privacy. Chỉ thiết bị đang hoạt động mới được đọc,
child_id luôn lấy từ token. Không trả token, fingerprint, email hay địa chỉ IP.
Không cần login riêng cho trẻ trong Week 03.

Background task chạy lúc server khởi động và mỗi 24 giờ; lỗi ghi log rồi retry sau
1 giờ. Xóa activity_events khi effective_at hoặc received_at quá 90 ngày để
batch offline không kéo dài hạn lưu và timestamp giả không tránh được retention.
Xóa screen_usage_daily và policy_audits cùng cửa sổ lưu trữ.
Khi server tắt thì task không chạy; khởi động lại sẽ chạy bù. Policy version history
không bị task này xóa vì còn phục vụ policy hiện hành và tham chiếu event.

## Kiểm thử

```powershell
# Trong server/
..\.venv\Scripts\python.exe -m pytest -q
# Từ thư mục project
node --test server/dashboard/tests/*.test.mjs
```

Test bao gồm validation policy, HMAC, audit, legacy input, batch partial ACK,
retry/conflict/cross-device ID, privacy fields, timestamp offline/future/drift,
aggregation, quota snapshot, timezone/date filters, transparency, CSV, ownership,
CSRF, revoked device, retention worker và migration round trip.

Để thử trước khi có agent Week 03: dùng Swagger `/docs` hoặc Postman với device
Bearer token hiện có để gửi batch và heartbeat có quota_date. Sau đó mở `/reports`
bằng tài khoản phụ huynh. Integration process/DNS/SafeSearch thật cần phần agent.
