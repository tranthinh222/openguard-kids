# Dataset phân loại tên miền — phiên bản 2

Cập nhật ngày 20/10/2026. Nguồn dữ liệu duy nhất: [domain_categories.csv](../server/app/data/domain_categories.csv).
API phụ huynh `/api/v1/domain-categories` và API agent `/api/v1/agent/domain-categories`
cùng phục vụ bảng này qua [loader](../server/app/services/domain_categories.py).
CSV nằm trong `app/data` nên được đóng gói cùng Docker image hiện tại.

## Yêu cầu và số lượng

Đối chiếu F2 trong đề `QuanLyMayTinhTreEm.md`: bảng phân loại tối thiểu **200 mục**, đủ
6 nhóm. Đề không đặt tối thiểu riêng cho từng nhóm.

| Nhóm | Số mục |
| --- | ---: |
| education | 135 |
| entertainment | 21 |
| social | 17 |
| games | 25 |
| age_inappropriate | 4 |
| unknown | 27 |
| **Tổng** | **229** |

139 mục có nhãn vùng VN. Một số trường đại học có hostname riêng dưới cùng domain
đại học quốc gia; đây là các mục hostname, không tuyên bố có 229 registrable domain
độc lập. Không thêm hàng loạt subdomain giả để đạt số lượng.

## Nguồn và phương pháp

- Ưu tiên trường, nền tảng học tập và dịch vụ Việt Nam. Phân loại theo mục đích chính
  của dịch vụ, là quyết định biên tập của dự án, không phải nhãn do nhà cung cấp chứng nhận.
- Tham khảo [đơn vị thành viên ĐHQGHN](https://vnu.edu.vn/gioi-thieu/co-cau-to-chuc/cac-truong-dai-hoc-thanh-vien),
  [OLM](https://olm.vn/), [HOCMAI](https://hocmai.vn/) và trang chủ ghi ở từng dòng CSV.
- Kiểm tra HTTP tự động 266 domain ứng viên, giữ 219 mục trả HTTP 200, cộng 6 mục
  được giữ theo nguồn tham chiếu/compatibility dù không đọc trực tiếp được và 4 fixture.
  `verification` là kết quả truy cập, **không phải** chứng nhận nội dung an toàn hay
  kết quả kiểm thử chặn DNS. HTTP 200 cũng có thể là trang challenge hoặc trang chuyển vùng.
- Các mục giữ dù truy cập trực tiếp lỗi: `ueb.vnu.edu.vn`, `sis.vnu.edu.vn` có trong
  danh mục chính thức ĐHQGHN; `olm.vn` có nguồn web được đối chiếu; `wikipedia.org`,
  `roblox.com`, `steampowered.com` giữ tương thích dataset cũ. Chúng cần được kiểm tra
  lại khi làm evidence trên mạng demo. Không diễn giải timeout/403 thành domain nguy hại.
- Qua kiểm tra trang chủ, `go.vn` hiện là goEdu nên được xếp giáo dục, không xếp game.
  Các cổng tin tức và GapoWork được để `unknown` vì bộ 6 nhóm không có news/workplace.
- Trường `title` chỉ lưu tiêu đề trang chủ công khai trong lần biên soạn dataset;
  không phải dữ liệu thu từ hoạt động duyệt web của trẻ và không gửi trong API dataset.

## Nhóm mô phỏng nội dung không phù hợp

Chỉ gồm `example.com`, `example.net`, `example.org`, `age-restricted.example.test`.
Ba domain example được [IANA dành cho tài liệu](https://www.iana.org/help/example-domains);
`.test` dành cho kiểm thử theo [RFC 2606](https://www.rfc-editor.org/rfc/rfc2606).
Đây là nhãn mô phỏng để test category blocking, không phải nhận định về nội dung thật.
CSV ghi `test_only=true`; API có `test_only_domains` để nhận diện.

Không truy cập, lưu hoặc đính kèm domain có nội dung người lớn thật.
Không dùng `.test` làm bằng chứng DNS chặn thành công chỉ vì nhận NXDOMAIN:
nó vốn không phân giải công khai. Với test DNS thật, cần đối chứng khi bỏ chặn
và xác nhận event/reason do proxy sinh ra.

## Áp dụng và giới hạn

- Restart server sau khi đổi CSV; agent tải dataset lúc sync và refresh khoảng mỗi giờ.
  Restart runtime/service agent để kích hoạt lượt tải sớm; chỉ đóng/mở Tray không restart runtime.
- Giữ thứ tự `explicit_allow > explicit_block > category > default_allow`.
  Domain không có trong CSV nhận `unknown`. Thêm dataset không tự đổi policy phụ huynh:
  muốn chặn nhóm phải bật nhóm đó trong `blocked_categories`.
- Phân loại áp dụng cả subdomain; không phân tích từng video/bài viết và không chứng nhận
  mọi nội dung trên YouTube, mạng xã hội, game hoặc dịch vụ streaming phù hợp lứa tuổi.
- `unknown` bao gồm cổng tin tức/chính phủ. Chặn toàn bộ unknown có thể chặn nhầm tài nguyên
  cần thiết; dùng explicit allow cho các domain cần bảo đảm truy cập.
- Dataset tĩnh cần rà soát định kỳ vì domain có thể đổi nội dung/chủ sở hữu.

## Kiểm chứng

`server/tests/test_domain_categories.py` kiểm tra số lượng, schema, trùng lặp, nguồn và
fixture an toàn. `agent/tests/test_category_dataset.py` đưa toàn bộ CSV qua matcher thật,
kiểm tra domain/subdomain, ưu tiên allow và fallback unknown (không truy cập mạng).

Đạt 200 mục **chưa đồng nghĩa** đạt nghiệm thu F2. Tiêu chí chặn ≥95% bộ 50 domain,
0 dương tính giả trên 20 domain giáo dục và policy mặc định độ tuổi cần evidence riêng.
Phụ lục đề gợi ý 20/10/8/7/5/10 mục (tổng 60, có DoH và mô phỏng); không nhầm bảng gợi ý
này với số lượng bắt buộc theo từng category hoặc kết quả test đã chạy.
