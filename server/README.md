# OpenGuard Kids Server

FastAPI phục vụ API và dashboard Jinja2/JavaScript trong `server/dashboard/`; không cần Node.js hay build frontend để chạy. SQLite/SQLAlchemy lưu dữ liệu, Alembic quản lý schema. Hướng dẫn đầu cuối: [README gốc](../README.md).

## Cài đặt

Cần Python 3.13 và pip; SQLite đi kèm Python. Tại thư mục gốc source:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
if (!(Test-Path server/.env)) { Copy-Item server/.env.example server/.env }
```

Bỏ bước tạo venv nếu đã có. Điền `JWT_SECRET`, `POLICY_HMAC_SECRET` và `DATA_ENCRYPTION_KEY` theo [README gốc](../README.md). Không khởi động với placeholder. Khóa AES là base64 của 32 byte ngẫu nhiên, tạo một lần và sao lưu; mất khóa sẽ không đọc được dữ liệu đã mã hóa.

Server tự đọc `server/.env`; biến môi trường process ưu tiên hơn file. Chạy lệnh bên dưới từ `server/` để SQLite tương đối luôn trỏ đúng database:

```powershell
cd server
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.maintenance check
..\.venv\Scripts\python.exe -m app.seed --email demo@example.com --demo-child
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Seed hỏi mật khẩu, không ghi log hay đặt mật khẩu mặc định. Đăng nhập `/login` bằng `demo@example.com` và mật khẩu đã nhập. `--demo-child` chỉ dùng development/test, tạo hồ sơ demo chưa ghép thiết bị. Tài khoản đã tồn tại không bị ghi đè. Cũng có thể đăng ký phụ huynh qua `/register`.

Nếu cần phục vụ máy khác trong LAN, đổi host thành `0.0.0.0` và cho phép TCP 8000 qua firewall. `/health` kiểm tra process; `/ready` kiểm tra DB/revision. Runner `python -m app.start` kiểm tra schema trước khi chạy; không tự migrate hay reset.

## Cấu hình và HTTPS

Tạo chứng chỉ lab bằng script có sẵn, chạy từ **thư mục gốc repository**:

```powershell
.\.venv\Scripts\python.exe tools/create_lab_certs.py --ip 127.0.0.1 --dns localhost --out lab-certs
# Nếu agent khác máy, thêm IP LAN thật của server, ví dụ:
# .\.venv\Scripts\python.exe tools/create_lab_certs.py --ip 127.0.0.1 --ip 192.168.1.10 --dns localhost --out lab-certs
```

Chọn một lệnh phù hợp, không chạy cả hai với cùng thư mục. Script cần `cryptography`
(đã có trong requirements), tạo CA riêng và chứng chỉ server có SAN tương ứng,
hiệu lực mặc định 365 ngày (`--days` để đổi). `--ip`/`--dns` có thể lặp nhiều lần.
Thư mục output phải chưa tồn tại; script không ghi đè hoặc tự thay chứng chỉ đang dùng.

Output gồm `ca.pem`, `ca-key.pem`, `server.pem`, `server-key.pem`,
`server-sha256.txt`. Script in `OGK_TLS_CA_FILE` và `OGK_TLS_CERT_SHA256` để
điền phía agent. Với agent khác máy, sao chép **chỉ `ca.pem`** và sửa đường dẫn
CA thành đường dẫn tuyệt đối trên máy agent; fingerprint giữ nguyên.
Service đã cài đọc cấu hình ProgramData trước `agent/.env`.

Khóa riêng không có mật khẩu để server khởi động tự động; giới hạn quyền thư mục
cho người quản trị/server. `ca-key.pem` chỉ dùng cấp chứng chỉ, không phân phối.
Output mặc định và tên `*-key.pem` được Git bỏ qua. Không commit chứng chỉ/khóa
sinh ra ở đường dẫn tùy chỉnh. Script không tự import CA, đổi `.env` hay restart service.

Chạy HTTPS từ `server/`:

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-certfile ../lab-certs/server.pem --ssl-keyfile ../lab-certs/server-key.pem
```

Đặt `WEB_COOKIE_SECURE=true`, `ALLOWED_HOSTS` đúng hostname/IP. Agent dùng URL
`https://<địa chỉ trong SAN>:8000`, `OGK_VERIFY_TLS=true`, CA và pin vừa tạo.
Để browser tin chứng chỉ, import **CA công khai do chính bạn tạo** vào kho
Trusted Root của tài khoản dùng dashboard, ví dụ tại root repository:

```powershell
Import-Certificate -FilePath .\lab-certs\ca.pem -CertStoreLocation Cert:\CurrentUser\Root
```

Kiểm tra `/ready`, heartbeat và WebSocket; browser không được cảnh báo chứng chỉ.
Nếu tạo bộ mới, CA và pin cũng mới: cần phân phối lại. Không tắt xác minh TLS để
bỏ qua lỗi. CA lab chỉ phù hợp môi trường thử nghiệm được quản lý.

| Biến | Vai trò |
| --- | --- |
| `ENVIRONMENT` | development/test/staging/production |
| `DATABASE_URL` | Mặc định `sqlite:///./data/openguard.db` khi chạy từ server/ |
| `JWT_SECRET` | Secret JWT, khác secret policy |
| `POLICY_HMAC_SECRET` | Ký policy; trùng `OGK_POLICY_HMAC_SECRET` phía agent |
| `DATA_ENCRYPTION_KEY` | AES-GCM cho trường nhạy cảm và email lookup |
| `WEB_COOKIE_SECURE` | false chỉ cho HTTP lab, true khi HTTPS |
| `ALLOWED_HOSTS` | JSON array hostname được phép |
| `REPORT_TIMEZONE_OFFSET_MINUTES` | Mặc định 420, thống nhất với agent |
| `AGENT_CLOCK_DRIFT_THRESHOLD_SEC` | Mặc định 120 giây |
| `RETENTION_INTERVAL_SEC` | Chu kỳ cleanup, mặc định 86400; không phải tuổi dữ liệu |

Production/staging yêu cầu secret thực ít nhất 32 ký tự, khóa mã hóa hợp lệ, secure cookie và host cụ thể. Chỉ triển khai **một worker** vì WebSocket registry và rate limiter hiện nằm trong bộ nhớ process.

Dùng HTTPS reverse proxy có TLS ≥1.2, chứng chỉ hợp lệ và hỗ trợ WebSocket Upgrade. Chỉ tin IP proxy thực tế qua `FORWARDED_ALLOW_IPS`; không dùng wildcard khi server truy cập trực tiếp được. Agent cần `OGK_TLS_CERT_SHA256` lấy từ chứng chỉ DER đã xác minh và CA PEM nếu CA nội bộ. Khi đổi chứng chỉ, cập nhật pin trước khi kết nối lại.

