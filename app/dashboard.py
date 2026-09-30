"""Dashboard runtime: 6 panel theo config/dashboard.yaml, dữ liệu từ data/logs.jsonl.

Mỗi lần mở /dashboard, trang tính lại từ log trong cửa sổ `time_range_minutes`
và tự refresh sau `refresh_seconds`. Không cần dependency ngoài (SVG inline).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

import yaml

from .metrics import percentile

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "dashboard.yaml"

COLORS = ["#2563eb", "#d97706", "#dc2626", "#059669"]
THRESHOLD_COLOR = "#dc2626"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["dashboard"]


def load_events(log_path: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    events = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            ts = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError):
            continue
        if start <= ts <= end:
            event["_ts"] = ts
            events.append(event)
    return events


def _minute_index(ts: datetime, start: datetime) -> int:
    return int((ts - start).total_seconds() // 60)


def compute_panels(events: list[dict[str, Any]], start: datetime, minutes: int) -> dict[str, dict]:
    """Tính giá trị cho 6 panel, cả tổng cửa sổ lẫn chuỗi theo phút."""
    received = [e for e in events if e.get("event") == "request_received"]
    sent = [e for e in events if e.get("event") == "response_sent"]
    failed = [e for e in events if e.get("event") == "request_failed"]

    def by_minute(items: list[dict]) -> list[list[dict]]:
        buckets: list[list[dict]] = [[] for _ in range(minutes)]
        for e in items:
            i = _minute_index(e["_ts"], start)
            if 0 <= i < minutes:
                buckets[i].append(e)
        return buckets

    sent_m, recv_m, fail_m = by_minute(sent), by_minute(received), by_minute(failed)

    def series(buckets: list[list[dict]], fn) -> list[float | None]:
        return [fn(b) if b else None for b in buckets]

    lat = [e["latency_ms"] for e in sent if e.get("latency_ms") is not None]
    ttft = [e["ttft_ms"] for e in sent if e.get("ttft_ms") is not None]
    tool = [e["tool_success"] for e in events if e.get("tool_success") is not None]
    costs = [e.get("cost_usd") or 0 for e in sent]
    cum, running = [], 0.0
    for b in sent_m:
        running += sum(e.get("cost_usd") or 0 for e in b)
        cum.append(round(running, 6))
    quality = [e["quality_score"] for e in sent if e.get("quality_score") is not None]

    def pct(values: list[int], p: int):
        return lambda b: percentile([e[values] for e in b if e.get(values) is not None], p)

    return {
        "latency": {
            "stats": {
                "p50": percentile(lat, 50), "p95": percentile(lat, 95),
                "p99": percentile(lat, 99), "ttft_p95": percentile(ttft, 95),
            },
            "series": {
                "P50": series(sent_m, pct("latency_ms", 50)),
                "P95": series(sent_m, pct("latency_ms", 95)),
                "P99": series(sent_m, pct("latency_ms", 99)),
                "TTFT P95": series(sent_m, pct("ttft_ms", 95)),
            },
        },
        "traffic": {
            "stats": {
                "count": len(received),
                "rate_per_minute": round(len(received) / minutes, 2),
                "peak_per_minute": max((len(b) for b in recv_m), default=0),
            },
            "series": {"requests/min": [len(b) for b in recv_m]},
            "bars": True,
        },
        "errors": {
            "stats": {
                "error_rate_pct": round(len(failed) / len(received) * 100, 2) if received else 0.0,
                "count_by_value": dict(Counter(e.get("error_type", "unknown") for e in failed)),
                "tool_success_rate_pct": round(sum(tool) / len(tool) * 100, 2) if tool else None,
            },
            "series": {
                "error rate %": [
                    round(len(f) / len(r) * 100, 2) if r else None for f, r in zip(fail_m, recv_m)
                ],
                "retrieval success %": series(
                    [[e for e in b if e.get("tool_success") is not None] for b in
                     (s + f for s, f in zip(sent_m, fail_m))],
                    lambda b: round(sum(e["tool_success"] for e in b) / len(b) * 100, 2),
                ),
            },
        },
        "cost": {
            "stats": {"total": round(sum(costs), 6), "avg_per_request": round(sum(costs) / len(costs), 6) if costs else 0},
            "series": {
                "cost/min": [round(sum(e.get("cost_usd") or 0 for e in b), 6) for b in sent_m],
                "cumulative": cum,
            },
        },
        "tokens": {
            "stats": {
                "tokens_in": sum(e.get("tokens_in") or 0 for e in sent),
                "tokens_out": sum(e.get("tokens_out") or 0 for e in sent),
            },
            "series": {
                "tokens_in/min": [sum(e.get("tokens_in") or 0 for e in b) for b in sent_m],
                "tokens_out/min": [sum(e.get("tokens_out") or 0 for e in b) for b in sent_m],
            },
        },
        "quality": {
            "stats": {"mean": round(sum(quality) / len(quality), 3) if quality else None},
            "series": {
                "mean quality": series(
                    sent_m, lambda b: round(sum(e.get("quality_score") or 0 for e in b) / len(b), 3)
                ),
            },
        },
    }


def threshold_status(panel: dict, stats: dict) -> tuple[Any, bool | None]:
    th = panel["threshold"]
    agg = th["aggregation"]
    value = stats.get(agg)
    if agg == "sum_by_field":
        value = max(stats.get("tokens_in", 0), stats.get("tokens_out", 0))
    if value is None:
        return None, None
    ok = value <= th["value"] if th["operator"] == "lte" else value >= th["value"]
    return value, ok


def _svg_chart(series: dict[str, list], start: datetime, minutes: int, threshold: float | None,
               unit: str, bars: bool = False, width: int = 560, height: int = 210) -> str:
    left, right, top, bottom = 58, 12, 12, 34
    pw, ph = width - left - right, height - top - bottom
    values = [v for s in series.values() for v in s if v is not None]
    ymax = max(values + ([threshold] if threshold is not None else []) + [1e-9])
    ymax *= 1.15

    def x(i: float) -> float:
        return left + pw * (i + 0.5) / minutes

    def y(v: float) -> float:
        return top + ph - ph * v / ymax

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    for k in range(5):  # grid + nhãn trục y
        v = ymax * k / 4
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>')
        label = f"{v:.4f}" if ymax < 0.1 else (f"{v:.2f}" if ymax < 10 else f"{v:,.0f}")
        parts.append(f'<text x="{left - 6}" y="{y(v) + 4:.1f}" class="axis" text-anchor="end">{label}</text>')
    for m in range(0, minutes + 1, 10):  # nhãn trục x mỗi 10 phút, giờ local
        t = (start + timedelta(minutes=m)).astimezone().strftime("%H:%M")
        parts.append(f'<text x="{left + pw * m / minutes:.1f}" y="{height - 12}" class="axis" text-anchor="middle">{t}</text>')
    for idx, (name, s) in enumerate(series.items()):
        color = COLORS[idx % len(COLORS)]
        if bars and idx == 0:
            bw = pw / minutes * 0.7
            for i, v in enumerate(s):
                if v:
                    parts.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{y(0) - y(v):.1f}" fill="{color}" opacity="0.8"/>')
            continue
        pts = [(x(i), y(v)) for i, v in enumerate(s) if v is not None]
        if len(pts) > 1:
            parts.append('<polyline fill="none" stroke="{}" stroke-width="2" points="{}"/>'.format(
                color, " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)))
        for a, b in pts:
            parts.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="3" fill="{color}"/>')
    if threshold is not None:
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(threshold):.1f}" y2="{y(threshold):.1f}" stroke="{THRESHOLD_COLOR}" stroke-dasharray="6 4" stroke-width="1.5"/>')
        parts.append(f'<text x="{width - right - 4}" y="{y(threshold) - 5:.1f}" class="thr" text-anchor="end">threshold {threshold:g} {escape(unit)}</text>')
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{COLORS[i % len(COLORS)]}"></i>{escape(n)}</span>'
        for i, n in enumerate(series)
    )
    return "".join(parts) + f'<div class="legend">{legend}<span><i class="dash"></i>threshold</span></div>'


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.6f}".rstrip("0").rstrip(".") if abs(v) < 1 else f"{v:,.2f}"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {n}" for k, n in v.items()) or "none"
    return "n/a" if v is None else f"{v:,}" if isinstance(v, int) else escape(str(v))


def render_dashboard(log_path: Path, now: datetime | None = None, config: dict | None = None,
                     minutes: int | None = None) -> str:
    config = config or load_config()
    # Mặc định dùng time range của contract; `minutes` chỉ để zoom vào một khoảng ngắn hơn.
    default_minutes = config["time_range_minutes"]
    minutes = max(1, min(minutes or default_minutes, default_minutes))
    end = (now or datetime.now(timezone.utc)).replace(second=59, microsecond=999999)
    start = end.replace(second=0, microsecond=0) - timedelta(minutes=minutes - 1)
    data = compute_panels(load_events(log_path, start, end), start, minutes)

    cards = []
    for panel in config["panels"]:
        pid, th = panel["id"], panel["threshold"]
        d = data[pid]
        value, ok = threshold_status(panel, d["stats"])
        badge = ("ok", "OK") if ok else ("bad", "BREACH") if ok is False else ("na", "NO DATA")
        op = "≤" if th["operator"] == "lte" else "≥"
        # Threshold của latency/traffic/errors/quality so trên từng phút -> vẽ line.
        # Cost/tokens là ngân sách cho cả cửa sổ -> vẽ thanh mức dùng so với threshold.
        line_th = th["value"] if pid in {"latency", "traffic", "errors", "quality"} else None
        budget = ""
        if line_th is None and value is not None:
            used = min(value / th["value"] * 100, 100)
            budget = (f'<div class="budget"><div style="width:{used:.1f}%"></div></div>'
                      f'<p class="meta">{escape(th["aggregation"])} = {_fmt(value)} / threshold {th["value"]:g} '
                      f'{escape(panel["unit"])} ({value / th["value"] * 100:.2f}% used)</p>')
        stats = "".join(f"<div><b>{escape(k)}</b><span>{_fmt(v)}</span></div>" for k, v in d["stats"].items())
        cards.append(f"""
