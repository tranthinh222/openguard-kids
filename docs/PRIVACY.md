# Quyền riêng tư — OpenGuard Kids

> **Phiên bản:** 1.0 — bản chốt tài liệu đồ án, đối chiếu source ngày 19/10/2026.
> **Đối tượng:** phụ huynh, người vận hành và người đánh giá đồ án.
> **Bản dành cho trẻ:** [Ứng dụng này ghi nhận gì về em?](PRIVACY_CHILD.md)

Tài liệu mô tả hành vi hiện có và các khoảng trống của prototype. “Bản chốt” không có nghĩa mọi yêu cầu bảo mật, quyền riêng tư hoặc pháp lý đã hoàn thành. Các mục chưa triển khai được ghi rõ; tài liệu không thay thế đánh giá pháp lý hay evidence kiểm thử.

## 1. Mục đích và nguyên tắc

OpenGuard Kids hỗ trợ phụ huynh thiết lập thời gian sử dụng máy, kiểm soát ứng dụng/tên miền và trao đổi yêu cầu thêm giờ với trẻ. Dữ liệu được dùng để thực thi chính sách, giải thích hoạt động bị hạn chế, đồng bộ và lập báo cáo sử dụng.

> Công cụ đồng hành, không phải phần mềm theo dõi lén.

- Chỉ xử lý dữ liệu cần thiết cho chức năng đã công bố.
- Có giao diện agent/Tray để trẻ xem hoạt động, policy và thông tin quyền riêng tư.
- Không có chức năng quảng cáo hoặc bán dữ liệu trong prototype.
- Không coi một sự kiện DNS là bằng chứng trẻ chủ động mở một trang web; ứng dụng nền cũng có thể tạo truy vấn.
- Metadata ứng dụng và tên miền vẫn có thể tiết lộ thói quen riêng tư, vì vậy cần giới hạn truy cập và thời hạn lưu.

## 2. Dữ liệu không thu thập

Không có pipeline thu thập nội dung tin nhắn, email, tài liệu, nội dung gõ phím, ảnh màn hình, tiêu đề cửa sổ, tên tài liệu đang mở, clipboard, âm thanh, hình ảnh camera, GPS hay danh bạ. Sự kiện hoạt động không chứa URL đầy đủ, đường dẫn trang hoặc query string.

Agent đọc tệp **thực thi ứng dụng** để tính SHA-256. Đây là xử lý cục bộ để nhận diện chương trình, không phải đọc tài liệu của trẻ hoặc tải nội dung tệp lên server. Idle detection kiểm tra thời gian từ lần tương tác gần nhất, không ghi phím nào đã được gõ.

## 3. Dữ liệu được xử lý và người được tiếp cận

| Nhóm | Dữ liệu chính | Mục đích / nơi xử lý | Phạm vi tiếp cận |
| --- | --- | --- | --- |
| Tài khoản phụ huynh | Email, password hash, trạng thái, số lần đăng nhập sai | Server: xác thực và hạn chế thử mật khẩu | Dịch vụ xác thực; không trả password hash cho UI |
| Phiên dashboard | Token hash, CSRF token, thời điểm hết hạn/thu hồi | Server và cookie trình duyệt: duy trì phiên | Phiên của phụ huynh tương ứng |
| Hồ sơ trẻ | ID, tên hiển thị, năm sinh tùy chọn | Server: gắn policy và báo cáo | Phụ huynh sở hữu; agent nhận thông tin theo API được cấp |
| Thiết bị | ID, tên máy, fingerprint hash, trạng thái, lần liên lạc, phiên bản policy, usage và độ lệch giờ | Server/agent: ghép nối, đồng bộ và kiểm soát | Phụ huynh sở hữu, agent được xác thực |
| Enrollment và token | Hash mã ghép, thời hạn, thời điểm dùng; hash refresh token | Server: ghép một lần, cấp/thu hồi quyền truy cập | Dịch vụ xác thực; mã ghép gốc chỉ hiển thị khi tạo |
| Policy và audit | Quota, lịch, app/domain rules, SafeSearch, phiên bản, chữ ký; người sửa và nội dung trước/sau | Server, policy cache của agent | Phụ huynh và trẻ qua giao diện/API tương ứng |
| Hoạt động | Tên executable hoặc tên miền đăng ký, loại sự kiện, thời lượng, thời điểm, ID sự kiện và policy | SQLite agent → server → báo cáo | Phụ huynh sở hữu; trẻ qua transparency |
| Screen time | Thiết bị, ngày, số giây sử dụng | Agent đo, server tổng hợp | Phụ huynh và trẻ |
| Yêu cầu và lệnh | Yêu cầu thêm giờ, phản hồi, trạng thái; loại lệnh, payload, thời điểm gửi/ACK, lỗi | Server/agent: điều khiển và chống xử lý lặp | Phụ huynh và agent tương ứng; trẻ xem phản hồi qua UI |
| Dữ liệu kỹ thuật cục bộ | PID, thời điểm tạo tiến trình, user/session, executable path, SHA-256; nhật ký policy/clock | Agent: nhận diện, áp policy, chẩn đoán | Tiến trình agent và người có quyền truy cập máy |

