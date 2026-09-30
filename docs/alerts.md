# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (99.5% request thành công và `latency_ms <= 3000` trong 28 ngày); panel "Latency percentiles and TTFT".
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms) > 3000ms` liên tục 5 phút.
- Ảnh hưởng tới người dùng: người dùng phải chờ trên 3 giây để nhận câu trả lời, mỗi request chậm tiêu error budget.
- Ba bước kiểm tra đầu tiên:
  1. Mở `/dashboard`, panel latency: xác nhận P50/P95/P99 và khoảng thời gian tăng. So với TTFT P95: TTFT bình thường mà latency cao thì phần chậm nằm ngoài LLM (retrieval, fetch prompt, hàng đợi).
  2. Lọc `data/logs.jsonl` trong khoảng đó: `event == "response_sent" and latency_ms > 3000`, lấy `correlation_id`.
  3. Trên Langfuse, lọc trace có metadata `correlation_id` đó, so sánh thời gian của `retrieval` và `llm-generation` với phần còn lại của `lab-agent-run`.
- Mitigation tạm thời: nếu `retrieval` chậm thì tắt practice scenario `rag_slow`, hoặc chuyển sang tài liệu fallback. Nếu thời gian nằm ngoài hai span con (fetch prompt từ Langfuse) thì kiểm tra kết nối tới Langfuse và dùng prompt cache hoặc fallback local. Nếu chậm do tải thì giảm concurrency.
- Owner: `student-2A202602505`

## Alert 2

- Tên: `HighErrorRate`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (request lỗi là bad event); guardrail `error_rate_pct_max: 2`; panel "Error rate and retrieval success".
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received) * 100 > 2%` liên tục 5 phút.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 thay vì câu trả lời; 5 phút ở 100% lỗi đủ tiêu hết budget của nhiều ngày.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel errors: xem error rate và breakdown `count_by_value` theo `error_type` để biết loại lỗi chiếm đa số.
  2. Lọc log `event == "request_failed"`, đọc `error_type`, `payload.detail`, `tool_name` và lấy `correlation_id`.
  3. Mở trace cùng `correlation_id`: observation nào có level `ERROR` (ví dụ `retrieval` với `RuntimeError: Vector store timeout`).
- Mitigation tạm thời: tắt practice scenario gây lỗi (`tool_fail`), rollback thay đổi gần nhất (label `production` của prompt hoặc config), bật fallback trả lời không cần retrieval.
- Owner: `student-2A202602505`

## Alert 3

- Tên: `LowRetrievalSuccess`
- Severity: `critical`
- Duration: `10m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail `retrieval_success_rate_pct_min: 90`; panel "Error rate and retrieval success" (đường retrieval success %).
- Điều kiện và thời gian duy trì: `count(tool_success == true) / count(tool_success != null) * 100 < 90%` liên tục 10 phút.
- Ảnh hưởng tới người dùng: câu trả lời không có context từ tài liệu nên sai hoặc chung chung; khi retrieval raise lỗi thì request fail luôn.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel errors: so đường retrieval success % với error rate để phân biệt retrieval fail làm hỏng cả request hay chỉ giảm chất lượng; xem thêm panel quality.
  2. Lọc log có `tool_name == "retrieval"` và `tool_success == false`, lấy `correlation_id` và thời điểm bắt đầu.
  3. Mở trace, xem observation `retrieval`: level, `status_message`, output `doc_count`.
- Mitigation tạm thời: tắt scenario `tool_fail`, khởi động lại hoặc chuyển vector store dự phòng, tạm trả câu trả lời fallback và báo người dùng thử lại.
- Owner: `student-2A202602505`