Có thể chạy TLS trực tiếp trong lab với chứng chỉ/khóa riêng đã chuẩn bị:

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-certfile C:/certs/server.pem --ssl-keyfile C:/certs/server-key.pem
```

Tên host trong URL phải khớp SAN của chứng chỉ. Không thay HTTPS bằng HTTP để tuyên bố đạt yêu cầu bảo mật. `HOST`, `PORT`, `FORWARDED_ALLOW_IPS` của runner được đọc từ môi trường process; nếu cần hãy đặt `$env:HOST`, `$env:PORT` trong PowerShell hoặc truyền tham số Uvicorn như trên.

## Dashboard và phân quyền

- `/dashboard`, `/children`: tổng quan, hồ sơ, thiết bị và consent trước ghép đôi.
- `/policies`: quota ngày thường/cuối tuần, lịch 7×48, rule ứng dụng/domain, category và SafeSearch.
- `/requests`: thêm giờ và báo chặn nhầm; ghi nhận báo chặn nhầm không tự đổi rule.
- `/reports`: screen time, top apps/domains, số lần chặn, khoảng ngày và CSV.
- Tray đọc transparency: báo cáo, policy, lịch sử và quyền riêng tư.

Parent chỉ thao tác trên trẻ thuộc mình. Child-view chỉ đọc, gắn với device/child; parent cấp token 15 phút qua `POST /api/v1/children/{child}/devices/{device}/child-view-token`. Admin chỉ thống kê vận hành, không tự có quyền xem hồ sơ trẻ của parent khác. Provision admin qua CLI:

```powershell
..\.venv\Scripts\python.exe -m app.seed --email operator@example.com --role admin
```

Admin lấy bearer token ở `/api/v1/auth/token`, đọc `/api/v1/admin/summary`. Không có dashboard admin riêng. Cookie writes yêu cầu CSRF; API bearer kiểm tra loại token và quyền sở hữu.

## Đồng bộ và dữ liệu

Policy version/HMAC được đẩy qua WebSocket; heartbeat mặc định 60 giây là fallback. Command pending/sent được gửi lại cùng ID tới khi ACK terminal; agent chống thực thi trùng. Sự kiện upload theo batch, ACK từng event; retry không tạo bản ghi trùng. Xem [kiến trúc](../docs/ARCHITECTURE.md).

Báo cáo dùng `effective_at`, timezone cấu hình và khoảng ngày tối đa 90 ngày. Screen time lấy usage tổng hợp từ heartbeat; tổng app duration có thể lớn hơn do nhiều process cùng chạy. Không cộng app duration để thay screen time.

Cleanup chạy lúc khởi động và theo chu kỳ, retry lỗi sau `RETENTION_RETRY_SEC`. Activity, usage, policy/control audit, request và command có retention 90 ngày; token/session/enrollment có vòng đời riêng. Policy/state đang làm tham chiếu và receipt chưa ACK không bị coi là lịch sử thông thường. Chạy thủ công:

```powershell
..\.venv\Scripts\python.exe -m app.maintenance cleanup
```

Xóa hồ sơ cascade dữ liệu server, giữ receipt chỉ chứa token hash để agent reconnect nhận yêu cầu xóa. Agent dừng thu thập, xóa cache rồi ACK; offline chưa thể xác nhận xóa ngay. Backup/CSV bên ngoài phải xử lý riêng. Xem [PRIVACY.md](../docs/PRIVACY.md).

## Nâng cấp, sao lưu và phục hồi

Giữ nguyên khóa AES và secret policy. Trước nâng cấp, tạo backup bằng SQLite backup API; không copy riêng DB đang ghi WAL:

```powershell
..\.venv\Scripts\python.exe -m app.maintenance backup --output ../backups/openguard-before-update.db
..\.venv\Scripts\python.exe -m app.maintenance verify-backup ../backups/openguard-before-update.db
```

Sau đó dừng server, chạy `alembic upgrade head`, `app.maintenance check` và khởi động lại. Migration mã hóa dữ liệu cũ cần đúng `DATA_ENCRYPTION_KEY`; sao lưu khóa tách biệt và bảo vệ cả khóa lẫn DB. SQLite ≥3.35 cần cho thao tác downgrade bỏ cột trực tiếp. Không downgrade trên dữ liệu thật để thử nghiệm.

Phục hồi: dừng server, verify backup, copy sang **tên file mới**, trỏ `DATABASE_URL` vào bản copy rồi migrate/check. Giữ DB cũ để rollback; không ghép WAL/SHM cũ với DB phục hồi. Reset demo bằng database mới và seed lại, không xóa DB đang dùng.

## Docker (tùy chọn)

Cần Docker Engine/Docker Desktop. Từ `server/`:

```powershell
docker build -t openguard-server .
docker volume create openguard-server-data
docker run --rm --env-file .env -e DATABASE_URL=sqlite:////data/openguard.db -v openguard-server-data:/data openguard-server python -m alembic upgrade head
docker run --rm -it --env-file .env -e DATABASE_URL=sqlite:////data/openguard.db -v openguard-server-data:/data openguard-server python -m app.seed --email demo@example.com --demo-child
docker run --rm --name openguard-server --env-file .env -e DATABASE_URL=sqlite:////data/openguard.db -v openguard-server-data:/data -p 127.0.0.1:8000:8000 openguard-server
```

Seed demo chỉ dùng development/test. Image không chứa `.env`, chạy user không phải root; bind mount cần quyền UID 10001. Mapping trên chỉ cho host truy cập; khi triển khai LAN/HTTPS cấu hình proxy hoặc publish phù hợp. Agent/DNS proxy vẫn chạy trên Windows, không nằm trong container server.

## Kiểm thử và giới hạn

Cài `requirement.txt` ở root để có pytest/httpx. Từ server/: `..\.venv\Scripts\python.exe -m pytest tests -q`. Test JavaScript dùng Node.js 24 từ root: `node --test server/dashboard/tests/*.test.mjs`.

Giới hạn gồm SQLite cho deployment nhỏ, WebSocket/rate limit một process, dataset tĩnh và DNS bypass. Chưa có số đo bảo đảm latency hay hiệu năng trên mọi môi trường. Test tự động không thay thế nghiệm thu HTTPS, backup restore, Windows và bộ đo M1–M6.