Đường dẫn executable và thông tin tiến trình dùng trong bộ nhớ, không có trong payload activity gửi server. SHA-256 được cache và lưu cùng tổng hợp ứng dụng cục bộ; SHA-256 cũng có thể nằm trong rule policy. Không mô tả SHA-256 như một trường của mọi activity event trên server.

Người quản trị có quyền truy cập hệ điều hành, database hoặc backup có thể đọc dữ liệu lưu trữ. Kiểm tra ownership ở API không ngăn được quyền truy cập trực tiếp này. Prototype chưa có cổng admin với audit mọi thao tác quản trị.

## 4. Luồng dữ liệu và kết nối ra ngoài

### 4.1. Hoạt động và báo cáo

```text
Agent phát sinh sự kiện → SQLite outbox → gửi batch có xác thực
→ server kiểm tra → ACK từng sự kiện → agent đánh dấu synced
```

Mỗi sự kiện có UUID giữ nguyên khi retry. Server phát hiện bản gửi trùng và xung đột nội dung; agent xử lý partial ACK. Mất mạng thì dữ liệu chờ trong SQLite. ACK không xóa sự kiện ngay: bản đã đồng bộ còn phục vụ xem lịch sử cục bộ cho đến khi được prune.

Payload gồm `event_id`, `ts`, `type`, `subject`, `duration_sec`, `policy_id`. Server xác định trẻ/thiết bị từ token; nếu có các trường identity tương thích cũ, chúng phải khớp thiết bị đã xác thực. Trường ngoài schema bị từ chối.

Các loại được schema chấp nhận: `app_start`, `app_stop`, `domain_query`, `blocked_app`, `blocked_domain`, `quota_warning`, `locked`, `unlock_request`, `override_granted`. Danh sách schema không có nghĩa mọi luồng UI đều phát đủ các loại này.

Server lưu thêm `occurred_at`, `received_at`, `effective_at`, `clock_trusted` và `payload_hash` để xử lý độ tin cậy thời gian và gửi trùng. Chỉ `app_stop` mang thời lượng ứng dụng khác 0. Screen time được tổng hợp riêng, không bằng tổng thời lượng các tiến trình chạy đồng thời.

### 4.2. DNS và dịch vụ bên ngoài

- Proxy kiểm tra hostname đầy đủ để match rule, nhưng sự kiện từ agent lưu **registrable domain**: ví dụ `drive.google.com` được ghi thành `google.com`.
- Truy vấn được phép chuyển tới DNS upstream, mặc định `1.1.1.1`, cấu hình bằng `OGK_DNS_UPSTREAM`. Nhà cung cấp DNS nhận tên được truy vấn và thông tin kết nối; resolver hiện dùng DNS UDP/TCP, không phải DNS mã hóa.
- SafeSearch dùng điều chỉnh DNS, không giải mã nội dung HTTPS. Không có HTTPS interception.
- Dashboard hiện tải Bootstrap và biểu tượng từ `cdn.jsdelivr.net`; trình duyệt tạo kết nối tới CDN, nên nhà cung cấp có thể nhận metadata mạng của yêu cầu tải tài nguyên.
- Prototype không tích hợp SDK quảng cáo/analytics. Tuy nhiên, không thể tuyên bố “không có kết nối tới bên thứ ba” vì có upstream DNS và CDN.

