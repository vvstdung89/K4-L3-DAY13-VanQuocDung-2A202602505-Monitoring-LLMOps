from __future__ import annotations

import os
import time
from dataclasses import dataclass

from . import metrics
from .mock_llm import FakeLLM, FakeResponse
from .mock_rag import retrieve
from .pii import hash_user_id, summarize_text
from .prompt_management import ResolvedPrompt, resolve_prompt
from .tracing import get_langfuse_client, observe, propagate_attributes, tracing_enabled


@dataclass
class AgentResult:
    answer: str
    latency_ms: int
    ttft_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float


class LabAgent:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.llm = FakeLLM(model=model)

    @observe(name="lab-agent-run", as_type="agent", capture_input=False, capture_output=False)
    def run(
        self,
        user_id: str,
        feature: str,
        session_id: str,
        message: str,
        correlation_id: str,
    ) -> AgentResult:
        langfuse_client = get_langfuse_client()
        with propagate_attributes(
            user_id=hash_user_id(user_id),
            session_id=session_id,
            tags=["lab", feature, self.model],
            trace_name="day13-agent-request",
            environment=os.getenv("APP_ENV", "dev"),
            metadata={
                "feature": feature,
                "model": self.model,
                "correlation_id": correlation_id,
            },
        ):
            started = time.perf_counter()
            docs = self._retrieve(langfuse_client, message)
            prompt = resolve_prompt(
                langfuse_client,
                feature=feature,
                docs=docs,
                message=message,
                enabled=tracing_enabled(),
            )
            langfuse_client.update_current_span(
                metadata={
                    "doc_count": len(docs),
                    "query_preview": summarize_text(message),
                    "prompt_name": prompt.name,
                    "prompt_label": prompt.label,
                    "prompt_version": prompt.version,
                    "prompt_source": prompt.source,
                    "prompt_fetch_error": prompt.fetch_error or "",
                },
                version=prompt.version,
            )
            with propagate_attributes(prompt=prompt.managed_prompt):
                response, cost_usd = self._generate(langfuse_client, prompt)
            quality_score = self._heuristic_quality(message, response.text, docs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            langfuse_client.update_current_span(
                metadata={
                    "correlation_id": correlation_id,
                    "tokens_in": response.usage.input_tokens,
                    "tokens_out": response.usage.output_tokens,
                    "cost_usd": cost_usd,
                    "latency_ms": latency_ms,
                    "ttft_ms": response.ttft_ms,
                    "quality_score": quality_score,
                },
            )

        metrics.record_request(
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            cost_usd=cost_usd,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            quality_score=quality_score,
        )

        return AgentResult(
            answer=response.text,
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            cost_usd=cost_usd,
            quality_score=quality_score,
        )

    def _retrieve(self, langfuse_client, message: str) -> list[str]:
        # Child observation cho retrieval; chỉ lưu preview đã scrub, không lưu query thô.
        with langfuse_client.start_as_current_observation(
            name="retrieval",
            as_type="retriever",
            input={"query_preview": summarize_text(message)},
        ) as retrieval:
            try:
                docs = retrieve(message)
            except Exception as exc:
                retrieval.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
                raise
            retrieval.update(
                output={"doc_count": len(docs), "doc_previews": [summarize_text(d, 60) for d in docs]},
            )
            return docs

    def _generate(self, langfuse_client, prompt: ResolvedPrompt) -> tuple[FakeResponse, float]:
        # Child observation loại generation: model, prompt link, usage và cost.
        # Input/output chỉ là preview đã scrub để không đưa PII lên Langfuse.
        with langfuse_client.start_as_current_observation(
            name="llm-generation",
            as_type="generation",
            model=self.model,
            input=summarize_text(prompt.text, 200),
            prompt=prompt.managed_prompt,
            metadata={"prompt_version": prompt.version, "prompt_label": prompt.label},
        ) as generation:
            response = self.llm.generate(prompt.text)
            tokens_in = response.usage.input_tokens
            tokens_out = response.usage.output_tokens
            input_cost, output_cost = self._cost_parts(tokens_in, tokens_out)
            cost_usd = round(input_cost + output_cost, 6)
            generation.update(
                output=summarize_text(response.text, 200),
                usage_details={"input": tokens_in, "output": tokens_out},
                cost_details={"input": input_cost, "output": output_cost, "total": cost_usd},
                metadata={"ttft_ms": response.ttft_ms},
            )
            return response, cost_usd

    def _cost_parts(self, tokens_in: int, tokens_out: int) -> tuple[float, float]:
        return (tokens_in / 1_000_000) * 3, (tokens_out / 1_000_000) * 15

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        return round(sum(self._cost_parts(tokens_in, tokens_out)), 6)

    def _heuristic_quality(self, question: str, answer: str, docs: list[str]) -> float:
        score = 0.5
        if docs:
            score += 0.2
        if len(answer) > 40:
            score += 0.1
        if question.lower().split()[0:1] and any(token in answer.lower() for token in question.lower().split()[:3]):
            score += 0.1
        if "[REDACTED" in answer:
            score -= 0.2
        return round(max(0.0, min(1.0, score)), 2)
