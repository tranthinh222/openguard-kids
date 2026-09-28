# OpenGuard Kids Agent

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