DoH, VPN, DNS khác, direct IP và kết nối đang mở có thể vượt ngoài tác dụng chặn DNS. Domain event không đo thời gian xem trang; thông báo chặn xác nhận một truy vấn bị chặn, không xác nhận mọi kết nối tới website đã bị ngắt.

## 5. Lưu trữ và cleanup thực tế

Các thời hạn xác thực dưới đây là giá trị mặc định, có thể đổi qua cấu hình. **Thời hạn hiệu lực không đồng nghĩa thời điểm bản ghi được xóa vật lý.**

| Dữ liệu | Cơ chế hiện có |
| --- | --- |
| ActivityEvent trên server | Cleanup bản có `received_at` hoặc `effective_at` cũ hơn 90 ngày |
| ScreenUsage và PolicyAudit | Cleanup theo ngày sử dụng / thời điểm audit cũ hơn 90 ngày |
| WebSession, DeviceRefreshToken | Cleanup bản hết hạn hoặc đã bị thu hồi; mặc định phiên web 12 giờ, refresh token 30 ngày |
| Access token của agent | Hiệu lực mặc định 15 phút; không phải bảng lịch sử được giữ 90 ngày |
| EnrollmentCode | Hiệu lực 10 phút, dùng một lần; cleanup khi đã dùng hoặc hết hạn quá 1 ngày |
| Agent `events`, `app_usage_daily` | Prune dữ liệu cũ hơn 90 ngày; áp dụng cả sự kiện chưa sync hoặc bị từ chối |
| Tài khoản, trẻ, thiết bị, policy các phiên bản, request và command | Chưa có cleanup theo tuổi bản ghi trong job retention hiện tại |
| Agent usage, warning, processed command, remote lock, policy/security/clock và content cache | Không có cam kết cleanup 90 ngày bao phủ toàn bộ các bảng này |
| CSV, backup và log ngoài ứng dụng | Không được job database tự xóa; người vận hành quản lý riêng |

Server chạy retention loop, mặc định mỗi 24 giờ và retry sau 1 giờ khi lỗi; có lệnh maintenance cleanup. Agent gọi prune sau khi đồng bộ và lấy dataset thành công, dự kiến khoảng mỗi giờ khi kết nối hoạt động. Offline kéo dài hoặc lỗi sync có thể trì hoãn prune. Vì vậy **90 ngày là ngưỡng cleanup**, không phải bảo đảm xóa đúng thời điểm tròn 90 ngày trên mọi bản sao.

SQLite DELETE cũng không phải chứng nhận xóa không thể phục hồi trên ổ đĩa/WAL/backup. Khi triển khai thực tế cần chính sách backup, quyền truy cập và quy trình xóa riêng.

## 6. Trẻ và phụ huynh xem, điều chỉnh dữ liệu thế nào?

- Phụ huynh xem và sửa policy, xem báo cáo và xuất CSV trong phạm vi hồ sơ trẻ mình sở hữu. CSV hiện xuất sự kiện hoạt động, không phải bản xuất toàn bộ dữ liệu cá nhân.
- Trẻ mở **Hôm nay / quyền riêng tư** trên agent/Tray để xem usage, hoạt động/chặn, policy, lịch sử policy và lời giải thích. Khi offline, giao diện có thể dùng dữ liệu cục bộ/cache nên chưa phản ánh cập nhật mới nhất.
- API `/api/v1/agent/transparency` xác thực bằng token thiết bị, giới hạn theo trẻ gắn với thiết bị. Đây không phải một tài khoản web có role `child-view` độc lập. Hoạt động và audit trả tối đa 100 mục mỗi loại trong khoảng yêu cầu.
- Trẻ có thể gửi yêu cầu thêm giờ. Nếu thông tin sai hoặc chặn nhầm, trẻ trao đổi với phụ huynh để kiểm tra policy; chưa có luồng phản ánh chặn nhầm chuyên biệt được xác nhận trong source.
- Chưa có chức năng tự phục vụ **xóa toàn bộ dữ liệu trẻ** xuyên server–agent, re-authentication cho thao tác đó hoặc lệnh `DELETE_CHILD_DATA`. Thu hồi thiết bị không đồng nghĩa dữ liệu đã bị xóa.

