# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:**
- **MSSV:**
- **Lớp:** K4-L3B
- **Repository URL:**
- **Commit SHA cuối:**
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-<MSSV>`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (thiếu required fields, 0 correlation ID, thiếu enrichment; PII 0 leak) | | |
| `validate_dashboard.py` | 6/6 panel hợp lệ | | |
| `pytest` | 22 passed | | |
| Số traces hợp lệ | 0 (10 traces, chỉ có root `lab-agent-run`, chưa có retrieval/generation) | | |
| Số PII leak | 0 | | |
| Latency P95 / TTFT P95 | 1325 ms / 50 ms | | |
| Retrieval success rate | 100% (10/10) | | |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) gọi `clear_contextvars()` đầu mỗi request để không rò context từ request trước. Nếu client gửi `x-request-id` hợp lệ (`[A-Za-z0-9._-]{1,64}`) thì dùng lại, ngược lại sinh `req-<8-hex>` (header không hợp lệ bị thay để tránh log injection). ID được `bind_contextvars` nên mọi log line trong request đều có `correlation_id`, được lưu vào `request.state` để truyền vào `LabAgent.run` (trace metadata), và trả lại qua header `x-request-id`, `x-response-time-ms` cùng field `correlation_id` trong response body.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`, và context bind trong `/chat` (`app/main.py`): `user_id_hash` (`sha256(user_id)[:12]`, không log user_id thô), `session_id`, `feature`, `model`, `env`. Log `response_sent` có thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` được đăng ký trong chuỗi structlog ngay sau `merge_contextvars`/`TimeStamper` và **trước** `JsonlFileProcessor`/`JSONRenderer`, nên dữ liệu được redact trước khi serialize hoặc ghi xuống `data/logs.jsonl`. `scrub_event` scrub đệ quy mọi field (kể cả dict/list lồng nhau), trừ các field do hệ thống sinh (`ts`, `level`, `correlation_id`, `user_id_hash`) để tránh false positive. Pattern trong `app/pii.py` chạy theo thứ tự email → thẻ → điện thoại VN → CCCD → hộ chiếu (thẻ chạy trước để phone/CCCD không cắt một phần số thẻ). Preview được scrub trước rồi mới cắt 80 ký tự.
- **Cách kiểm chứng kết quả:** `validate_logs.py` đạt 100/100 (0 thiếu field, 0 thiếu enrichment, 18 correlation ID, 0 PII leak) — `evidence/02-log-validator.png`. Structured log thật với cùng `correlation_id` ở header, response và log — `evidence/04-structured-log.png`. Gửi request chứa thẻ/CCCD/điện thoại/email giả, log chỉ còn `[REDACTED_*]` — `evidence/05-pii-redaction.png`. Tests: `tests/test_pii.py` (từng loại PII, nhiều PII trong một câu, không false positive) và `tests/test_correlation_logging.py` (sinh/nhận ID, từ chối header không an toàn, không rò context giữa request, scrub trước khi ghi file); `pytest` 32 passed.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:**
- **Cấu trúc root/retrieval/generation observations:**
- **Cách nối trace với log:**
- **Prompt name:**
- **Version/label baseline:**
- **Version/label candidate:**
- **Trace ID của mỗi version:**
- **Cách promote và rollback `production`:**

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:**
- **SLO và lý do chọn:**
- **Cách tính error budget:**
- **Ba alert và runbook tương ứng:**

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

> Gợi ý cách viết ngắn, không thay cho evidence thực tế: "Metric cho thấy `[latency/error/cost/quality]` bất thường trong `[khoảng thời gian]`. Log line `[event]` có `correlation_id=[...]` đại diện cho request bị ảnh hưởng. Trace cùng `correlation_id` cho thấy span `[retrieval/generation/prompt/tool]` có dấu hiệu `[chậm/lỗi/token tăng]`. Root cause là `[nguyên nhân suy ra từ evidence]`. Fix action là `[hành động khôi phục]`; preventive measure là `[alert/runbook/test/guardrail để ngăn tái diễn]`."

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
