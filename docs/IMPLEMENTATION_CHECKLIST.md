# Checklist triển khai yêu cầu bắt buộc

Cập nhật source ngày 20/10/2026; không coi checklist source là nghiệm thu trên máy sạch.

- [x] Kiểm tra và giữ bản sửa uninstall đã có.
- [x] Sửa ACL/IPC/restore và thêm test hồi quy, gồm named pipe thật.
- [x] Consent và phiên bản thông báo khi enrollment.
- [x] Báo chặn nhầm, quyết định/lời nhắn và phản hồi Tray.
- [x] Safety exemptions DNS, policy expiry, watchdog visibility.
- [x] Audit IP và các thao tác điều khiển, hiển thị cho trẻ.
- [x] Xóa dữ liệu server/agent, offline receipt và retry ACK.
- [x] TLS pinning HTTP/WebSocket trước credentials.
- [x] AES-GCM, key môi trường/DPAPI, migration dữ liệu cũ.
- [x] Parent / child-view / admin và quyền ownership.
- [x] Bổ sung retention và xử lý cleanup khi offline.
- [x] Privacy inventory, threat model, AI usage, dependency file, seed CLI.
- [ ] Acceptance Windows SCM/ACL/Tray/DNS/browser trên máy sạch.
- [ ] Nghiệm thu tài nguyên an toàn và cuộc gọi khẩn cấp khi desktop khóa.
- [ ] Evidence M1–M6, video, báo cáo cuối và đo thời gian cài đặt.

Chi tiết và giới hạn: [REQUIREMENTS_REVIEW.md](REQUIREMENTS_REVIEW.md).
Cấu hình/migration cần làm trước khi chạy: [FINAL_CONTROLS.md](FINAL_CONTROLS.md).