Yêu cầu sửa/xóa dữ liệu trong bản demo cần được chuyển cho phụ huynh và người vận hành đồ án để xử lý có kiểm soát, bao gồm máy agent, server, CSV và backup. Không hứa đã xóa khi thiết bị offline chưa được xử lý. Khi bàn giao, người vận hành phải cung cấp đầu mối liên hệ thực tế; tài liệu không tự tạo địa chỉ hỗ trợ chưa tồn tại.

## 7. Thông báo và sự đồng ý

Bản thông báo dành cho trẻ ở [PRIVACY_CHILD.md](PRIVACY_CHILD.md) đáp ứng phần tài liệu dễ hiểu: ghi gì, không ghi gì, ai xem, thời hạn và cách đặt câu hỏi. Phụ huynh nên cùng trẻ đọc trước khi ghép thiết bị.

**Giới hạn triển khai:** model enrollment chưa có `consent_at`, `privacy_notice_version`, `child_assent_at`; chưa có bước opt-in bắt buộc kèm lưu bằng chứng hoặc luồng rút lại sự đồng ý. Việc nhập mã ghép, đọc tài liệu hay mở Tray không tự chứng minh đã có sự đồng ý hợp lệ. Yêu cầu consent/assent trong đề cần được báo cáo là phần còn thiếu, không đánh dấu hoàn thành chỉ vì đã có bản thông báo.

## 8. Biện pháp bảo vệ và giới hạn

| Biện pháp | Trạng thái source |
| --- | --- |
| Argon2id, token/mã ghép lưu hash ở server | Có; mật khẩu đăng ký hiện 10–128 ký tự |
| Session cookie, CSRF, ownership | Có HttpOnly/SameSite, kiểm tra CSRF cho thao tác cookie-auth và quyền sở hữu ở server |
| Production | Có kiểm tra cấu hình secret/Secure cookie; HTTPS phải được triển khai ở hạ tầng thực tế |
| Hạn chế đăng nhập và API | Có khóa tạm khi đăng nhập sai, rate limit và giới hạn body |
| Policy integrity | HMAC-SHA256, kiểm tra version, giữ last-known-good; HMAC không mã hóa nội dung policy |
| Clock integrity | Server làm tham chiếu, monotonic đo thời lượng; event đánh dấu mức tin cậy |
| Agent local secrets | State JSON có token; chưa có DPAPI/AES-GCM bảo vệ chúng. `chmod` không chứng minh Windows ACL đã được harden |
| Kênh mạng | Có tùy chọn kiểm tra chứng chỉ TLS; chưa có certificate pinning. Chạy HTTP local để demo không chứng minh TLS production |
| Database/backup | Chưa có mã hóa toàn bộ database ở tầng ứng dụng; cần bảo vệ tệp và bản sao bằng cơ chế vận hành |

Không ghi mật khẩu/token vào evidence, ảnh chụp, báo cáo hoặc issue. Log của web server/reverse proxy có thể chứa IP và đường dẫn API tùy cấu hình; cần kiểm tra và đặt retention riêng. PolicyAudit hiện ghi actor, thời điểm, phiên bản và payload trước/sau; không có `source_ip` hay audit mọi thao tác admin như bản thiết kế ban đầu.

## 9. Đối chiếu yêu cầu đồ án và nguồn tham chiếu

Các nguồn dưới đây phục vụ giải thích thiết kế, không phải chứng nhận tuân thủ. Không trộn điều khoản trích từ văn bản cũ với tên luật mới.

