# MACD_MTF_Strategy_V9_2A_Attribution_Review

> 文档用途：对 `V9.2A` 做一次独立的按币种与按回撤区间归因复核，确认提升是否具备可解释性，而不是单纯样本偶然。  
> 当前正式实盘基线：`V8/A`。  
> 当前候选实盘配置：`config/candidates/trading_config_fund_flow_v9_2a_candidate.json`。  
> 复核日期：`2026-03-21`。

---

## 一、结论先行

本次复核结论：`Accept as Candidate`。

原因不是“V9.2A 全面碾压所有币种”，而是：

- 它改善的是和 `V8/A` 完全相同的 stress window，而不是换了一段更顺的行情
- 改善来源与设计意图一致，主要落在 `short_dual_pressure` 的两个高风险 session
- 负向副作用也可定位，主要是部分 `flip_bullish` 相关 long state 有回吐

因此它更像“有明确机制解释的定向优化”，不是纯随机波动。

但也要如实说明：

- 增量并不分散
- 主要收益改善集中在少数此前最脏的币种
- 所以它已经足够成为候选实盘配置，但还不算“无条件直接替代正式基线”

---

## 二、结果总览

| 版本 | Return | PF | MDD | Trades |
| --- | --- | --- | --- | --- |
| V8/A | `+92.38%` | `2.74` | `10.69%` | `511` |
| V9.2A | `+99.39%` | `3.04` | `10.10%` | `498` |

关键变化：

- Return：`+7.01pp`
- PF：`+0.31`
- MDD：`-0.59pp`
- Trades：`-13`

候选配置快照：

- `config/candidates/trading_config_fund_flow_v9_2a_candidate.json`

分析产物：

- `output/analysis/v9_2a_attribution_review_20260321.json`
- `output/analysis/v9_2a_symbol_pnl_delta_20260321.csv`
- `output/analysis/v9_2a_drawdown_symbol_delta_20260321.csv`
- `output/analysis/v9_2a_state_pnl_delta_20260321.csv`
- `output/analysis/v9_2a_drawdown_state_delta_20260321.csv`

---

## 三、回撤区间复核

### 3.1 两版最大回撤窗口一致

`V8/A` 与 `V9.2A` 的最大回撤都发生在同一段：

- drawdown start: `2026-03-01 03:15:00`
- drawdown trough: `2026-03-04 17:15:00`

差别只在恢复：

- `V8/A` recovery: `2026-03-06 14:15:00`
- `V9.2A` recovery: `2026-03-06 12:00:00`

也就是：

- `V9.2A` 不是躲开了这段坏行情
- 而是在同一段坏行情里，回撤更浅，恢复提前 `2.25h`

这是“不是纯样本偶然”的第一条硬证据。

### 3.2 drawdown 区间内的主变化

按 `vwap_state` 看，`V9.2A` 在最大回撤区间的变化非常集中：

| 状态 | V8/A | V9.2A | Delta |
| --- | --- | --- | --- |
| `short_dual_pressure` | `-649.16` | `-102.25` | `+546.90` |
| `short_retest_reject` | `-346.86` | `-345.84` | `+1.02` |
| `long_dual_support` | `-10.43` | `-134.73` | `-124.30` |
| `long_reclaim_confirmed` | `+290.42` | `-110.60` | `-401.02` |

解释：

- `V9.2A` 真正压掉的是 `short_dual_pressure`
- 这正是 session 风控原本要打的 loss pocket
- 回吐主要出现在 `flip_bullish` 相关 long state，而不是目标空头 pocket 本身失效

这说明版本收益改善有明确机制来源，而不是随机漂移。

### 3.3 drawdown 区间的币种归因

在这段最大回撤区间里，贡献最大的改善币种是：

| 币种 | Delta |
| --- | --- |
| `SOLUSDT` | `+315.20` |
| `AAVEUSDT` | `+98.36` |
| `XLMUSDT` | `+22.13` |
| `WLDUSDT` | `+13.89` |
| `BCHUSDT` | `+13.78` |

主要恶化币种是：

| 币种 | Delta |
| --- | --- |
| `ONDOUSDT` | `-133.57` |
| `LINKUSDT` | `-100.68` |
| `LTCUSDT` | `-76.62` |
| `AVAXUSDT` | `-67.67` |
| `TRUMPUSDT` | `-46.07` |

判断：

- 回撤改善不是平均撒在所有币种上
- 但它也不是由单一一笔大赚造成
- 它主要来自此前最脏的 `SOLUSDT / AAVEUSDT` 亏损 pocket 被明显压缩

---

## 四、按币种复核

### 4.1 全样本 breadth

按全样本 symbol delta 统计：

