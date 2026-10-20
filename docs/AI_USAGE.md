# Sử dụng AI trong đồ án

Tài liệu này ghi nhận phần có thể xác minh từ phiên làm việc hiện tại; nhóm cần bổ sung
tên thành viên, thời gian và công cụ thực tế trước khi nộp. Không suy đoán lịch sử đã dùng AI.

| Công cụ | Công việc | Cách kiểm chứng |
| --- | --- | --- |
| ChatGPT bản web (do người dùng cung cấp context) | Thảo luận thiết kế, chức năng và nội dung báo cáo | Đối chiếu yêu cầu gốc và source; trao đổi web không được coi là bằng chứng triển khai |
| Codex trong workspace | Rà source, đề xuất/sửa code server-agent, viết migration/tests và tài liệu | Review git diff; pytest server/agent; Node dashboard tests; migration DB tạm |
| Công cụ tra cứu web trong phiên | Đối chiếu domain dataset và địa chỉ tài nguyên an toàn | Ghi nguồn trong [DOMAIN_CATEGORIES.md](DOMAIN_CATEGORIES.md); không dùng domain nội dung người lớn thật |

Các thay đổi AI cần nhóm đọc lại, chạy thử và chịu trách nhiệm trước khi dùng/nộp.
Không đưa `.env`, token, khóa hoặc dữ liệu của trẻ thật vào báo cáo/ảnh evidence.
Test PASS chỉ áp dụng môi trường đã chạy; skipped không phải PASS. AI không tự tạo số đo
latency/CPU/RAM, ảnh nghiệm thu hoặc kết luận đáp ứng mọi yêu cầu khi chưa có evidence.

Xem [hướng dẫn hệ thống](../README.md), [kiến trúc](ARCHITECTURE.md)
và [THREATMODEL.md](THREATMODEL.md) để phân biệt source đã có với nghiệm thu còn lại.
