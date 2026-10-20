# OpenGuard Kids

Ứng dụng hỗ trợ phụ huynh quản lý thời gian sử dụng máy tính, ứng dụng và website của trẻ trên Windows. Trẻ được xem thời lượng, hoạt động, chính sách và lý do bị chặn; có thể xin thêm giờ hoặc báo chặn nhầm. Không thu phím gõ, ảnh màn hình, nội dung tin nhắn, tiêu đề cửa sổ hay URL đầy đủ.

## Cài đặt từ máy sạch

Hướng dẫn dành cho Windows 10/11 x64, PowerShell và môi trường lab. Mục tiêu là dựng hệ thống trong khoảng 15 phút sau khi có Python và tải xong phụ thuộc; chưa có phép đo nghiệm thu thời gian trên máy sạch.

Cần cài Python **3.13 x64** từ bộ cài có pip và Tcl/Tk (Tkinter), Git nếu clone repository, trình duyệt và kết nối Internet để tải thư viện. SQLite đi kèm Python, không cần cài database server. Agent cần quyền Administrator để cài dịch vụ; tài khoản của trẻ phải là tài khoản thường. Docker và Node.js không bắt buộc để chạy sản phẩm; Node.js 24 dùng khi chạy test JavaScript.

### 1. Chuẩn bị môi trường

Mở PowerShell tại thư mục gốc source đã tải về, ví dụ `D:\Code\openguard-kids`:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirement.txt
if (!(Test-Path server/.env)) { Copy-Item server/.env.example server/.env }
if (!(Test-Path agent/.env)) { Copy-Item agent/.env.example agent/.env }
```

Nếu triển khai trên hai máy, mỗi máy tạo `.venv` riêng và chỉ cài `server/requirements.txt` hoặc `agent/requirements.txt`. Không sao chép virtual environment giữa các máy. Giữ thư mục source và Python ở vị trí ổn định sau khi cài dịch vụ.

### 2. Điền cấu hình

Sinh hai secret khác nhau (chạy lệnh hai lần), dùng lần lượt cho JWT và chữ ký policy:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Sinh khóa mã hóa **một lần**, sao lưu và giữ nguyên khi nâng cấp:

```powershell
.\.venv\Scripts\python.exe -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

| File | Biến cần điền |
| --- | --- |
| `server/.env` | `JWT_SECRET`, `POLICY_HMAC_SECRET`, `DATA_ENCRYPTION_KEY` bằng các giá trị vừa sinh |
| `agent/.env` | `OGK_POLICY_HMAC_SECRET` giống `POLICY_HMAC_SECRET`; `OGK_SERVER_URL=http://127.0.0.1:8000` khi cùng máy |

Giữ `ENVIRONMENT=development`, `WEB_COOKIE_SECURE=false` cho HTTP lab. Agent trên máy khác dùng IP LAN của server thay `127.0.0.1`. Các file `.env` chứa secret, không commit và không đưa vào ảnh báo cáo. Biến môi trường process ưu tiên hơn `.env`. Hướng dẫn HTTPS và pin chứng chỉ nằm trong [README server](server/README.md) và [README agent](agent/README.md).

### 3. Khởi động server và tạo tài khoản demo

```powershell
cd server
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.maintenance check
..\.venv\Scripts\python.exe -m app.seed --email demo@example.com --demo-child
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Lệnh seed hỏi mật khẩu tương tác. Dùng mật khẩu 10–128 ký tự ASCII không khoảng trắng, có chữ hoa, số và ký tự đặc biệt. **Tài khoản demo: `demo@example.com`; mật khẩu: giá trị bạn vừa nhập.** Source không có mật khẩu chung. Không chạy seed lại với email đã tồn tại.

Mở `http://127.0.0.1:8000/login`, đăng nhập, mở hồ sơ `Demo Child`. `/health` và `/ready` phải trả thành công. Nếu agent ở máy khác, dùng `--host 0.0.0.0`, cho phép TCP 8000 qua firewall trong mạng lab và dùng IP LAN để truy cập.

### 4. Cài agent và ghép thiết bị

Giữ cửa sổ server chạy. Mở PowerShell **Run as Administrator** mới tại thư mục gốc:

```powershell
.\.venv\Scripts\python.exe agent\openguard_service.py install
.\.venv\Scripts\python.exe agent\openguard_service.py status
```

Service `OpenGuardKids` chạy LocalSystem, tự mở Tray trong phiên đăng nhập. Mặc định service cấu hình DNS máy về proxy cục bộ; xem [hướng dẫn agent](agent/README.md) trước khi dùng trên máy có cấu hình mạng riêng.

Trên dashboard, xác nhận thông báo thu thập dữ liệu rồi tạo mã ghép đôi. Nhập mã 8 ký tự vào Tray và ghép trong 10 phút. Sau heartbeat, thiết bị hiện online. Không chạy thêm `openguard_agent.py run` khi service đã chạy.

### 5. Kiểm tra đầu cuối

- Sửa quota/lịch trên dashboard, kiểm tra policy mới ở Tray.
- Chặn `example.com`, thử `Resolve-DnsName example.com -Server 127.0.0.1 -DnsOnly`; xác nhận NXDOMAIN và sự kiện chặn.
- Mở `/reports` để xem báo cáo; mở **Hôm nay / quyền riêng tư** trên Tray để xem dữ liệu dành cho trẻ.
- Gửi yêu cầu thêm giờ từ Tray, duyệt trên dashboard và kiểm tra phản hồi.

Các bước trên là hướng dẫn kiểm tra, không phải bằng chứng đã nghiệm thu trên mọi máy.

## Tài liệu và cấu trúc

| Vị trí | Nội dung |
| --- | --- |
| [agent/README.md](agent/README.md) | Cài/gỡ service, cấu hình, DNS, xử lý lỗi |
| [server/README.md](server/README.md) | Server/dashboard, HTTPS, migration, backup, Docker |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Thành phần, giao thức, thời gian, dữ liệu và giới hạn |
| [docs/DOMAIN_CATEGORIES.md](docs/DOMAIN_CATEGORIES.md) | Nguồn, phạm vi và dữ liệu kiểm thử domain |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Bảng dữ liệu – mục đích – thời hạn – người xem |
| [docs/PRIVACY_CHILD.md](docs/PRIVACY_CHILD.md) | Giải thích quyền riêng tư dành cho trẻ |
| [docs/THREATMODEL.md](docs/THREATMODEL.md) | STRIDE và checklist bảo mật |
| [docs/AI_USAGE.md](docs/AI_USAGE.md) | Khai báo sử dụng và kiểm chứng AI |

Dashboard nằm trong `server/dashboard/`, không cần build frontend riêng. Test nằm trong `server/tests/`, `agent/tests/` và `server/dashboard/tests/`. Dataset nộp kèm là `server/app/data/domain_categories.csv`.

## Kiểm thử

Tại thư mục gốc, sau khi cài `requirement.txt`:

```powershell
.\.venv\Scripts\python.exe -m pytest agent/tests -q
node --test server/dashboard/tests/*.test.mjs
cd server
..\.venv\Scripts\python.exe -m pytest tests -q
```

Kết quả đã ghi nhận ngày 20/10/2026: server 76 passed, agent 114 passed/21 skipped, dashboard 14 passed. Skipped không được tính đạt. Cài service/DNS/ACL/Tray thực, SafeSearch trên browser và các phép đo mạng cần nghiệm thu riêng.

## Phạm vi nộp và sử dụng

Chỉ sử dụng với sự đồng ý hợp lệ trên máy được phép quản lý; không dùng theo dõi bí mật. DNS filtering không bảo đảm ngăn mọi VPN, DoH hoặc truy cập IP trực tiếp. Máy offline phải kết nối lại để hoàn tất xóa dữ liệu cục bộ. DNS miễn chặn không bảo đảm truy cập website khi desktop đang khóa.

Đề còn yêu cầu `docs/BaoCao.docx`, `docs/BaoCaoKyThuatMang.pdf` (M1–M6), evidence kiểm thử và `demo/video.mp4`. Các tài liệu kỹ thuật trong repository không thay thế các sản phẩm này; không coi chúng đã hoàn thành khi chưa có tệp và phép đo thực tế.
