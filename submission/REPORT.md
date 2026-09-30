# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Văn Quốc Dũng
- **MSSV:** 2A202602505
- **Lớp:** K4-L3B
- **Repository URL:** [https://github.com/vvstdung89/K4-L3-DAY13-VanQuocDung-2A202602505-Monitoring-LLMOps](https://github.com/vvstdung89/K4-L3-DAY13-VanQuocDung-2A202602505-Monitoring-LLMOps)
- **Commit SHA cuối:** `2916c1f0c87a6b559e5fea9d20b56ad944b4e748` (commit chứa toàn bộ source, config và evidence; commit sau đó chỉ ghi SHA này vào report)
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602505`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.


| Evidence            | Đường dẫn                                                                                                                   |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Pytest cuối         | `evidence/01-pytest.png`                                                                                                    |
| Log validator       | `evidence/02-log-validator.png`                                                                                             |
| Dashboard validator | `evidence/03-dashboard-validator.png`                                                                                       |
| Structured log      | `evidence/04-structured-log.png`                                                                                            |
| PII redaction       | `evidence/05-pii-redaction.png`                                                                                             |
| Trace list          | `evidence/06-trace-list.png`                                                                                                |
| Trace waterfall     | `evidence/07-trace-waterfall.png`                                                                                           |
| Trace metadata      | `evidence/08-trace-metadata.png`, `evidence/08b-generation-metadata.png`                                                    |
| Prompt versions     | `evidence/09-prompt-versions.png`                                                                                           |
| Prompt rollback     | `evidence/10a-prompt-before-promote.png`, `evidence/10b-prompt-after-promote.png`, `evidence/10c-prompt-after-rollback.png` |
| Dashboard runtime   | `evidence/11-dashboard-overview.png`                                                                                        |
| Incident metric     | `evidence/12-incident-metric.png`                                                                                           |
| Incident log        | `evidence/13-incident-log.png`                                                                                              |
| Incident trace      | `evidence/14-incident-trace.png`, `evidence/14b-incident-trace-metadata.png`                                                |


## 3. Kết quả kỹ thuật


| Nội dung                | Baseline                                                                       | Kết quả cuối                                                       | Nhận xét                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| `validate_logs.py`      | 30/100 (thiếu required fields, 0 correlation ID, thiếu enrichment; PII 0 leak) | 100/100 (207 records, 98 correlation ID, 0 thiếu field/enrichment) | Correlation middleware + bind context + scrub trước khi ghi (CP1)                               |
| `validate_dashboard.py` | 6/6 panel hợp lệ                                                               | 6/6 panel hợp lệ                                                   | Contract giữ nguyên; dashboard runtime `/dashboard` đọc đúng contract                           |
| `pytest`                | 22 passed                                                                      | 38 passed                                                          | +16 test: PII, correlation/logging, child observations, dashboard                               |
| Số traces hợp lệ        | 0 (10 traces, chỉ có root `lab-agent-run`, chưa có retrieval/generation)       | 64 traces có root + retrieval + generation (88 traces tổng)        | 24 trace chỉ có root là từ baseline/trước CP2                                                   |
| Số PII leak             | 0                                                                              | 0 (log) và chỉ preview đã scrub trên trace                         | Sample query có email/thẻ; baseline đã che nhờ `summarize_text`, nay scrub mọi field            |
| Latency P95 / TTFT P95  | 1325 ms / 50 ms                                                                | 157 ms / 50 ms                                                     | Lượt cuối 10 request, 05:17Z; sau khi prompt `day13-chat` có trên Langfuse, không còn fetch 404 |
| Retrieval success rate  | 100% (10/10)                                                                   | 100% (95/95)                                                       | Kể cả trong incident: retrieval chậm nhưng không lỗi                                            |


## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) gọi `clear_contextvars()` đầu mỗi request để không rò context từ request trước. Nếu client gửi `x-request-id` hợp lệ (`[A-Za-z0-9._-]{1,64}`) thì dùng lại, ngược lại sinh `req-<8-hex>` (header không hợp lệ bị thay để tránh log injection). ID được `bind_contextvars` nên mọi log line trong request đều có `correlation_id`, được lưu vào `request.state` để truyền vào `LabAgent.run` (trace metadata), và trả lại qua header `x-request-id`, `x-response-time-ms` cùng field `correlation_id` trong response body.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`, và context bind trong `/chat` (`app/main.py`): `user_id_hash` (`sha256(user_id)[:12]`, không log user_id thô), `session_id`, `feature`, `model`, `env`. Log `response_sent` có thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` được đăng ký trong chuỗi structlog ngay sau `merge_contextvars`/`TimeStamper` và **trước** `JsonlFileProcessor`/`JSONRenderer`, nên dữ liệu được redact trước khi serialize hoặc ghi xuống `data/logs.jsonl`. `scrub_event` scrub đệ quy mọi field (kể cả dict/list lồng nhau), trừ các field do hệ thống sinh (`ts`, `level`, `correlation_id`, `user_id_hash`) để tránh false positive. Pattern trong `app/pii.py` chạy theo thứ tự email → thẻ → điện thoại VN → CCCD → hộ chiếu (thẻ chạy trước để phone/CCCD không cắt một phần số thẻ). Preview được scrub trước rồi mới cắt 80 ký tự.
- **Cách kiểm chứng kết quả:** `validate_logs.py` đạt 100/100 (207 records, 0 thiếu field, 0 thiếu enrichment, 98 correlation ID, 0 PII leak) — `evidence/02-log-validator.png`. Structured log thật với cùng `correlation_id` ở header, response và log — `evidence/04-structured-log.png`. Gửi request chứa thẻ/CCCD/điện thoại/email giả, log chỉ còn `[REDACTED_*]` — `evidence/05-pii-redaction.png`. Tests: `tests/test_pii.py` (từng loại PII, nhiều PII trong một câu, không false positive) và `tests/test_correlation_logging.py` (sinh/nhận ID, từ chối header không an toàn, không rò context giữa request, scrub trước khi ghi file); `pytest` 38 passed — `evidence/01-pytest.png`.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** `.env` dùng key của project `day13-k4-l3b-2A202602505` (xác nhận qua `GET /api/public/projects`). Tôi tự chạy `scripts/load_test.py` và các request prompt; trace list lọc root observation có 49 traces `day13-agent-request`, environment `dev` (`evidence/06-trace-list.png`).
- **Cấu trúc root/retrieval/generation observations:** root `lab-agent-run` (type `agent`, `@observe`) chứa 2 child tạo bằng `start_as_current_observation` trong `app/agent.py`: `retrieval` (type `retriever`, input là query preview đã scrub, output `doc_count` + preview tài liệu, level `ERROR` khi retrieval raise lỗi) và `llm-generation` (type `generation`, có `model`, prompt link `day13-chat`, `usage_details` input/output, `cost_details` input/output/total). Input/output của generation chỉ là preview đã scrub PII (`evidence/07-trace-waterfall.png`, `evidence/08b-generation-metadata.png`).
- **Cách nối trace với log:** middleware truyền `correlation_id` vào `LabAgent.run`; `propagate_attributes(metadata=...)` gắn nó vào metadata của mọi observation, root span còn có tokens, cost, latency. Tìm log theo `correlation_id` rồi lọc trace metadata cùng giá trị, ví dụ `req-20d00003` ↔ trace `6496daf9173509bc46a6bd252076b4d2` (`evidence/08-trace-metadata.png`).
- **Prompt name:** `day13-chat` (text prompt với `{{feature}}`, `{{docs}}`, `{{message}}`).
- **Version/label baseline:** v1, labels `baseline` + `production` (template gốc của contract).
- **Version/label candidate:** v2, label `candidate` (thêm câu "You are a concise support assistant. Answer in at most 3 sentences using only the docs.").
- **Trace ID của mỗi version:** cùng input "Explain why metrics traces and logs work together":
  
  | Label khi chạy            | Prompt version | correlation_id | Trace ID                           |
  | ------------------------- | -------------- | -------------- | ---------------------------------- |
  | `baseline`                | v1             | `req-ba5e0011` | `f6eb17f18a7f9fc3ae962b23e3477f74` |
  | `candidate`               | v2             | `req-ca0d0002` | `8c07a5558867636419d9c7f8d4029db0` |
  | `production` sau promote  | v2             | `req-20d00013` | `a3fe6e1c9c6833491e5519277579a1f0` |
  | `production` sau rollback | v1             | `req-10d00014` | `ef1a567cae7369169d662ea7a83c3c3c` |
  
- **Cách promote và rollback `production`:** không sửa code; app đọc prompt theo `LANGFUSE_PROMPT_NAME` + `LANGFUSE_PROMPT_LABEL`. Promote: chuyển label `production` sang v2 (`langfuse.update_prompt(name="day13-chat", version=2, new_labels=["production"])`), khởi động lại API để bỏ cache 60s, request `req-20d00013` dùng v2. Rollback: chuyển `production` về v1 (`version=1`), request `req-10d00014` dùng lại v1. Mỗi ảnh chọn đúng version đang mang label `production` (`?version=N`) để thấy nội dung prompt thay đổi: v1 (chỉ 3 biến) → v2 (thêm câu "concise support assistant") → v1. Ảnh trước/sau: `evidence/10a-prompt-before-promote.png`, `evidence/10b-prompt-after-promote.png`, `evidence/10c-prompt-after-rollback.png`; danh sách version: `evidence/09-prompt-versions.png`.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `GET /dashboard` (`app/dashboard.py`) đọc `data/logs.jsonl` mỗi lần mở trang, lấy title/unit/threshold/time range/refresh trực tiếp từ `config/dashboard.yaml`: cửa sổ 60 phút, tự refresh 30s, 6 panel Latency (P50/P95/P99 + TTFT P95, đường threshold 3000ms), Traffic (request/phút, threshold ≥1), Errors (error rate %, breakdown `error_type`, retrieval success %), Cost (theo phút + cumulative, thanh mức dùng so với 2.5 USD), Tokens (tokens_in/out, so với 50,000), Quality (mean, threshold 0.75). Mỗi panel có badge OK/BREACH so với threshold (`evidence/11-dashboard-overview.png`; `validate_dashboard.py` 6/6 — `evidence/03-dashboard-validator.png`).
- **SLO và lý do chọn:** `fast_successful_requests` = 99.5% request trả `response_sent` với `latency_ms <= 3000` trong 28 ngày (`config/slo.yaml`). Baseline khi prompt đã có trên Langfuse: P50 152ms, P95 1333ms, P99 1539ms, nên 3000ms cao gấp ~2 lần P99 bình thường, tránh báo động giả nhưng vẫn bắt được incident như `rag_slow` (+2.5s).
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5% số request trong 28 ngày. 10,000 request → tối đa 50 request lỗi/chậm; ~1,000 request/ngày → 28,000 request → 140 request. Trong lab, 11/51 request vi phạm SLO (78.43% tốt), đều trước khi prompt tồn tại: 10 request ~6.2s do fetch prompt 404 và 1 request 735,713ms khi kết nối tới Langfuse bị treo. Bài học: fetch prompt nằm trên đường xử lý request nên phụ thuộc ngoài có thể tiêu hết budget.
- **Ba alert và runbook tương ứng:** (`config/alert_rules.yaml`, `docs/alerts.md`, Slack `#k4-l3b-alerts`, owner `student-2A202602505`)
  1. `HighLatencyP95` — warning, `p95(latency_ms) > 3000ms` trong 5m → runbook `docs/alerts.md#alert-1`.
  2. `HighErrorRate` — critical, error rate > 2% trong 5m → `docs/alerts.md#alert-2`.
  3. `LowRetrievalSuccess` — critical, retrieval success < 90% trong 10m → `docs/alerts.md#alert-3`.

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4, seed 1312, affected feature `monitoring`, `latency_threshold_ms` 2000). Chạy `python scripts/inject_incident.py` rồi `python scripts/load_test.py --challenge --concurrency 5` (2 lượt, 10 request).
- **Khoảng thời gian điều tra:** incident 05:01:41Z–05:02:10Z (12:01:41–12:02:10 giờ VN). Mốc so sánh khỏe mạnh ngay trước: 05:01:22Z–05:01:27Z. Fix và kiểm chứng: 05:08:02Z–05:08:40Z.
- **Triệu chứng từ metrics:** panel latency (`/dashboard?minutes=10`, `evidence/12-incident-metric.png`): P50 tăng từ 153ms lên **2,653ms** (~17 lần), P95 từ 1,566ms lên **2,654ms**, vượt `latency_threshold_ms` 2000 của challenge. **TTFT P95 giữ nguyên 50ms**, error rate 0%, retrieval success 100%, tokens/cost/quality bình thường, nên chỗ chậm nằm ngoài LLM và không phải lỗi. Lưu ý: P95 2,654ms vẫn dưới threshold SLO 3000ms nên panel vẫn báo OK và alert `HighLatencyP95` sẽ không bắn.
- **Log line và correlation ID liên quan:** lọc `response_sent` trong khoảng incident (`evidence/13-incident-log.png`): cả 10 request `feature=monitoring` có `latency_ms` 2652–2654, `ttft_ms=50`, `tool_name=retrieval`, `tool_success=true`; các request `qa/summary` ngay trước chỉ ~153ms. Request đại diện: `correlation_id=req-c1b49090`, session `k4-l3b-challenge-s05`, `request_received` lúc 05:01:42.494Z, `response_sent` lúc 05:01:45.147Z, `latency_ms=2652`.
- **Trace ID và span gây ảnh hưởng:** trace `14e2ede7121fdaf2d23897e3686c2bbc`, metadata `correlation_id=req-c1b49090` (`evidence/14b-incident-trace-metadata.png`). Waterfall (`evidence/14-incident-trace.png`): `lab-agent-run` 2,653ms, trong đó `**retrieval` 2,500ms (94%)**, còn `llm-generation` 151ms như bình thường. Retrieval vẫn trả `doc_count=1`, level DEFAULT, nên nó chậm chứ không lỗi.
- **Root cause:** bước retrieval (vector store / `app/mock_rag.retrieve`) bị chậm thêm cố định ~2.5s mỗi request trong khoảng incident (incident `rag_slow` được bật bởi challenge), làm latency end-to-end vượt ngưỡng 2000ms. Ba tín hiệu cùng chỉ về một nguyên nhân: metric latency tăng mà TTFT không đổi → log có `latency_ms≈2653` với `tool_success=true` → trace cùng `correlation_id` có span `retrieval` 2.5s.
- **Fix action:** tắt nguồn gây chậm của retrieval (`python scripts/inject_incident.py --disable`, tương đương khôi phục vector store/cấu hình retrieval), rồi chạy lại đúng workload challenge. Kiểm chứng: lượt đầu sau fix P50 153ms nhưng 1 request 2,151ms (`req-c182f4a0`, trace `31243c1948fc24f3bce460d47441f839`: retrieval 0ms, generation 152ms, khoảng trống 2,000ms là lúc fetch prompt từ Langfuse sau khi cache 60s hết hạn, không phải incident). Lượt thứ hai (cache ấm): P50 153ms, P95 154ms, max 154ms (`req-e11da203`), tức đã hồi phục.
- **Preventive measure:**
  1. **Alert theo đúng triệu chứng:** thêm ngưỡng latency 2000ms cho feature `monitoring` (hoặc hạ SLO latency xuống 2000ms), vì alert `HighLatencyP95` hiện ở 3000ms đã bỏ lọt incident này.
  2. **Đo retrieval trực tiếp trong metrics:** ghi `retrieval_ms` vào log `response_sent` và thêm alert "retrieval P95 > 1000ms trong 5m", để dashboard chỉ ra retrieval mà không cần mở trace.
  3. **Timeout và fallback cho retrieval:** đặt timeout (ví dụ 1s) quanh `retrieve()`; quá hạn thì trả lời bằng fallback và đánh dấu `tool_success=false`, để một vector store chậm không kéo cả request.
  4. **Không chặn event loop:** `/chat` là `async` nhưng gọi `agent.run` đồng bộ, nên với concurrency 5 client phải chờ 13.3s dù server ghi 2.65s (các request xếp hàng). Chạy agent trong threadpool và ghi latency end-to-end ở middleware (`x-response-time-ms`) vào log.
  5. **Bỏ fetch prompt khỏi đường xử lý request:** refresh prompt cache ở background hoặc warm-up khi khởi động, vì fetch đồng bộ đã gây request 2.1s sau fix và request 735s trước CP2.

