from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


LOG_DIR = Path("logs/2026-05/2026-05-13")
ATTR = LOG_DIR / "fund_flow_attribution.jsonl"
API = LOG_DIR / "api_cycle_stats_utc.jsonl"
RUNTIME_FILES = [
    LOG_DIR / "runtime.out.06.log",
    LOG_DIR / "runtime.out.12.log",
    LOG_DIR / "runtime.out.18.log",
]
FILLS = LOG_DIR / "trade_fills_utc.csv"
OUT = Path("docs/2026-05-13_latest_2h_low_entry_and_trump_stop_review_for_claude.md")


UTC = timezone.utc
BJ = timezone(timedelta(hours=8))


def parse_iso_utc(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)


def parse_fill_ts(raw: str) -> datetime:
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def bj(ts: datetime) -> str:
    return ts.astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S")


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def compact_meta(meta: dict) -> dict:
    keys = [
        "hold_code",
        "hold_reason",
        "hold_stage",
        "signal_score",
        "score",
        "signal_threshold",
        "threshold",
        "threshold_source",
        "signal_1h",
        "signal_4h",
        "entry_15m",
        "veto_type",
        "vwap_score",
        "regime",
        "regime_adx",
        "regime_atr_pct",
        "macd_v2_stage",
        "direction_lock",
        "stop_pct",
        "stop_loss_pct",
    ]
    return {k: meta.get(k) for k in keys if k in meta}


def decision_time(row: dict) -> datetime | None:
    raw = row.get("ts") or row.get("timestamp") or row.get("timestamp_utc")
    if not raw:
        return None
    try:
        return parse_iso_utc(str(raw))
    except Exception:
        return None


def latest_window(rows: list[dict], hours: int = 2) -> tuple[datetime, datetime]:
    times = [t for row in rows if (t := decision_time(row))]
    latest = max(times)
    return latest - timedelta(hours=hours), latest


def analyze_attribution(start: datetime, end: datetime) -> dict:
    rows = read_jsonl(ATTR)
    selected = []
    for row in rows:
        ts = decision_time(row)
        if ts and start <= ts <= end:
            selected.append((ts, row))

    decisions = [(ts, row) for ts, row in selected if row.get("event") == "decision"]
    executions = [(ts, row) for ts, row in selected if row.get("event") == "execution"]

    op_counter = Counter()
    reason_counter = Counter()
    stage_counter = Counter()
    exec_counter = Counter()
    non_hold = []
    trump_rows = []

    for ts, row in decisions:
        dec = row.get("decision") or {}
        op = str(dec.get("operation", "")).lower()
        op_counter[op] += 1
        symbol = dec.get("symbol")
        meta = dec.get("metadata") or {}
        reason = meta.get("hold_code") or meta.get("hold_reason") or dec.get("reason") or "-"
        stage = meta.get("hold_stage") or meta.get("macd_v2_stage") or "-"
        if op == "hold":
            reason_counter[str(reason)] += 1
            stage_counter[str(stage)] += 1
        else:
            non_hold.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "op": op,
                    "target": dec.get("target_portion_of_balance"),
                    "lev": dec.get("leverage"),
                    "reason": dec.get("reason"),
                    "meta": compact_meta(meta),
                }
            )
        if symbol == "TRUMPUSDT":
            trump_rows.append((ts, row))

    for ts, row in executions:
        result = row.get("result") or {}
        exec_counter[str(result.get("status", "-"))] += 1

    return {
        "selected": selected,
        "decisions": decisions,
        "executions": executions,
        "op_counter": op_counter,
        "reason_counter": reason_counter,
        "stage_counter": stage_counter,
        "exec_counter": exec_counter,
        "non_hold": non_hold,
        "trump_rows": trump_rows,
    }


