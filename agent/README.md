# OpenGuard Kids Agent

## Week 03

Hướng dẫn cấu hình, test app/DNS/offline và các giới hạn triển khai: [WEEK03.md](WEEK03.md).

```powershell
.\.venv\Scripts\python.exe -m pip install -r agent/requirements.txt
.\.venv\Scripts\python.exe agent/agent_gui.py
```

Agent nhận policy ngay qua WebSocket (xác minh HMAC), heartbeat là fallback.
GUI có biểu tượng system tray; đóng cửa sổ sẽ thu xuống tray, chọn **Thoát agent**
để dừng. **Hôm nay / quyền riêng tư** hiển thị báo cáo, policy đang áp dụng,
lịch sử thay đổi và event chưa đồng bộ. Nút tạm dừng đồng bộ chỉ dừng heartbeat,
không dừng bảo vệ app/DNS, WebSocket hay upload event.

## Chạy giao diện

Từ thư mục gốc của dự án, dùng Python trong virtual environment:

```bash
.venv/bin/python agent/agent_gui.py
```

Hoặc kích hoạt môi trường trước:

```bash
source .venv/bin/activate
python agent/agent_gui.py
```

Trên trang phụ huynh, mở hồ sơ trẻ và bấm **Tạo mã ghép đôi**. Dán mã
8 ký tự vào cửa sổ agent rồi bấm **Ghép thiết bị**. Sau khi ghép thành công,
GUI tự khởi động heartbeat.

## Policy và screen time (Week 02)

Agent tự đọc file `.env` ở thư mục gốc dự án. Bảo đảm
`OGK_POLICY_HMAC_SECRET` giống `POLICY_HMAC_SECRET` của server, sau đó chạy:

```powershell
python openguard_agent.py run
```

Agent tải policy mới sau heartbeat, xác minh HMAC-SHA256 và schema rồi mới lưu
vào SQLite (`agent.db`). Policy sai bị từ chối, policy tốt gần nhất vẫn được dùng
và sự kiện `POLICY_REJECTED` được ghi vào bảng `security_events`.

Service đếm active usage bằng `time.monotonic()` mỗi giây. Thời gian idle,
session bị khóa và thời gian ngoài weekly schedule không được cộng. Tổng theo
ngày và bonus được lưu trong bảng `usage_daily`; khi hết quota agent gọi API
khóa workstation của Windows.

Giao diện có hai trạng thái:

- **Chưa ghép**: ô nhập mã lớn, thông báo lỗi ngay dưới ô nhập và phần
  **Cài đặt nâng cao** chứa địa chỉ server.
- **Đã ghép**: trạng thái bảo vệ, kết nối server, thời điểm đồng bộ cuối và
  phiên bản chính sách. Nút **Kiểm tra kết nối** gửi heartbeat ngay; phần
  **Thông tin thiết bị** có tuỳ chọn tạm dừng đồng bộ hoặc ghép lại.

Mỗi lần mở lại, nếu máy đã được ghép thì agent tự đồng bộ.

Tkinter đi kèm bản cài Python tiêu chuẩn. Trên một số bản Linux tối giản, cần
cài thêm gói `python3-tk` của hệ điều hành.

## Chạy bằng dòng lệnh

```bash
.venv/bin/python agent/openguard_agent.py enroll ABCD1234
.venv/bin/python agent/openguard_agent.py run
```
