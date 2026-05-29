from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path("logs/2026-05")
LOG_DIRS = [ROOT / "2026-05-13", ROOT / "2026-05-14"]
OUT = Path("docs/2026-05-14_since_2100_entry_drought_root_cause_for_claude.md")

UTC = timezone.utc
BJ = timezone(timedelta(hours=8))
START_UTC = datetime(2026, 5, 13, 13, 0, tzinfo=UTC)
UPDATE_UTC = datetime(2026, 5, 13, 18, 55, tzinfo=UTC)


def parse_iso(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).astimezone(UTC)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def parse_utc_space(raw: str) -> datetime | None:
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def bj(ts: datetime | None) -> str:
    if not ts:
        return "-"
    return ts.astimezone(BJ).strftime("%Y-%m-%d %H:%M")


def utc_s(ts: datetime | None) -> str:
    if not ts:
        return "-"
    return ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def all_runtime_files() -> list[Path]:
    files: list[Path] = []
    for d in LOG_DIRS:
        files.extend(sorted(d.glob("runtime.out.*.log")))
    return files


def all_attribution_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for d in LOG_DIRS:
        rows.extend(read_jsonl(d / "fund_flow_attribution.jsonl"))
    return rows


def all_api_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for d in LOG_DIRS:
        rows.extend(read_jsonl(d / "api_cycle_stats_utc.jsonl"))
    return rows