<section class="card">
  <header><h2>{escape(panel['title'])}</h2><span class="badge {badge[0]}">{badge[1]}</span></header>
  <p class="meta">unit: <b>{escape(panel['unit'])}</b> · threshold: <b>{escape(th['aggregation'])} {op} {th['value']:g}</b>
     · current: <b>{_fmt(value)}</b></p>
  <div class="stats">{stats}</div>
  {budget}
  {_svg_chart(d['series'], start, minutes, line_th, panel['unit'], bars=d.get('bars', False))}
  <p class="query"><code>{escape(panel['query'])}</code></p>
</section>""")

    local = lambda t: t.astimezone().strftime("%Y-%m-%d %H:%M")  # noqa: E731
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="{config['refresh_seconds']}">
<title>{escape(config['title'])}</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6fa;color:#111827}}
 .top{{padding:14px 22px;background:#111827;color:#fff;display:flex;justify-content:space-between;align-items:center}}
 .top h1{{font-size:20px;margin:0}} .top div{{font-size:14px;opacity:.9}}
 .grid6{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;padding:14px}}
 .card{{background:#fff;border-radius:10px;padding:12px 14px;box-shadow:0 1px 3px #0002}}
 .card header{{display:flex;justify-content:space-between;align-items:center}}
 h2{{font-size:16px;margin:0}} .meta{{font-size:12px;color:#4b5563;margin:4px 0 6px}}
 .badge{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px}}
 .ok{{background:#d1fae5;color:#065f46}} .bad{{background:#fee2e2;color:#991b1b}} .na{{background:#e5e7eb;color:#374151}}
 .stats{{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;margin-bottom:4px}}
 .stats div{{display:flex;gap:5px}} .stats span{{font-family:Consolas,monospace}}
 .chart{{width:100%;height:auto}} .grid{{stroke:#e5e7eb}} .axis{{font-size:10px;fill:#6b7280}}
 .thr{{font-size:10px;fill:{THRESHOLD_COLOR}}}
 .legend{{font-size:11px;display:flex;gap:12px;flex-wrap:wrap;color:#374151}}
 .legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}}
 .legend i.dash{{background:none;border-top:2px dashed {THRESHOLD_COLOR};height:0;width:14px;vertical-align:3px}}
 .budget{{height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden}}
 .budget div{{height:100%;background:#059669}}
 .query{{font-size:10px;color:#6b7280;margin:6px 0 0}}
</style></head><body>
<div class="top"><h1>{escape(config['title'])}</h1>
<div>Time range: last {minutes} min{"" if minutes == default_minutes else f" (zoom; default {default_minutes} min)"} ({local(start)} → {local(end)}) · auto-refresh {config['refresh_seconds']}s · source: <code>{escape(str(log_path.as_posix()))}</code></div></div>
<main class="grid6">{''.join(cards)}</main>
</body></html>"""
