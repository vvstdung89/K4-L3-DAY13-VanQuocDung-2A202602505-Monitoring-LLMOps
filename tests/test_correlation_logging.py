from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.logging_config import scrub_event
from app.main import app
from app.pii import hash_user_id


def _post(headers: dict[str, str] | None = None, message: str = "Explain observability") -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/chat",
                headers=headers or {},
                json={"user_id": "student-01", "session_id": "session-01", "feature": "qa", "message": message},
            )

    return asyncio.run(send())


def _events(log_path: Path) -> list[dict]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_generates_correlation_id_and_headers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")
    response = _post()

    cid = response.headers["x-request-id"]
    assert re.fullmatch(r"req-[0-9a-f]{8}", cid)
    assert float(response.headers["x-response-time-ms"]) >= 0
    assert response.json()["correlation_id"] == cid


def test_reuses_incoming_request_id_and_rejects_unsafe(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")
    assert _post({"x-request-id": "req-abc12345"}).headers["x-request-id"] == "req-abc12345"

    unsafe = _post({"x-request-id": "bad id\ninjected"}).headers["x-request-id"]
    assert re.fullmatch(r"req-[0-9a-f]{8}", unsafe)


def test_logs_are_enriched_and_not_leaked_between_requests(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    first = _post().headers["x-request-id"]
    second = _post().headers["x-request-id"]
    assert first != second

    api_events = [e for e in _events(log_path) if e.get("service") == "api"]
    assert {e["correlation_id"] for e in api_events} == {first, second}
    for event in api_events:
        assert event["user_id_hash"] == hash_user_id("student-01")
        assert event["session_id"] == "session-01"
        assert event["feature"] == "qa"
        assert event["model"]
        assert event["env"]
        assert "student-01" not in json.dumps(event)


def test_pii_is_scrubbed_before_writing_log(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    _post(message="My email is student@vinuni.edu.vn, phone 0901234567")

    raw = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw
    assert "0901234567" not in raw
    assert "REDACTED_EMAIL" in raw


def test_scrub_event_handles_nested_values_and_keeps_trusted_fields() -> None:
    event = {
        "event": "x",
        "user_id_hash": "123456789012",
        "session_id": "a@b.com",
        "payload": {"items": ["0901234567"], "inner": {"card": "4111 1111 1111 1111"}},
    }
    out = scrub_event(None, "info", event)
    assert out["user_id_hash"] == "123456789012"
    assert "a@b.com" not in json.dumps(out)
    assert "0901234567" not in json.dumps(out)
    assert "4111 1111 1111 1111" not in json.dumps(out)