def all_fills() -> list[dict[str, Any]]:
    fills: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for d in LOG_DIRS:
        path = d / "trade_fills_utc.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                ts = parse_utc_space(row.get("时间(UTC)", ""))
                if not ts:
                    continue
                key = (
                    row.get("时间(UTC)", ""),
                    row.get("合约", ""),
                    row.get("方向", ""),
                    row.get("成交ID", ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                row["_ts"] = ts
                fills.append(row)
    return sorted(fills, key=lambda r: r["_ts"])


def decision_ts(row: dict[str, Any]) -> datetime | None:
    return parse_iso(str(row.get("ts") or row.get("timestamp") or ""))


def extract_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in text.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def parse_score_line(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {"raw": text}
    m = re.search(r"stage=([^,]+)", text)
    if m:
        data["stage"] = m.group(1).strip()
    m = re.search(r"primary=4H:([0-9.\-]+)\(([^)]*)\)", text)
    if m:
        data["score_4h"] = float(m.group(1))
        data["signal_4h"] = m.group(2)
    m = re.search(r"1H=([0-9.\-]+)\(([^)]*)\)", text)
    if m:
        data["score_1h"] = float(m.group(1))
        data["signal_1h"] = m.group(2)
    m = re.search(r"VWAP(?:q|)=([0-9.\-]+).*?dev=([+\-0-9.]+)%", text)
    if m:
        data["vwap_score"] = float(m.group(1))
        data["vwap_dev_pct"] = float(m.group(2))
    m = re.search(r"15M=([0-9.\-]+)\(([^)]*)\)", text)
    if m:
        data["score_15m"] = float(m.group(1))
        data["entry_15m"] = m.group(2)
    m = re.search(r"VOL=([0-9.\-]+)\(r=([0-9.\-]+)\)", text)
    if m:
        data["volume_score"] = float(m.group(1))
        data["volume_ratio"] = float(m.group(2))
    m = re.search(r"total=([0-9.\-]+)/([0-9.\-]+)", text)
    if m:
        data["total"] = float(m.group(1))
        data["threshold"] = float(m.group(2))
    m = re.search(r"veto=([^,]+)$", text)
    if m:
        data["veto"] = m.group(1).strip()
    return data


def parse_runtime() -> dict[str, Any]:
    cycle_re = re.compile(r"^=== FUND_FLOW cycle .* @ (?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC")
    symbol_re = re.compile(r"^\[(?P<symbol>[A-Z0-9]+USDT)\] 决策=(?P<decision>\w+) .*?目标占比=(?P<target>[0-9.]+).*?当前占比=(?P<current>[0-9.]+).*?杠杆\(请求/实际\)=(?P<req>\d+)x/(?P<actual>\d+)x")
    engine_re = re.compile(r"引擎上下文: .*adx=(?P<adx>[0-9.\-]+), atr_pct=(?P<atr>[0-9.\-]+)")
    score_re = re.compile(r"MACD_V2评分: (?P<text>.*)")
    hold_re = re.compile(r"HOLD归因: (?P<text>.*)")
    reason_re = re.compile(r"决策原因: (?P<text>.*)")
    gate_re = re.compile(r"ENTRY_GATE_BLOCK (?P<json>\{.*\})")
    exit_re = re.compile(r"\[ExitGuard\] (?P<symbol>[A-Z0-9]+USDT) (?P<action>\w+): (?P<reason>.*)")
    error_re = re.compile(r"执行失败详情: (?P<text>.*)")
    scan_re = re.compile(r"本轮扫描完成: (?P<text>.*)")
    runtime_config_hits = Counter()

    entries: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    exit_guard: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    scans: list[dict[str, Any]] = []
    current_ts: datetime | None = None
    current: dict[str, Any] | None = None

    for path in all_runtime_files():
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line_no, raw in enumerate(fh, start=1):
                line = raw.rstrip("\n")
                m = cycle_re.match(line)
                if m:
                    current_ts = parse_utc_space(m.group("ts"))
                    current = None
                    continue
                if "shadow_mode" in line:
                    if "shadow_mode\":true" in line or "shadow_mode=True" in line:
                        runtime_config_hits["shadow_mode_true"] += 1
                    if "shadow_mode\":false" in line or "shadow_mode=False" in line:
                        runtime_config_hits["shadow_mode_false"] += 1
                if "vwap_gate_action" in line:
                    runtime_config_hits["vwap_gate_action"] += 1
                if "probe_min_open" in line:
                    runtime_config_hits["probe_min_open"] += 1

                m = symbol_re.match(line)
                if m and current_ts:
                    current = {
                        "ts": current_ts,
                        "symbol": m.group("symbol"),
                        "decision": m.group("decision"),
                        "target": float(m.group("target")),
                        "current": float(m.group("current")),
                        "req_leverage": int(m.group("req")),
                        "actual_leverage": int(m.group("actual")),
                        "file": str(path),
                        "line": line_no,
                    }
                    entries.append(current)
                    continue
                m = engine_re.search(line)
                if m and current is not None:
                    current["adx"] = float(m.group("adx"))
                    current["atr_pct"] = float(m.group("atr"))
                    continue
                m = score_re.search(line)
                if m and current is not None:
                    current.update(parse_score_line(m.group("text")))
                    continue
                m = hold_re.search(line)
                if m and current is not None:
                    current["hold_text"] = m.group("text")
                    kv = extract_kv(m.group("text"))
                    current["hold_stage"] = kv.get("stage")
                    current["hold_reason"] = kv.get("reason")
                    current["hold_code"] = kv.get("code")
                    current["reject_code"] = kv.get("code")
                    continue
                m = reason_re.search(line)
                if m and current is not None:
                    current["decision_reason"] = m.group("text")
                    continue
                m = gate_re.search(line)
                if m and current_ts:
                    try:
                        payload = json.loads(m.group("json"))
                    except json.JSONDecodeError:
                        continue
                    payload["ts"] = current_ts
                    payload["file"] = str(path)
                    payload["line"] = line_no
                    gates.append(payload)
                    continue
                m = exit_re.search(line)
                if m and current_ts:
                    exit_guard.append(
                        {
                            "ts": current_ts,
                            "symbol": m.group("symbol"),
                            "action": m.group("action"),
                            "reason": m.group("reason"),
                            "file": str(path),
                            "line": line_no,
                        }
                    )
                    continue
                m = error_re.search(line)
                if m and current_ts:
                    errors.append({"ts": current_ts, "text": m.group("text"), "file": str(path), "line": line_no})
                    continue
                m = scan_re.search(line)
                if m and current_ts:
                    scans.append({"ts": current_ts, "text": m.group("text")})

    return {
        "entries": entries,
        "gates": gates,
        "exit_guard": exit_guard,
        "errors": errors,
        "scans": scans,
        "runtime_config_hits": runtime_config_hits,
    }


def slice_rows(rows: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    return [r for r in rows if start <= r.get("ts", datetime.min.replace(tzinfo=UTC)) <= end]


def summarize_runtime(entries: list[dict[str, Any]], gates: list[dict[str, Any]]) -> dict[str, Any]:
    op = Counter(str(e.get("decision", "")).upper() for e in entries)
    hold_entries = [e for e in entries if str(e.get("decision", "")).upper() == "HOLD"]
    hold_code = Counter(str(e.get("hold_code") or e.get("hold_reason") or "-") for e in hold_entries)
    stage = Counter(str(e.get("hold_stage") or e.get("stage") or "-") for e in hold_entries)
    score_stage = Counter(str(e.get("stage") or "-") for e in hold_entries)
    gate = Counter(str(g.get("gate") or "-") for g in gates)
    gate_reason = Counter(str(g.get("reason") or "-") for g in gates)
    min_open = [g for g in gates if g.get("gate") == "min_open_portion"]
    same_side = [g for g in gates if g.get("gate") == "same_side_add_guard"]
    shadow_true = [
        g for g in min_open
        if ((g.get("extra") or {}).get("probe_floor_rescue") or {}).get("shadow_mode") is True
    ]
    shadow_false = [
        g for g in min_open
        if ((g.get("extra") or {}).get("probe_floor_rescue") or {}).get("shadow_mode") is False
    ]
    final_like = [e for e in hold_entries if str(e.get("stage")) in {"final", "threshold_check", "score_aggregation"}]
    near_threshold = [
        e for e in hold_entries
        if isinstance(e.get("total"), float)
        and isinstance(e.get("threshold"), float)
        and 0 <= e["threshold"] - e["total"] <= 0.05
    ]
    return {
        "op": op,
        "hold_code": hold_code,
        "stage": stage,
        "score_stage": score_stage,
        "gate": gate,
        "gate_reason": gate_reason,
        "min_open": min_open,
        "same_side": same_side,
        "shadow_true": shadow_true,
        "shadow_false": shadow_false,
        "final_like": final_like,
        "near_threshold": near_threshold,
    }


def summarize_attribution(rows: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    selected = []
    executions = []
    decisions = []
    for row in rows:
        ts = decision_ts(row)
        if not ts or not (start <= ts <= end):
            continue
        event = row.get("event")
        if event == "decision":
            dec = row.get("decision") or {}
            selected.append(row)
            decisions.append(row)
        elif event == "execution":
            executions.append(row)
    op = Counter(str((r.get("decision") or {}).get("operation", "-")).lower() for r in decisions)
    exec_status = Counter(str((r.get("result") or {}).get("status", "-")).lower() for r in executions)
    non_hold = []
    for r in decisions:
        dec = r.get("decision") or {}
        op_name = str(dec.get("operation", "")).lower()
        if op_name != "hold":
            non_hold.append(
                {
                    "ts": decision_ts(r),
                    "symbol": dec.get("symbol"),
                    "op": op_name,
                    "target": dec.get("target_portion_of_balance"),
                    "lev": dec.get("leverage"),
                    "reason": dec.get("reason"),
                    "status": None,
                }
            )
    return {"decisions": decisions, "executions": executions, "op": op, "exec_status": exec_status, "non_hold": non_hold}


def summarize_api(rows: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    selected = []
    for row in rows:
        ts = parse_utc_space(str(row.get("timestamp_utc") or ""))
        if ts and start <= ts <= end:
            selected.append(row)
    modes = Counter(str(r.get("scan_mode") or r.get("mode") or "-") for r in selected)
    allow = sum(1 for r in selected if r.get("allow_new_entries") is True)
    ingestion = sum(1 for r in selected if r.get("ingestion_only") is True)
    processed = Counter(str(r.get("processed")) + "/" + str(r.get("total_symbols")) for r in selected)
    return {"rows": selected, "modes": modes, "allow": allow, "ingestion": ingestion, "processed": processed}


def summarize_fills(rows: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    return [r for r in rows if start <= r["_ts"] <= end]


def top_table(counter: Counter, n: int = 10) -> str:
    if not counter:
        return "| 项 | 次数 |\n|---|---:|\n"
    lines = ["| 项 | 次数 |", "|---|---:|"]
    for k, v in counter.most_common(n):
        lines.append(f"| `{k}` | {v} |")
    return "\n".join(lines) + "\n"


def gate_table(gates: list[dict[str, Any]], n: int = 12) -> str:
    lines = ["| UTC | 北京时间 | Symbol | gate | reason | value | score | shadow | line |", "|---|---|---|---|---|---:|---:|---|---:|"]
    for g in gates[:n]:
        extra = g.get("extra") or {}
        rescue = extra.get("probe_floor_rescue") or {}
        lines.append(
            f"| {utc_s(g.get('ts'))} | {bj(g.get('ts'))} | `{g.get('symbol')}` | `{g.get('gate')}` | "
            f"`{g.get('reason')}` | {float(g.get('value') or 0):.4f} | {float(g.get('signal_score') or 0):.4f} | "
            f"`{rescue.get('shadow_mode', '-')}` | {g.get('line')} |"
        )
    return "\n".join(lines) + "\n"


def non_hold_table(rows: list[dict[str, Any]], n: int = 20) -> str:
    lines = ["| UTC | 北京时间 | Symbol | op | target | lev | reason |", "|---|---|---|---|---:|---:|---|"]
    for r in rows[:n]:
        lines.append(
            f"| {utc_s(r.get('ts'))} | {bj(r.get('ts'))} | `{r.get('symbol')}` | `{r.get('op')}` | "
            f"{float(r.get('target') or 0):.4f} | {r.get('lev')} | `{r.get('reason')}` |"
        )
    return "\n".join(lines) + "\n"


def fill_table(rows: list[dict[str, Any]], n: int = 20) -> str:
    lines = ["| UTC | 北京时间 | Symbol | 方向 | 价格 | 数量 | PnL |", "|---|---|---|---|---:|---:|---:|"]
    for r in rows[:n]:
        lines.append(
            f"| {utc_s(r['_ts'])} | {bj(r['_ts'])} | `{r.get('合约')}` | {r.get('方向')} | "
            f"{r.get('价格')} | {r.get('数量')} | {r.get('已实现盈亏')} |"
        )
    return "\n".join(lines) + "\n"


def sample_hold(entries: list[dict[str, Any]], code: str, n: int = 5) -> str:
    rows = [e for e in entries if str(e.get("hold_code") or e.get("hold_reason")) == code]
    lines = ["| UTC | 北京时间 | Symbol | stage | 4H | 1H | total/th | vwap_dev | atr_pct | entry_15m |", "|---|---|---|---|---|---|---:|---:|---:|---|"]
    for e in rows[:n]:
        total = e.get("total")
        th = e.get("threshold")
        lines.append(
            f"| {utc_s(e.get('ts'))} | {bj(e.get('ts'))} | `{e.get('symbol')}` | `{e.get('stage')}` | "
            f"`{e.get('signal_4h')}` | `{e.get('signal_1h')}` | "
            f"{float(total or 0):.4f}/{float(th or 0):.4f} | {float(e.get('vwap_dev_pct') or 0):.2f}% | "
            f"{float(e.get('atr_pct') or 0):.4f} | `{e.get('entry_15m')}` |"
        )
    return "\n".join(lines) + "\n"


def build_report() -> str:
    runtime = parse_runtime()
    attr_rows = all_attribution_rows()
    api_rows = all_api_rows()
    fills = all_fills()
    runtime_entries = runtime["entries"]
    latest_ts = max([e["ts"] for e in runtime_entries] + [START_UTC])
    latest4_start = latest_ts - timedelta(hours=4)
    windows = [
        ("昨晚 21:00 后全窗口", START_UTC, latest_ts),
        ("02:55 更新后", UPDATE_UTC, latest_ts),
        ("最新 4H", latest4_start, latest_ts),
    ]

    lines: list[str] = []
    lines.append("# 2026-05-14 昨晚21点后开仓稀少根因复盘")
    lines.append("")
    lines.append(f"分析范围：北京时间 `2026-05-13 21:00` 至 `{bj(latest_ts)}`，UTC `{utc_s(START_UTC)}` 至 `{utc_s(latest_ts)}`。")
    lines.append(f"策略更新切点按用户描述取北京时间 `2026-05-14 02:55`，即 UTC `{utc_s(UPDATE_UTC)}`。")
    lines.append("")
    lines.append("## 核心结论")
    lines.append("")
    lines.append("这次开仓数量没有明显增加，关键不是单一阈值没降够，而是两个层面同时失败：")
    lines.append("")
    lines.append("1. **部署/运行态不一致持续存在**：昨晚 21:00 后仍出现 `probe_floor_rescue.shadow_mode=true` 的 `ENTRY_GATE_BLOCK`，说明至少到 UTC 15:45 / 北京时间 23:45，运行进程仍在用旧逻辑。")
    lines.append("2. **真正生效后的主瓶颈转移到方向门控和 VWAP hard block**：最新 4H 仍几乎全 HOLD，主要死在 `4H无明确方向` 与 `vwap_hard_block`，而不是 final threshold。")
    lines.append("3. **ExitGuard 不是多余优化，但执行层有新故障**：今天 12:00 BJ 左右 ExitGuard 触发 DOGE `CLOSE`，但 Binance 返回 `-2022 ReduceOnly Order is rejected`，说明退出信号守卫能触发，实际平仓路由仍需修。")
    lines.append("4. **继续堆策略参数会扩大屎山**：当前最该做的是先把配置加载、日志字段、执行路由、回测切片对齐，再决定是否放开 neutral/RSI/VWAP。")
    lines.append("")

    for name, start, end in windows:
        entries = slice_rows(runtime_entries, start, end)
        gates = slice_rows(runtime["gates"], start, end)
        exits = slice_rows(runtime["exit_guard"], start, end)
        errs = slice_rows(runtime["errors"], start, end)
        s = summarize_runtime(entries, gates)
        a = summarize_attribution(attr_rows, start, end)
        api = summarize_api(api_rows, start, end)
        f = summarize_fills(fills, start, end)
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"窗口：UTC `{utc_s(start)}` - `{utc_s(end)}`，北京时间 `{bj(start)}` - `{bj(end)}`。")
        lines.append("")
        lines.append("### 调度与决策")
        lines.append("")
        lines.append(f"- runtime 决策行：`{len(entries)}`")
        lines.append(f"- attribution decision：`{len(a['decisions'])}`，execution：`{len(a['executions'])}`")
        lines.append(f"- API cycles：`{len(api['rows'])}`，allow_new_entries=True：`{api['allow']}`，ingestion_only：`{api['ingestion']}`")
        if api["processed"]:
            lines.append(f"- 处理标的分布：`{', '.join(f'{k}={v}' for k, v in api['processed'].most_common(5))}`")
        lines.append("")
        lines.append("runtime 决策类型：")
        lines.append(top_table(s["op"], 8))
        lines.append("attribution 决策类型：")
        lines.append(top_table(a["op"], 8))
        lines.append("execution 状态：")
        lines.append(top_table(a["exec_status"], 8))
        lines.append("")
        lines.append("### HOLD 主因")
        lines.append("")
        lines.append("按 runtime `HOLD归因`：")
        lines.append(top_table(s["hold_code"], 12))
        lines.append("按 stage：")
        lines.append(top_table(s["stage"], 12))
        lines.append("")
        lines.append("### ENTRY_GATE_BLOCK")
        lines.append("")
        lines.append(f"- gate 总数：`{len(gates)}`")
        lines.append(f"- `min_open_portion`：`{len(s['min_open'])}`")
        lines.append(f"- `same_side_add_guard`：`{len(s['same_side'])}`")
        lines.append(f"- min_open 中 shadow_mode=true：`{len(s['shadow_true'])}`，shadow_mode=false：`{len(s['shadow_false'])}`")
        lines.append(top_table(s["gate"], 8))
        if gates:
            lines.append("代表样例：")
            lines.append(gate_table(gates[:12]))
        lines.append("")
        lines.append("### 非 HOLD 与成交")
        lines.append("")
        lines.append(f"- attribution 非 HOLD：`{len(a['non_hold'])}`")
        if a["non_hold"]:
            lines.append(non_hold_table(a["non_hold"]))
        lines.append(f"- fills 去重：`{len(f)}`")
        if f:
            lines.append(fill_table(f))
        lines.append("")
        lines.append("### ExitGuard / 执行错误")
        lines.append("")
        lines.append(f"- ExitGuard 触发：`{len(exits)}`")
        for e in exits[:10]:
            lines.append(f"  - `{utc_s(e['ts'])}` / `{bj(e['ts'])}` `{e['symbol']}` `{e['action']}`: {e['reason']}")
        lines.append(f"- 执行失败详情：`{len(errs)}`")
        for e in errs[:8]:
            lines.append(f"  - `{utc_s(e['ts'])}` / `{bj(e['ts'])}`: `{e['text']}`")
        lines.append("")

    latest_entries = slice_rows(runtime_entries, latest4_start, latest_ts)
    latest_gates = slice_rows(runtime["gates"], latest4_start, latest_ts)
    latest_summary = summarize_runtime(latest_entries, latest_gates)
    lines.append("## 最新 4H 关键样例")
    lines.append("")
    for code in ["4H无明确方向", "vwap_hard_block", "rsi_15m_extreme_veto", "rsi_1h_direction_flat_veto", "信号评分低于阈值"]:
        lines.append(f"### `{code}`")
        lines.append("")
        lines.append(sample_hold(latest_entries, code, 6))
    lines.append("")

    lines.append("## 部署生效性判断")
    lines.append("")
    hits = runtime["runtime_config_hits"]
    lines.append(f"- runtime 中 `shadow_mode=true` 命中：`{hits.get('shadow_mode_true', 0)}`")
    lines.append(f"- runtime 中 `shadow_mode=false` 命中：`{hits.get('shadow_mode_false', 0)}`")
    lines.append(f"- runtime 中 `vwap_gate_action` 命中：`{hits.get('vwap_gate_action', 0)}`")
    lines.append(f"- runtime 中 `probe_min_open` 命中：`{hits.get('probe_min_open', 0)}`")
    lines.append("")
    lines.append("解释：如果最新 4H 已经跑新代码，但 runtime 没有打印 `vwap_gate_action`，可能只是日志格式未展示；但 `vwap_hard_block` 数量仍高，说明 ATR normalized gate 没有带来预期放行，或实际 ATR 阈值仍小于多数偏离。这里必须用更完整 metadata 或临时 debug 字段确认。")
    lines.append("")

    lines.append("## 根因判断")
    lines.append("")
    lines.append("### 1. 上次“增加开仓”的改动没有形成闭环")
    lines.append("")
    lines.append("`total_compression_floor` 和 `probe_floor_rescue` 只影响已经到达 final sizing/min-open 的少数候选。最新窗口的大多数 HOLD 仍在 `neutral_upgrade_gate`、`vwap`、`rsi_rhythm` 阶段被归零，根本没有走到仓位压缩修复能发挥作用的位置。")
    lines.append("")
    lines.append("### 2. min_open 不是唯一问题，但部署旧配置确实浪费了高分候选")
    lines.append("")
    lines.append("昨晚 21:00 后出现多个 `signal_score >= 0.80`、`target=0.042` 的候选被 `min_open=0.06` 丢弃，同时 `probe_floor_rescue.shadow_mode=true`。这说明旧进程至少在该窗口前半段仍未加载 live rescue。")
    lines.append("")
    lines.append("### 3. 最新 4H 主要不是 final threshold 问题")
    lines.append("")
    lines.append("最新 4H 的 HOLD 主因集中在方向/VWAP/RSI 早期阶段。若只降 `entry_threshold`，只能影响已到 final 的候选，无法释放 `4H无明确方向`、`vwap_hard_block`、`rsi_15m_extreme_veto`。")
    lines.append("")
    lines.append("### 4. VWAP ATR gate 需要重新核验，不应假设已经有效")
    lines.append("")
    lines.append("最新 runtime 仍大量 `vwap_hard_block`。样例中 HYPE `dev=-7.31%`、`atr_pct=0.0068`，按 `4*ATR=2.72%` 仍会 hard block；这类不是固定 3% 一刀切的问题，而是趋势极端偏离确实超过 ATR block。对 SOL `dev=-4.57%`、`atr_pct=0.0069` 也同理。")
    lines.append("")
    lines.append("### 5. ExitGuard 有效触发，但执行失败暴露了路由问题")
    lines.append("")
    lines.append("`[ExitGuard] DOGEUSDT CLOSE` 后的平仓订单被 `ReduceOnly Order is rejected` 拒绝。这个问题不影响开仓数量，但会让风控修复在真实成交层失效，必须优先修。")
    lines.append("")

    lines.append("## 给 Claude 的评审问题")
    lines.append("")
    lines.append("1. 是否同意：当前开仓少的第一问题不是 threshold，而是 `4H无明确方向`、`vwap_hard_block`、`rsi_15m_extreme_veto` 的前置归零？")
    lines.append("2. 是否同意：`total_compression_floor/probe_floor_rescue` 只能救 final 后的小仓位候选，不能解决大多数 early HOLD？")
    lines.append("3. 是否应先加完整运行态配置指纹日志，例如启动时打印 config hash、probe shadow、VWAP gate mode、neutral/rsi/vwap 参数，而不是继续猜部署是否生效？")
    lines.append("4. VWAP ATR gate 目前只把 3% 改成 `4*ATR`，但多数样例仍超过 `4*ATR`。是否应该引入 `PROBE_ONLY` 路径，还是保持 hard block 等回测？")
    lines.append("5. `neutral_upgrade partial_confirm` 是否应该成为下一阶段主改动？日志显示 `4H无明确方向` 仍是最大 HOLD 来源。")
    lines.append("6. `rsi_15m_extreme_veto` 是否过硬？最新 4H 它已经比 final threshold 更常见。")
    lines.append("7. ExitGuard 平仓被 `-2022 ReduceOnly rejected` 打回，应优先审查 close 路由、positionSide、reduceOnly 参数与持仓同步。")
    lines.append("")

    lines.append("## 建议下一步")
    lines.append("")
    lines.append("不要继续无序叠参数。建议顺序：")
    lines.append("")
    lines.append("1. 先修部署可观测性：每次启动和每个 cycle 首行打印 config hash 与关键参数。")
    lines.append("2. 修 ExitGuard 平仓执行：复盘 DOGE `-2022`，保证退出守卫能真实平仓。")
    lines.append("3. 增加完整 metadata 输出或 debug JSONL，至少保留 `vwap_gate_action`、`vwap_deviation_in_atr`、`neutral_upgrade_mode`、`rsi_veto_reason`。")
    lines.append("4. 对最新 12H 做离线 counterfactual：把 `neutral_upgrade partial_confirm`、`VWAP PROBE_ONLY`、`rsi_15m_extreme_veto soft` 分别模拟，比较释放候选数量。")
    lines.append("5. 只有确认候选质量后，再改 live 参数。")
    lines.append("")
    lines.append("一句话：这两天的改动像是在下游补仓位和 min-open，但真正堵点在上游方向/VWAP/RSI 门控；而且部署和执行层又没有闭环，所以开仓数量自然不会上来。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT.write_text(build_report(), encoding="utf-8")
    print(str(OUT))


if __name__ == "__main__":
    main()
