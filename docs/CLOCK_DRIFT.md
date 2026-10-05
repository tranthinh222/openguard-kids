# Đồng bộ thời gian và phát hiện clock drift

Server dùng đồng hồ UTC của máy chủ để xác thực token và tạo timestamp cho
request/lệnh. `agent_wall_clock` chỉ là số liệu chẩn đoán do agent khai báo.
Heartbeat vẫn trả HTTP 200 khi đồng hồ agent lệch để agent có thể lấy giờ đúng.
Yêu cầu xin thêm giờ, lấy policy và ACK vẫn hợp lệ; thời điểm tạo request do server đặt.

## Heartbeat

`AGENT_CLOCK_DRIFT_THRESHOLD_SEC` mặc định là 120, cấu hình ở `.env` phía server.
Không cần migration hoặc chỉnh `.env` hiện có để dùng giá trị mặc định.

- `clock_drift_sec`: giờ agent trừ giờ server, tính bằng giây.
- `clock_trusted`: true khi có giờ agent và độ lệch tuyệt đối không vượt ngưỡng.
- `clock_drift_threshold_sec`: ngưỡng server đang dùng.
- `server_time`: cùng mốc UTC được dùng để tính drift và cập nhật last-seen.

Thiếu `agent_wall_clock` trả drift null và trusted false, không tái sử dụng số đo cũ.
Trạng thái này mô tả đồng hồ máy agent, không phải việc kết nối có thành công hay không.

## Agent

GUI giữ một ClockMonitor dùng chung cho heartbeat, protection và command handler.
Quota theo ngày, lịch tuần và ADD_TIME đều dùng server anchor + thời gian monotonic.
Đổi đồng hồ Windows sau đồng bộ không làm đổi ngày quota hoặc lịch đang áp dụng.
Múi giờ địa phương được giữ trong phiên chạy để việc đổi timezone giữa phiên không
đổi lịch; cấu hình timezone theo policy và DST chưa được triển khai.

Mỗi heartbeat lệch ngưỡng ghi clock_events với timestamp server và log
`CLOCK_TAMPERING`. GUI hiển thị “Đồng hồ máy đang sai” khi nhận trạng thái này.
Thời điểm đồng bộ cuối cũng dùng timestamp server. Cảnh báo drift được cập nhật
ở heartbeat tiếp theo, mặc định tối đa khoảng 60 giây; enforcement đã dùng monotonic
ngay từ lần đồng bộ đầu tiên.

Mất mạng trong cùng phiên chạy: tiếp tục dùng server anchor + monotonic và policy cache.
Khởi động lại: không coi timestamp đã lưu hoặc đồng hồ local là nguồn giờ tin cậy,
vì chưa có cách xác minh thời gian đã trôi qua giữa các lần chạy.
Nếu có policy cache nhưng chưa heartbeat thành công, counter chờ tối đa 30 giây
từ lúc khởi tạo bằng monotonic clock (`clock_sync_pending`), không khóa máy trong
khoảng chờ này. Khi đồng bộ thành công, quota/lịch được áp dụng ngay, không đợi hết
30 giây. Nếu hết hạn vẫn chưa có giờ tin cậy, counter trả `clock_unverified` và
yêu cầu khóa máy cho tới khi xác minh được giờ server. Deadline không được gia hạn
bởi các lần tick hoặc retry heartbeat. Lệnh LOCK_NOW đã lưu vẫn khóa ngay.
Thiết bị chưa có policy không
bị khóa bởi nhánh này. WebSocket bắt đầu sau khi có anchor, tránh cộng giờ nhầm ngày.

Đây là lựa chọn fail-closed cho restart/offline; chưa triển khai trusted-clock
persistence qua reboot. Grace persistence và việc tách Windows Service khỏi Tray
là các vấn đề riêng, chưa được giải quyết bởi bản sửa drift.
Khoảng chờ khởi động được tạo lại khi runtime được khởi tạo lại; chống việc cố ý
restart liên tục cần xử lý cùng vòng đời Service và trạng thái khởi động bền vững.

## Kiểm tra thủ công

1. Khởi động lại server và agent sau khi cập nhật source.
2. Đặt server trên máy có đồng hồ độc lập, đặt `OGK_SERVER_URL` trên máy agent.
3. Đồng bộ agent, đặt quota ngắn và ghi lại thời gian còn lại.
4. Đổi đồng hồ máy agent tiến/lùi 12 giờ hoặc sang ngày khác. Sau heartbeat,
   kiểm tra `clock_trusted=false`, độ lệch khác 0 và cảnh báo trên GUI.
5. Kiểm tra quota không được cấp lại và lịch vẫn theo giờ thật của server.
6. Xin thêm 15 phút: request vẫn thành công, created_at theo giờ server;
   sau khi phụ huynh duyệt, bonus được cộng vào ngày theo trusted clock.
7. Khôi phục đồng hồ agent: heartbeat tiếp theo trả trusted true, cảnh báo được gỡ.
8. Mất mạng sau khi đồng bộ: enforcement tiếp tục. Restart agent khi mất mạng
   và có policy cache: hiển thị chờ xác minh giờ, khóa máy sau 30 giây nếu chưa
   đồng bộ được; kết nối lại để phục hồi.

Nếu server và agent chạy trên cùng Windows hoặc VM tự đồng bộ giờ với host đang
bị chỉnh, cả hai đồng hồ có thể lệch cùng nhau. Khi đó drift gần 0 là kết quả đúng
của phép so sánh; cơ chế này không cung cấp nguồn giờ độc lập cho server.
Không tắt kiểm tra TLS để vượt lỗi chứng chỉ khi đồng hồ hệ thống sai.

## Test tự động

Từ thư mục project:

```powershell
.\.venv\Scripts\python.exe -m pytest agent/tests -q
```

Từ thư mục server:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

Test dùng đồng hồ giả và khóa máy giả, không thay đổi giờ hệ thống hay khóa máy thật.
Bao gồm biên ±120 giây, ngưỡng tùy chỉnh, thiếu timestamp, phục hồi clock,
server-created request timestamp, quota/schedule khi đổi ngày,
shared clock trong GUI, cộng giờ đúng ngày và restart chưa có giờ tin cậy.
