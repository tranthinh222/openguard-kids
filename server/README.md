# Openguard Kids Server

## Week 04 — source server

Phạm vi gồm API, pipeline dữ liệu, dashboard và công cụ vận hành trong `server/`.
Không thay agent. Security/functional evidence, final report và demo script là
các bước riêng thực hiện sau; unit/regression tests trong source không thay thế
nghiệm thu thực tế.

### Cài đặt và khởi động

Từ thư mục `server/`, Python 3.13 hoặc 3.14:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.maintenance check
..\.venv\Scripts\python.exe -m app.start
```

Schema tiếp tục dùng migration Week 03, không thêm bảng tuần 4. Runner kiểm tra
revision trước khi phục vụ; không tự migrate/reset dữ liệu. `GET /health` là
liveness; `GET /ready` kiểm tra kết nối DB và revision, trả 503 khi chưa sẵn sàng.
Development có thể tiếp tục dùng `uvicorn app.main:app --reload` như trước.

Ứng dụng đọc `.env` ở **thư mục gốc project** như các tuần trước. File
[`server/.env.example`](.env.example) là mẫu biến process/container, không được
autoload như `.env` thứ hai. Biến môi trường của process ưu tiên hơn root `.env`.

`ENVIRONMENT=production` hoặc `staging` bắt buộc:

- `JWT_SECRET` và `POLICY_HMAC_SECRET` khác nhau, tối thiểu 32 ký tự, không dùng
  giá trị mẫu. Secret policy phải trùng cấu hình agent; đừng đổi secret tùy tiện
  trên DB đang dùng vì policy lịch sử vẫn có chữ ký cũ.
- `WEB_COOKIE_SECURE=true`; dashboard phục vụ HTTPS qua reverse proxy.
- `ALLOWED_HOSTS` là JSON array hostname thực tế, không dùng `*`.
- Chỉ tin proxy IP thực tế qua `FORWARDED_ALLOW_IPS`; không đặt `*` trên server
  có thể được truy cập trực tiếp. WebSocket proxy cần hỗ trợ Upgrade và idle timeout
  phù hợp. `HOST`, `PORT`, `LOG_LEVEL` điều khiển runner.

Runner dùng **một worker**: registry WebSocket và rate limiter hiện ở bộ nhớ của
process. Muốn nhiều worker/replica cần shared pub/sub và shared rate limiter.
HTTP access log mặc định tắt để tránh ghi URL/query ngoài ý muốn; lỗi có request ID
và loại exception, không ghi payload/token/password hay SQL parameters.

### Giới hạn và contract

- HTTP body tối đa `MAX_REQUEST_BYTES` (mặc định 1 MiB), kể cả chunked request.
  Reverse proxy cũng nên giới hạn body và timeout cho slow clients.
- Rate limit theo IP kết nối: POST auth/enroll/refresh 30 lần/phút, API khác
  600 lần/phút; cấu hình `AUTH_REQUESTS_PER_MINUTE`, `API_REQUESTS_PER_MINUTE`.
  Vượt hạn trả 429 + `Retry-After`. Nhiều thiết bị chung NAT chia sẻ hạn mức;
  điều chỉnh cho deployment, không dùng tắt limiter để xử lý tải production.
- Dashboard cookie writes bao gồm tạo mã ghép đôi yêu cầu CSRF. Bearer API vẫn
  tương thích. JWT bắt buộc có sub/type/iat/exp. API write từ chối field lạ và
  một số kiểu dữ liệu coercion như boolean thay cho số phút.
- `agent_wall_clock` nếu gửi phải có timezone. `server_time` luôn từ server;
  `clock_drift_sec = agent_wall_clock - server_time`. Thiếu wall clock trả drift
  null và clock_trusted false. Event sau heartbeat gần đây thiếu/sai clock dùng
  received_at và clock_trusted false. Event offline không có heartbeat mới vẫn
  được kiểm tra timestamp theo cửa sổ Week 03; đây là kiểm tra hợp lý, không phải
  xác thực lịch sử offline bằng trusted anchor. Chưa thêm giao thức clock mới
  đòi sửa agent.
- `occurred_at` giữ thời điểm agent, `received_at` là lúc server nhận,
  `effective_at` dùng cho report. Các response command/request/enrollment trả
  timestamp có UTC timezone để browser không hiểu nhầm là giờ local.
- Mã ghép đôi được claim bằng SQL compare-and-set. Quyết định yêu cầu và tạo
  command nằm trong cùng transaction; hai lần duyệt không tạo hai ADD_TIME.
  Policy update đụng version trả 409 để reload, không lộ lỗi constraint.
- Pending/sent commands vẫn được resend cùng ID khi heartbeat/reconnect; ACK
  terminal đầu tiên giữ nguyên. Đây là at-least-once, agent vẫn phải deduplicate.
- WebSocket kiểm tra lại expiry/revocation mỗi `WEBSOCKET_AUTH_INTERVAL_SEC`
  (mặc định 30 giây) và trước nhận ACK; đóng bằng 4401 để agent refresh/reconnect.
  Tối đa 3 socket/device, 120 message/phút/socket, payload 4096 byte mặc định.
  ACK JSON/schema sai hoặc command không thuộc thiết bị đóng 1008.

### Retention và báo cáo

Cleanup chạy khi server khởi động rồi mỗi `RETENTION_INTERVAL_SEC` (86400), lỗi
retry sau `RETENTION_RETRY_SEC` (3600). Activity events, screen usage và policy
audit giữ cửa sổ 90 ngày như Week 03. Cleanup xóa thêm session/refresh token hết
hạn hoặc bị revoke, enrollment code đã dùng/hết hạn quá 1 ngày. Không xóa pending
commands hoặc policy versions đang làm tham chiếu. Có thể chạy thủ công:

```powershell
..\.venv\Scripts\python.exe -m app.maintenance cleanup
```

Report dùng timezone server `REPORT_TIMEZONE_OFFSET_MINUTES` (420), khoảng ngày
inclusive tối đa 90 ngày. Screen time là daily max heartbeat theo device; app
usage cộng app_stop, không thay thế screen time. UI giữ dữ liệu cũ khi polling
lỗi, báo trạng thái stale; ngăn khoảng ngày không hợp lệ và thao tác duyệt/từ chối
đồng thời. `ASSET_VERSION` version hóa entry, CSS và JS import graph bằng import
map; static responses yêu cầu revalidation. Đổi version khi phát hành source mới.

### Backup, phục hồi và reset dữ liệu demo

Không copy riêng file SQLite trong lúc server đang ghi WAL. Công cụ backup dùng
SQLite backup API để lấy snapshot gồm dữ liệu đã commit, kiểm tra integrity và
foreign keys, từ chối ghi đè file backup có sẵn:

```powershell
..\.venv\Scripts\python.exe -m app.maintenance backup --output ../backups/openguard-before-update.db
..\.venv\Scripts\python.exe -m app.maintenance verify-backup ../backups/openguard-before-update.db
```

Đặt backup ngoài public/static, giới hạn quyền truy cập thư mục bằng ACL trên
Windows hoặc permission trên Linux; backup chứa dữ liệu trẻ và token đã hash.

Phục hồi: dừng server, verify backup, **copy backup sang tên file mới** trong thư
mục data; giữ file DB cũ và sidecar để rollback. Trỏ `DATABASE_URL` tới bản copy,
chạy `alembic upgrade head`, `app.maintenance check`, rồi khởi động lại. Không thay
DB khi process đang chạy và không dùng lại WAL/SHM của DB cũ với bản phục hồi.

Reset demo: backup trước, dừng server, chọn một `DATABASE_URL` trỏ tới **file mới
chưa tồn tại**, chạy migration và khởi động. Đây là DB rỗng; cần đăng ký/ghép đôi
lại. Source không có HTTP reset endpoint hoặc thao tác tự xóa DB.

### Docker

Build context là `server/`, không copy agent hay root `.env`:

```powershell
docker build -t openguard-server .
docker volume create openguard-server-data
docker run --rm --env-file .env.deploy -v openguard-server-data:/data openguard-server python -m alembic upgrade head
docker run --rm --name openguard-server --env-file .env.deploy -v openguard-server-data:/data -p 127.0.0.1:8000:8000 openguard-server
```

Tạo `.env.deploy` từ mẫu và điền secrets thật; không commit. Container chạy user
không phải root. Dùng named volume mới sẽ nhận quyền `/data` từ image; bind mount
cần cấp quyền UID 10001. Đặt HTTPS reverse proxy trước cổng 8000 khi chạy staging/
production. ALLOWED_HOSTS phải chứa `127.0.0.1` nếu dùng healthcheck mặc định.
Build/deploy Docker và restore drill cần xác minh trên môi trường triển khai riêng.

## Week 03

Xem [contract, migration và hướng dẫn kiểm thử Week 03](docs/WEEK03_CONTRACT.md).
Các thay đổi Week 03 nằm hoàn toàn trong `server/`, gồm API và dashboard.