> Gợi ý cách viết ngắn, không thay cho evidence thực tế: "Metric cho thấy `[latency/error/cost/quality]` bất thường trong `[khoảng thời gian]`. Log line `[event]` có `correlation_id=[...]` đại diện cho request bị ảnh hưởng. Trace cùng `correlation_id` cho thấy span `[retrieval/generation/prompt/tool]` có dấu hiệu `[chậm/lỗi/token tăng]`. Root cause là `[nguyên nhân suy ra từ evidence]`. Fix action là `[hành động khôi phục]`; preventive measure là `[alert/runbook/test/guardrail để ngăn tái diễn]`."

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** đặt PII scrubbing thành một structlog processor (`scrub_event`) chạy **trước** `JsonlFileProcessor`, scrub đệ quy mọi field thay vì chỉ `payload`. Lý do: bất kỳ field nào do người dùng nhập (kể cả `session_id` hay chi tiết lỗi) đều có thể chứa PII, và một khi đã ghi xuống file thì không thu hồi được. Ngoại lệ là các field do hệ thống sinh (`ts`, `level`, `correlation_id`, `user_id_hash`), vì hash 12 ký tự hex có thể toàn chữ số và bị regex CCCD che nhầm. Cùng nguyên tắc cho trace: generation chỉ gửi preview đã scrub lên Langfuse.
- **Một lỗi/blocker đã gặp:** lần load test đầu của CP2 (concurrency 5) có 5 request timeout, các request còn lại 7–17s, một request ghi `latency_ms=735713`, và log server báo "Failed to export spans batch due to timeout". Ngoài ra, trace của request baseline đầu tiên bị mất.
- **Cách tìm nguyên nhân và xử lý:** đo kết nối bằng `curl` tới cloud.langfuse.com (một lần 8.7s, các lần sau <1s → mạng chập chờn). Đọc log uvicorn thấy "Prompt 'day13-chat-label:production' not found": app fetch prompt từ Langfuse trên đường xử lý request, prompt chưa tồn tại nên mỗi request mất ~6.2s rồi fallback. Xử lý: tạo prompt v1/v2 để cache hoạt động, latency về ~160ms. Trace bị mất là do dừng server bằng `taskkill /F` trước khi SDK kịp flush batch span, nên tôi thêm bước chờ ~8s trước khi restart và kiểm tra lại trace qua API trước khi ghi trace ID vào report.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics trả lời *có vấn đề không và khi nào* (P50 153ms → 2653ms lúc 05:01:41Z, TTFT không đổi nên loại trừ LLM). Logs trả lời *request nào* (lọc `response_sent` có `latency_ms > 2000` → `req-c1b49090`). Traces trả lời *bước nào bên trong* (trace cùng `correlation_id` cho thấy `retrieval` chiếm 2.5s/2.65s). `correlation_id` là khóa nối log với trace; thiếu nó thì phải đoán theo thời gian.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt là "code" thay đổi hành vi mà không qua deploy, nên mỗi trace phải ghi `prompt_name/version/label` để biết regression đến từ version nào. Label `production` cho phép promote/rollback trong vài giây mà không sửa code. Token/cost theo từng generation cho biết prompt mới có làm câu trả lời dài hoặc đắt hơn không. SLO và error budget quyết định khi nào phải dừng thay đổi để ưu tiên ổn định: ví dụ 11 request chậm trước CP2 đã chiếm 21.6% số request trong lab, vượt xa budget 0.5%.
- **Điều quan trọng nhất đã học:** không đoán root cause, đi theo evidence. Trong incident, retrieval vẫn `tool_success=true` và không có lỗi nào; chỉ khi ghép metric (TTFT không đổi) với trace (span retrieval 2.5s) mới thấy vấn đề là *chậm* chứ không phải *hỏng*. Ngoài ra, phụ thuộc bên ngoài nằm trên đường request (fetch prompt) có thể tiêu hết error budget dù code của mình không lỗi.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** các preventive measure ở §7 (timeout retrieval, ghi `retrieval_ms`, chạy agent trong threadpool, refresh prompt ở background) mới là đề xuất, chưa implement. Alert `HighLatencyP95` ở 3000ms không bắt được incident 2.65s. Promote/rollback label làm bằng Langfuse SDK (`update_prompt`) thay vì click trên UI; ảnh evidence chụp từ UI. Latency ghi trong log là thời gian xử lý trong agent, chưa gồm thời gian xếp hàng khi event loop bị chặn (client thấy 13.3s trong incident).

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [x] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.