- 改善币种：`18`
- 变差币种：`18`
- median delta：`+2.68`
- mean delta：`+18.23`

这说明：

- `V9.2A` 不是“全市场普涨型改良”
- 但也不是大面积恶化后靠单一巨额 lucky trade 拉出来

### 4.2 改善集中在哪类币种

最主要的改善币种：

| 币种 | V8/A | V9.2A | Delta |
| --- | --- | --- | --- |
| `SOLUSDT` | `-152.71` | `+176.70` | `+329.41` |
| `TAOUSDT` | `+781.82` | `+922.36` | `+140.54` |
| `ICPUSDT` | `-173.21` | `-34.02` | `+139.19` |
| `AAVEUSDT` | `+1218.48` | `+1339.45` | `+120.97` |
| `BCHUSDT` | `-533.53` | `-435.59` | `+97.95` |

这些改善大多符合同一逻辑：

- 先把原来就脏的亏损币种拉回正常
- 再把部分本来就盈利的强币做得更平滑

### 4.3 仍需盯防的币种

最主要的恶化币种：

| 币种 | Delta |
| --- | --- |
| `LINKUSDT` | `-287.99` |
| `ONDOUSDT` | `-123.80` |
| `LTCUSDT` | `-81.09` |
| `MORPHOUSDT` | `-63.09` |
| `TRUMPUSDT` | `-35.75` |

这意味着：

- `V9.2A` 现在最需要继续盯的是 `LINK / ONDO / LTC / MORPHO / TRUMP`
- 如果后面进入 shadow/live candidate 观察，这几个币要单独做 watchlist

### 4.4 集中度结论

`V9.2A` 的总收益增量并不均匀。

- top 3 symbol delta 占总增量约 `92.82%`

这说明它并不是“完全分散的稳健增强版”。  
更准确的说法是：

- 它是“针对原始最脏 pocket 的高解释性定向修复版”
- 不是“所有币全面同步抬升版”

这点不是否决理由，但必须在专家组材料里写清楚。

---

## 五、按 session 复核

`V9.2A` 的设计核心就是两个时间窗：

```json
[
  { "utc_start": "03:00", "utc_end": "05:30", "position_scale": 0.70 },
  { "utc_start": "14:30", "utc_end": "16:00", "position_scale": 0.65 }
]
```

复核后，时间窗表现与设计意图吻合：

### 5.1 亚洲薄流动性段 `03:00~05:30`

- V8/A：`-173.22`
- V9.2A：`+79.34`

其中主要改善来自：

- `short_dual_pressure`: `-468.74 -> -331.39`
- `short_retest_reject`: `+357.19 -> +474.43`

说明亚洲窗口风控是有效的，不是多余动作。

### 5.2 美股盘前 `14:30~16:00`

- V8/A：`+1423.02`
- V9.2A：`+1516.51`

最关键变化：

- `short_dual_pressure`: `-538.97 -> -63.06`

但也伴随：

- `long_reclaim_confirmed`: `+1688.35 -> +1288.48`

这说明：

- 美股盘前去风险明显压住了空头 pocket
- 但同时也削掉了一部分 `flip_bullish` 长端盈利弹性

这与前面的 drawdown state 归因完全一致。

---

## 六、最终判断

### 6.1 为什么说它不是纯样本偶然

因为三件事同时成立：

1. 最大回撤发生在同一段时间窗，不存在“换了一段更顺行情”的伪改良  
2. 改善正好落在被设计打击的 `short_dual_pressure + 高风险 session` 上  
3. 负向副作用也能被明确定位到 `flip_bullish` 相关 long state，而不是随机噪声

这三点组合起来，说明它有稳定的结构解释。

### 6.2 为什么仍然只给 `Candidate`，不直接给 `Baseline`

因为它仍有两个现实问题：

1. 增量高度集中，不够分散  
2. `LINK / ONDO / LTC / MORPHO / TRUMP` 等币种存在明确回吐

因此现在最合理的定位是：

- `Accept as Candidate`
- 不建议越过候选阶段直接替换正式实盘基线

### 6.3 建议动作

1. 保持 `V8/A` 为当前正式实盘基线  
2. 将 `V9.2A` 作为新的候选实盘配置进入 shadow/live candidate 观察  
3. 后续监控重点盯：
   - `LINKUSDT`
   - `ONDOUSDT`
   - `LTCUSDT`
   - `MORPHOUSDT`
   - `TRUMPUSDT`
4. 如果还要继续微调，优先方向不是再动空头 pocket，而是限制 `flip_bullish` long side 的回吐

---

*版本：V9.2A 归因复核稿 / 日期：2026-03-21*