def parse_runtime_cycles(start: datetime, end: datetime) -> dict:
    cycle_re = re.compile(r"^=== FUND_FLOW cycle .* @ (?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC")
    symbol_re = re.compile(r"^\[(?P<symbol>[A-Z0-9]+USDT)\] 决策=(?P<decision>\w+) .*目标占比=(?P<target>[0-9.]+).*杠杆\(请求/实际\)=(?P<req>\d+)x/(?P<actual>\d+)x")
    gate_re = re.compile(r"ENTRY_GATE_BLOCK (?P<json>\{.*\})")
    score_re = re.compile(r"MACD_V2评分: (?P<text>.*)")
    hold_re = re.compile(r"HOLD归因: (?P<text>.*)")
    price_re = re.compile(r"K线价格\(15m\): (?P<text>.*)")
    stop_re = re.compile(r"MACD_V2止损: (?P<text>.*)")
    rule_re = re.compile(r"规则上下文: (?P<text>.*)")
    engine_re = re.compile(r"引擎上下文: (?P<text>.*)")
    reason_re = re.compile(r"决策原因: (?P<text>.*)")
    risk_re = re.compile(r"风控摘要 (?P<text>symbol=TRUMPUSDT .*)")

    current_ts: datetime | None = None
    current_symbol: str | None = None
    entries: list[dict] = []
    gates: list[dict] = []
    trump_timeline: list[dict] = []
    current_entry: dict | None = None

    def in_window() -> bool:
        return bool(current_ts and start <= current_ts <= end)

    for path in RUNTIME_FILES:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                m = cycle_re.match(line)
                if m:
                    current_ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                    current_symbol = None
                    current_entry = None
                    continue
                m = symbol_re.match(line)
                if m and in_window():
                    current_symbol = m.group("symbol")
                    current_entry = {
                        "cycle_ts": current_ts,
                        "symbol": current_symbol,
                        "decision": m.group("decision"),
                        "target": float(m.group("target")),
                        "requested_leverage": int(m.group("req")),
                        "actual_leverage": int(m.group("actual")),
                    }
                    entries.append(current_entry)
                    if current_symbol == "TRUMPUSDT":
                        trump_timeline.append(dict(current_entry))
                    continue
                m = gate_re.search(line)
                if m and in_window():
                    try:
                        payload = json.loads(m.group("json"))
                        payload["cycle_ts"] = current_ts
                        gates.append(payload)
                    except json.JSONDecodeError:
                        pass
                    continue
                m = risk_re.search(line)
                if m and in_window():
                    trump_timeline.append(
                        {
                            "cycle_ts": current_ts,
                            "symbol": "TRUMPUSDT",
                            "decision": "RISK_SUMMARY",
                            "risk": m.group("text"),
                        }
                    )
                    continue
                if current_entry is None or not in_window():
                    continue
                for key, regex in [
                    ("price", price_re),
                    ("rule", rule_re),
                    ("engine", engine_re),
                    ("score", score_re),
                    ("stop", stop_re),
                    ("reason", reason_re),
                    ("hold", hold_re),
                ]:
                    m = regex.search(line)
                    if m:
                        current_entry[key] = m.group("text")
                        if current_symbol == "TRUMPUSDT":
                            trump_timeline[-1][key] = m.group("text")
                        break

    return {
        "entries": entries,
        "gates": gates,
        "trump_timeline": sorted(
            trump_timeline,
            key=lambda x: (x.get("cycle_ts") or datetime.min.replace(tzinfo=UTC), x.get("decision") or ""),
        ),
    }


def parse_trump_fills() -> list[dict]:
    fills = []
    with FILLS.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            symbol = row.get("symbol") or row.get("合约")
            if symbol != "TRUMPUSDT":
                continue
            try:
                ts = parse_fill_ts(row.get("time_utc") or row.get("时间(UTC)") or "")
            except Exception:
                continue
            fills.append(
                {
                    "ts": ts,
                    "side": row.get("side") or row.get("方向"),
                    "price": float(row.get("price") or row.get("价格") or 0.0),
                    "qty": float(row.get("qty") or row.get("数量") or 0.0),
                    "quote_qty": float(row.get("quote_qty") or row.get("成交额") or 0.0),
                    "realized_pnl": float(row.get("realized_pnl") or row.get("已实现盈亏") or 0.0),
                }
            )
    uniq = {}
    for f in fills:
        key = (f["ts"], f["side"], f["price"], f["qty"], f["quote_qty"], f["realized_pnl"])
        uniq[key] = f
    return sorted(uniq.values(), key=lambda x: x["ts"])


