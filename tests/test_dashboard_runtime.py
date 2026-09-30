from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.dashboard import compute_panels, load_config, render_dashboard, threshold_status

NOW = datetime(2026, 9, 30, 10, 0, 30, tzinfo=timezone.utc)


def _write_logs(path: Path) -> None:
    ts = lambda s: (NOW - timedelta(seconds=s)).isoformat().replace("+00:00", "Z")  # noqa: E731
    rows = []
    for i, latency in enumerate([100, 200, 300, 4000]):
        rows.append({"event": "request_received", "ts": ts(60 + i)})
        rows.append({"event": "response_sent", "ts": ts(59 + i), "latency_ms": latency, "ttft_ms": 50,
                     "tokens_in": 10, "tokens_out": 20, "cost_usd": 0.01, "quality_score": 0.8,
                     "tool_success": True})
    rows.append({"event": "request_received", "ts": ts(30)})
    rows.append({"event": "request_failed", "ts": ts(29), "error_type": "RuntimeError", "tool_success": False})
    rows.append({"event": "response_sent", "ts": ts(7200), "latency_ms": 99999})  # ngoài cửa sổ 60 phút
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot-json\n", encoding="utf-8")


def test_compute_panels_matches_contract_aggregations(tmp_path: Path) -> None:
    log = tmp_path / "logs.jsonl"
    _write_logs(log)
    from app.dashboard import load_events

    start = NOW.replace(second=0) - timedelta(minutes=59)
    data = compute_panels(load_events(log, start, NOW), start, 60)

    assert data["latency"]["stats"] == {"p50": 200.0, "p95": 4000.0, "p99": 4000.0, "ttft_p95": 50.0}
    assert data["traffic"]["stats"]["count"] == 5
    assert data["errors"]["stats"]["error_rate_pct"] == 20.0
    assert data["errors"]["stats"]["count_by_value"] == {"RuntimeError": 1}
    assert data["errors"]["stats"]["tool_success_rate_pct"] == 80.0
    assert data["cost"]["stats"]["total"] == 0.04
    assert data["tokens"]["stats"] == {"tokens_in": 40, "tokens_out": 80}
    assert data["quality"]["stats"]["mean"] == 0.8


def test_threshold_status_uses_contract_operator() -> None:
    panels = {p["id"]: p for p in load_config()["panels"]}
    assert threshold_status(panels["latency"], {"p95": 4000.0}) == (4000.0, False)
    assert threshold_status(panels["quality"], {"mean": 0.8}) == (0.8, True)
    assert threshold_status(panels["tokens"], {"tokens_in": 10, "tokens_out": 60000}) == (60000, False)


def test_render_dashboard_has_six_panels_time_range_and_units(tmp_path: Path) -> None:
    log = tmp_path / "logs.jsonl"
    _write_logs(log)
    html = render_dashboard(log, now=NOW)
    config = load_config()
    for panel in config["panels"]:
        assert panel["title"] in html
        assert f"unit: <b>{panel['unit']}</b>" in html
    assert html.count('<section class="card">') == 6
    assert f'content="{config["refresh_seconds"]}"' in html
    assert "last 60 min" in html
    assert "BREACH" in html  # p95 4000ms > 3000ms
