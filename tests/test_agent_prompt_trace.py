from __future__ import annotations

from contextlib import contextmanager

from app import agent as agent_module


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingObservation:
    def __init__(self, kwargs: dict) -> None:
        self.kwargs = kwargs
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.span_updates: list[dict] = []
        self.observations: list[RecordingObservation] = []

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        observation = RecordingObservation(kwargs)
        self.observations.append(observation)
        yield observation

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)


def test_agent_records_prompt_version_with_v4_observation_api(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    propagated: list[dict] = []

    @contextmanager
    def record_attributes(**kwargs):
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(agent_module, "propagate_attributes", record_attributes)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
        correlation_id="req-12345678",
    )

    span_update = client.span_updates[0]
    assert span_update["metadata"] == {
        "doc_count": 1,
        "query_preview": "Explain traces",
        "prompt_name": "day13-chat",
        "prompt_label": "production",
        "prompt_version": "3",
        "prompt_source": "langfuse",
        "prompt_fetch_error": "",
    }
    assert span_update["version"] == "3"
    assert propagated[0]["metadata"]["correlation_id"] == "req-12345678"
    assert propagated[-1]["prompt"] is client.prompt

    retrieval, generation = client.observations
    assert retrieval.kwargs["name"] == "retrieval"
    assert retrieval.kwargs["as_type"] == "retriever"
    assert retrieval.updates[-1]["output"]["doc_count"] == 1

    assert generation.kwargs["as_type"] == "generation"
    assert generation.kwargs["model"] == agent.model
    assert generation.kwargs["prompt"] is client.prompt
    gen_update = generation.updates[-1]
    assert set(gen_update["usage_details"]) == {"input", "output"}
    assert gen_update["cost_details"]["total"] > 0

    root_metrics = client.span_updates[-1]["metadata"]
    assert root_metrics["correlation_id"] == "req-12345678"
    assert root_metrics["cost_usd"] == gen_update["cost_details"]["total"]
    assert root_metrics["tokens_in"] == gen_update["usage_details"]["input"]


def test_generation_does_not_send_raw_pii_to_langfuse(monkeypatch) -> None:
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Refund to student@vinuni.edu.vn, phone 0901234567",
        correlation_id="req-12345678",
    )

    sent = repr([(o.kwargs, o.updates) for o in client.observations]) + repr(client.span_updates)
    assert "student@vinuni.edu.vn" not in sent
    assert "0901234567" not in sent


def test_retrieval_failure_marks_observation_as_error(monkeypatch) -> None:
    import pytest

    from app.incidents import STATE

    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setitem(STATE, "tool_fail", True)

    with pytest.raises(RuntimeError):
        agent_module.LabAgent.run.__wrapped__(
            agent_module.LabAgent(),
            user_id="student-01",
            feature="qa",
            session_id="session-01",
            message="Explain traces",
            correlation_id="req-12345678",
        )

    retrieval = client.observations[0]
    assert retrieval.updates[-1]["level"] == "ERROR"