def find_config_state() -> dict:
    cfg = json.loads(Path("config/trading_config_fund_flow.json").read_text(encoding="utf-8"))
    ff = cfg.get("fund_flow", {})
    v2 = ff.get("macd_mtf_strategy_v2", {})
    dyn = ((v2.get("sizing") or {}).get("dynamic_position_sizing") or {})
    if not dyn:
        dyn = v2.get("dynamic_position_sizing", {})
    return {
        "probe_floor_rescue": ff.get("probe_floor_rescue", {}),
        "total_compression_floor": (dyn.get("total_compression_floor") or {}),
        "weights": v2.get("scoring_weights", {}),
        "entry_thresholds": v2.get("entry_thresholds", {}),
        "vwap_deviation_hard_block": v2.get("vwap_deviation_hard_block"),
        "vwap_deviation_gate": v2.get("vwap_deviation_gate"),
        "neutral_upgrade": {
            k: v2.get(k)
            for k in [
                "enable_neutral_upgrade",
                "neutral_upgrade_min_rsi_score",
                "neutral_upgrade_probe_rsi_score",
                "neutral_upgrade_probe_threshold_score",
                "neutral_upgrade_penalty_mult",
                "partial_confirm_path",
            ]
            if k in v2
        },
        "rsi_soft_penalty": (v2.get("rsi_rhythm") or {}).get("hard_veto_upgrade")
        or (v2.get("rsi_rhythm") or {}).get("hard_veto_to_penalty_upgrade"),
    }


def pct(n: int, d: int) -> str:
    if d <= 0:
        return "0.0%"
    return f"{n / d * 100:.1f}%"


def as_float(raw: object, default: float = 0.0) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def md_counter(counter: Counter, total: int, limit: int = 12) -> str:
    lines = ["| 项 | 次数 | 占比 |", "|---|---:|---:|"]
    for k, v in counter.most_common(limit):
        lines.append(f"| `{k}` | {v} | {pct(v, total)} |")
    return "\n".join(lines)


def extract_kv(text: str, key: str) -> str:
    m = re.search(rf"{re.escape(key)}=([^,]+)", text or "")
    return m.group(1).strip() if m else "-"