| Tham chiếu | Áp dụng / giới hạn |
| --- | --- |
| [Luật Trẻ em 2016, Điều 21](https://congbao.chinhphu.vn/van-ban/luat-so-102-2016-qh13-19611/14045.htm) | Bảo vệ đời sống riêng tư: tránh thu nội dung, giới hạn dữ liệu và quyền xem |
| Luật An ninh mạng 2018, Điều 29 theo rubric; [Luật 116/2025/QH15](https://vanban.chinhphu.vn/?classid=&docid=216499&pageid=27160) có hiệu lực 01/07/2026 | Domain filtering/SafeSearch hỗ trợ bảo vệ trẻ; không tuyên bố chặn mọi nội dung hoặc mọi bypass |
| Nghị định 13/2023/NĐ-CP theo rubric lịch sử; [Luật 91/2025/QH15](https://vanban.chinhphu.vn/?classid=1&docid=214590&pageid=27160&typegroup=) và [Nghị định 356/2025/NĐ-CP](https://chinhphu.vn/?docid=216387&pageid=27160), hiệu lực 01/01/2026 | Rà soát mục đích, thông báo, quyền dữ liệu và consent. Prototype còn thiếu luồng consent/assent và xóa toàn bộ |
| [Quyết định 830/QĐ-TTg](https://vanban.chinhphu.vn/?docid=203332&pageid=27160), chương trình 2021–2025 | Định hướng tương tác lành mạnh: cảnh báo, yêu cầu thêm giờ và transparency; không coi giai đoạn chương trình là còn đang diễn ra |
| [OWASP ASVS v4.0.3](https://github.com/OWASP/ASVS/tree/v4.0.3) theo rubric | Đối chiếu authentication, session, access control, validation, bảo vệ dữ liệu; chưa có kết luận đạt toàn bộ Level 1 |
| [NIST SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html) | Yêu cầu tối thiểu 15 ký tự với mật khẩu dùng làm yếu tố duy nhất; code hiện tối thiểu 10, nên chưa đáp ứng điểm này. Chưa có blocklist mật khẩu phổ biến/bị lộ |

Các mục chưa hoàn thành cần giữ trong kết luận đồ án: consent/assent có bằng chứng; xóa dữ liệu xuyên thiết bị; retention đầy đủ cho các bảng/cache và backup; hardening Windows; bảo vệ local token; pinning nếu rubric yêu cầu; bộ evidence ASVS và triển khai TLS thực tế. Không bổ sung các chức năng chưa có như safety allowlist cố định, nhắc 20-20-20 hay audit admin vào danh sách “đã triển khai”.

## 10. Nguồn kiểm chứng trong repository

| Nội dung | Source |
| --- | --- |
| Model và schema sự kiện | [models](../server/app/models/), [activity schema](../server/app/schemas/activity.py) |
| Xác thực và cấu hình | [security](../server/app/core/security.py), [auth schema](../server/app/schemas/auth.py), [config](../server/app/core/config.py) |
| Transparency / CSV | [activity routes](../server/app/api/routes/activity.py), [giao diện trẻ](../agent/transparency_ui.py) |
| DNS và tên miền lưu sự kiện | [DNS proxy](../agent/service/dns/proxy.py), [resolver](../agent/service/dns/resolver.py) |
| Ứng dụng và SHA-256 | [app monitor](../agent/service/apps/monitor.py) |
| Outbox và prune | [event queue](../agent/service/events/queue.py), [content runtime](../agent/service/content_runtime.py) |
| Cleanup server | [retention](../server/app/services/retention.py), [activity service](../server/app/services/activity_service.py) |
| Local state | [agent](../agent/openguard_agent.py) |

Các test liên quan nằm ở `server/tests/test_week03.py`, `server/tests/test_week04.py`, `server/tests/test_clock_drift.py`, `agent/tests/test_week03_agent.py`, `agent/tests/test_policy_manager.py` và `agent/tests/test_clock_monitor.py`. Sự tồn tại của test không thay thế log chạy test. Bản cập nhật tài liệu này không công bố số PASS mới hoặc coi yêu cầu chưa có code là đã được kiểm thử thành công.