def write_report() -> None:
    rows = read_jsonl(ATTR)
    start, end = latest_window(rows, 2)
    attr = analyze_attribution(start, end)
    rt = parse_runtime_cycles(start, end)
    fills = parse_trump_fills()
    cfg = find_config_state()

    decisions_n = len(attr["decisions"])
    hold_n = attr["op_counter"].get("hold", 0)
    non_hold = attr["non_hold"]
    gates = rt["gates"]
    min_open_gates = [g for g in gates if g.get("gate") == "min_open_portion"]
    same_side_gates = [g for g in gates if g.get("gate") == "same_side_add_guard"]
    gate_by_symbol = Counter(g.get("symbol", "-") for g in min_open_gates)
    runtime_hold_reason_counter = Counter()
    runtime_stage_counter = Counter()
    for e in rt["entries"]:
        hold = e.get("hold") or ""
        if "reason=" in hold:
            runtime_hold_reason_counter[extract_kv(hold, "reason")] += 1
        score = e.get("score") or ""
        if "stage=" in score:
            runtime_stage_counter[extract_kv(score, "stage")] += 1

    trump_relevant_fills = [
        f for f in fills
        if datetime(2026, 5, 13, 0, 0, tzinfo=UTC) <= f["ts"] <= end
    ]
    trump_runtime_all = parse_runtime_cycles(
        datetime(2026, 5, 13, 6, 45, tzinfo=UTC),
        end,
    )["trump_timeline"]

    lines: list[str] = []
    lines.append("# 2026-05-13 最新2H开仓无改善与 TRUMP 止损滞后分析包")
    lines.append("")
    lines.append("## 结论摘要")
    lines.append("")
    lines.append(
        f"分析窗口为北京时间 `{bj(start)}` 至 `{bj(end)}`，即 UTC `{start:%Y-%m-%d %H:%M:%S}` 至 `{end:%Y-%m-%d %H:%M:%S}`。"
    )
    lines.append("")
    lines.append("核心结论：上次两项优化没有看到明显增加开仓，原因不是修复失效，而是两项修复只作用在“已经到 final 且仓位被压小”的候选；最新 2H 的绝大多数候选仍死在更前面的方向/RSI/VWAP 门控。")
    lines.append("")
    lines.append("1. 最新 2H 仍是几乎全 HOLD。")
    lines.append("2. `total_compression_floor` 和 `probe_floor_rescue` 只救 final 后的小仓位候选，不会释放 `4H无明确方向`、`rsi_15m_extreme_veto`、`vwap_hard_block`。")
    lines.append("3. 最新 2H 的 `ENTRY_GATE_BLOCK` 仍显示 `probe_floor_rescue.shadow_mode=true`，说明运行中的进程很可能没有加载最新配置/代码，或日志来自切换前进程。")
    lines.append("4. TRUMP 的问题有两层：入场方向在后验上是错的；更严重的是持仓风控没有在 1H/RSI 已明显转空时触发提前退出，最终等到固定止损才卖出。")
    lines.append("5. Claude 提到的方向门控、RSI soft penalty、VWAP ATR gate、权重重平衡不是“多余优化”，但不建议一次性全部 live。当前证据支持优先做“退出风控/反向信号止损”与“确认 live 配置生效”，方向门控和 RSI/VWAP 放行至少需要 12H 日志或回测再动。")
    lines.append("")

    lines.append("## 最新2H运行概况")
    lines.append("")
    lines.append(f"- 策略决策数：`{decisions_n}`")
    for op, count in attr["op_counter"].most_common():
        lines.append(f"- `{op}`：`{count}`")
    lines.append("")
    lines.append("执行状态：")
    lines.append("")
    lines.append(md_counter(attr["exec_counter"], sum(attr["exec_counter"].values()) or 1, 8))
    lines.append("")
    lines.append("非 HOLD 决策：")
    lines.append("")
    if non_hold:
        lines.append("| UTC | 北京时间 | Symbol | op | target | reason |")
        lines.append("|---|---|---|---|---:|---|")
        for x in non_hold:
            lines.append(
                f"| {x['ts']:%Y-%m-%d %H:%M:%S} | {bj(x['ts'])} | {x['symbol']} | {x['op']} | {x['target']} | `{x['reason']}` |"
            )
    else:
        lines.append("最新 2H 未发现非 HOLD 策略决策。")
    lines.append("")

    lines.append("## HOLD 归因")
    lines.append("")
    lines.append("先看 runtime 文本中的细归因：")
    lines.append("")
    lines.append(md_counter(runtime_hold_reason_counter, sum(runtime_hold_reason_counter.values()) or 1, 12))
    lines.append("")
    lines.append("按 runtime stage：")
    lines.append("")
    lines.append(md_counter(runtime_stage_counter, sum(runtime_stage_counter.values()) or 1, 12))
    lines.append("")
    lines.append("再看 attribution JSON 中的粗 reason。注意：该 JSON 对 metadata 做了 `_omitted_keys` 压缩，所以比 runtime 粗。")
    lines.append("")
    lines.append(md_counter(attr["reason_counter"], hold_n, 12))
    lines.append("")
    lines.append("按 attribution stage：")
    lines.append("")
    lines.append(md_counter(attr["stage_counter"], hold_n, 12))
    lines.append("")
    lines.append("解释：如果 HOLD 主体仍集中在 `vwap_hard_block`、`rsi_*_veto`、`4H无明确方向/neutral_upgrade_*`，那么降低最终阈值、修复仓位 floor 都不会明显增加开仓。")
    lines.append("")

    lines.append("## min_open 与 probe_floor_rescue")
    lines.append("")
    lines.append(f"最新 2H runtime 中发现 `ENTRY_GATE_BLOCK`：`{len(gates)}` 次，其中 `min_open_portion` 为 `{len(min_open_gates)}` 次，TRUMP 同向加仓拦截 `same_side_add_guard` 为 `{len(same_side_gates)}` 次。")
    if min_open_gates:
        lines.append("")
        lines.append("min_open_portion 按 Symbol：")
        lines.append("")
        lines.append("| Symbol | 次数 |")
        lines.append("|---|---:|")
        for sym, cnt in gate_by_symbol.most_common():
            lines.append(f"| `{sym}` | {cnt} |")
        lines.append("")
        lines.append("代表样例：")
        lines.append("")
        lines.append("| UTC cycle | Symbol | side | target | min_open | score/threshold | probe_floor_rescue |")
        lines.append("|---|---|---|---:|---:|---:|---|")
        for g in min_open_gates[:8]:
            rescue = ((g.get("extra") or {}).get("probe_floor_rescue") or {})
            lines.append(
                f"| {g.get('cycle_ts'):%Y-%m-%d %H:%M:%S} | {g.get('symbol')} | {g.get('side')} | "
                f"{as_float(g.get('value')):.6f} | {as_float(g.get('threshold')):.4f} | "
                f"{as_float(g.get('signal_score')):.4f}/{as_float(g.get('signal_threshold')):.4f} | "
                f"enabled={rescue.get('enabled')}, applied={rescue.get('applied')}, shadow={rescue.get('shadow_mode')}, reason={rescue.get('reason')} |"
            )
    if same_side_gates:
        lines.append("")
        lines.append("TRUMP 相关 same_side_add_guard 样例：")
        lines.append("")
        lines.append("| UTC cycle | reason | score/threshold | signal_1h | signal_4h | reject_code |")
        lines.append("|---|---|---:|---|---|---|")
        for g in same_side_gates[:5]:
            lines.append(
                f"| {g.get('cycle_ts'):%Y-%m-%d %H:%M:%S} | `{g.get('reason')}` | "
                f"{as_float(g.get('signal_score')):.4f}/{as_float(g.get('signal_threshold')):.4f} | "
                f"{g.get('signal_1h')} | {g.get('signal_4h')} | `{g.get('reject_code')}` |"
            )
    lines.append("")
    lines.append("关键异常：当前配置文件中 `probe_floor_rescue.shadow_mode=false`，但最新 runtime 样例仍打印 `shadow_mode=true`。这不是策略逻辑问题，而是部署/进程状态问题：需要确认 bot 是否已重启并加载了最新配置。")
    lines.append("")
    lines.append("当前配置片段：")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(cfg["probe_floor_rescue"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    lines.append("## TRUMP 交易链路")
    lines.append("")
    lines.append("### 成交记录")
    lines.append("")
    lines.append("| UTC | 北京时间 | side | price | qty | quote_qty | realized_pnl |")
    lines.append("|---|---|---|---:|---:|---:|---:|")
    for f in trump_relevant_fills:
        lines.append(
            f"| {f['ts']:%Y-%m-%d %H:%M:%S} | {bj(f['ts'])} | {f['side']} | {f['price']:.4f} | {f['qty']:.4f} | {f['quote_qty']:.5f} | {f['realized_pnl']:.5f} |"
        )
    lines.append("")
    lines.append("本日 TRUMP：北京时间 `15:15:15` 买入，`19:52:10` 卖出，价格从 `2.483` 到 `2.387`，亏损约 `-3.87%`，realized PnL `-1.13088 USDT`。")
    lines.append("")
    lines.append("### 15:00 后 TRUMP 信号状态")
    lines.append("")
    lines.append("| UTC cycle | 北京时间 | decision | current/risk | price | engine | score摘要 | hold/原因 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for e in trump_runtime_all:
        if e.get("cycle_ts") is None:
            continue
        if e.get("decision") == "RISK_SUMMARY":
            risk = e.get("risk", "-")
            lines.append(
                f"| {e['cycle_ts']:%Y-%m-%d %H:%M:%S} | {bj(e['cycle_ts'])} | RISK | `{risk}` | - | - | - | - |"
            )
            continue
        price = e.get("price", "-")
        engine = e.get("engine", "-")
        score = e.get("score", "-")
        hold = e.get("hold") or e.get("reason") or "-"
        current = f"target={e.get('target')}, lev={e.get('actual_leverage')}"
        lines.append(
            f"| {e['cycle_ts']:%Y-%m-%d %H:%M:%S} | {bj(e['cycle_ts'])} | {e.get('decision')} | `{current}` | `{price}` | `{engine}` | `{score}` | `{hold}` |"
        )
    lines.append("")
    lines.append("观察：北京时间 18:00 起，风控摘要连续显示 `engine=NO_TRADE`、`state=HOLD`、`votes=0`、`action=none`。北京时间 18:00/18:15/18:30/17:45 等周期，策略侧已出现 `rsi_1h_direction_against_veto` 或 `rsi_15m_extreme_veto`，但这些只影响新开/加仓，没有转化为持仓退出信号。北京时间 20:00 以后 TRUMP 已经是 `4H=flip_bearish`，但仓位已经在 19:52 由价格止损卖出。")
    lines.append("")

    lines.append("## 为什么上次优化未增加开仓")
    lines.append("")
    lines.append("上次实际落地的是两项：")
    lines.append("")
    lines.append("1. `total_compression_floor`：只在信号已经通过评分、只是仓位被 VWAP/volume/ADX 叠压后发挥作用。")
    lines.append("2. `probe_floor_rescue live/probe_min_open`：只在最终 target 低于 min_open、且 score >= 0.80 时发挥作用。")
    lines.append("")
    lines.append("它们不改变以下前置门控：")
    lines.append("")
    lines.append("- `vwap_hard_block`")
    lines.append("- `rsi_15m_extreme_veto`")
    lines.append("- `rsi_1h_direction_against_veto` / `flat_veto`")
    lines.append("- `4H无明确方向` / `neutral_upgrade_gate`")
    lines.append("")
    lines.append("因此，如果最新 2H 的主要阻断仍在这些 stage，开仓数量不会明显提升。")
    lines.append("")
    lines.append("另一个更直接的问题是：最新 runtime 的 `ENTRY_GATE_BLOCK` 仍显示 `probe_floor_rescue.shadow_mode=true`，这与当前配置文件不一致。先确认部署生效，比继续加策略改动更重要。")
    lines.append("")

    lines.append("## Claude 上次提出的未落地优化是否多余")
    lines.append("")
    lines.append("判断：不是多余，但优先级需要拆开。")
    lines.append("")
    lines.append("| 优化项 | 当前判断 | 是否现在 live | 理由 |")
    lines.append("|---|---|---|---|")
    lines.append("| 方向门控 / neutral partial_confirm | 仍可能必要 | 暂不建议直接 live | 最新日志仍有大量 `4H无明确方向`，但放开会改变入场方向质量，需要至少 12H 样本或回测。 |")
    lines.append("| RSI soft penalty | 仍可能必要 | 暂不建议直接 live | RSI veto 仍是阻断源；但 TRUMP 亏损说明“放松入场 RSI”可能增加错误方向交易，必须先把退出风控补上。 |")
    lines.append("| VWAP ATR normalized gate | 必要性更强 | 必须回测后 live | 当前 `vwap_hard_block` 仍非常多，且高 ATR 标的固定 3%/4% 偏离一刀切不合理；但直接放开可能追趋势尾部。 |")
    lines.append("| 权重重平衡 | 不建议现在做 | 等 12H/回测 | 当前已发现 Claude 对 RSI raw_score > 1 的前提不适用于现代码；权重改动属于大手术。 |")
    lines.append("| 降阈值 | 不建议 | 否 | 当前问题仍不是最终阈值为主。 |")
    lines.append("")

    lines.append("## 需要优先修的不是入场，而是持仓风控")
    lines.append("")
    lines.append("TRUMP 暴露的问题：策略能在 15:15 开多，但没有在 1H/MACD/RSI 明显变坏时主动退出，最后等价格止损。")
    lines.append("")
    lines.append("建议 Claude 优先评审一个 `position_exit_signal_guard`：")
    lines.append("")
    lines.append("```text")
    lines.append("LONG 持仓提前退出条件候选：")
    lines.append("- 1H signal 从 bullish/growing 转为 flip_bearish 或 green_bar_shrinking 且 RSI_1H 下行")
    lines.append("- MACD_1H histogram 连续 2 根走弱，或 15m 已 flip_bearish")
    lines.append("- engine=NO_TRADE 且 ADX 高于 55，持仓方向与 4H flip 反向")
    lines.append("- VWAP dev 从入场顺势转为明显反向偏离")
    lines.append("")
    lines.append("动作：")
    lines.append("- 不等固定 2%/4% 价格止损")
    lines.append("- 先减仓 50% 或直接 close，具体需回放 TRUMP 与近 30D 止损样本")
    lines.append("```")
    lines.append("")

    lines.append("## 建议下一步")
    lines.append("")
    lines.append("1. 先确认部署是否真的加载：runtime 里 `probe_floor_rescue.shadow_mode` 仍是 `true`，这必须先查。")
    lines.append("2. 暂停继续放松入场门控，先加/回测持仓侧反向信号止损，TRUMP 说明退出慢比开仓少更危险。")
    lines.append("3. 等 12H 日志后再评估方向门控、RSI soft penalty、VWAP ATR gate；其中 VWAP ATR gate 必须单独回测。")
    lines.append("4. 权重重平衡最后做，且先修正 Claude 提案里不符合当前代码的前提。")
    lines.append("")
    lines.append("一句话：最新 2H 不能证明上次两项代码修复无效，因为运行日志疑似仍未加载 live probe 配置；但可以证明“只修 final 仓位门槛”不足以解决开仓少。当前更紧急的风险是 TRUMP 这种入场后反向信号未触发提前止损。")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT)
    print(f"window_utc={start:%Y-%m-%d %H:%M:%S}->{end:%Y-%m-%d %H:%M:%S}")
    print(f"decisions={decisions_n} hold={hold_n} non_hold={len(non_hold)} gates={len(gates)}")
    print("top_reasons=", attr["reason_counter"].most_common(8))


if __name__ == "__main__":
    write_report()
