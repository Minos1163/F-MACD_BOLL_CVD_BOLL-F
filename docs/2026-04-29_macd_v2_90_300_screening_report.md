# MACD V2 90-300 笔约束筛选报告

- 日期: `2026-04-29`
- 目标: 不再把 `90-120` 作为硬目标，而是在 `90-300` 笔区间内优先寻找更高收益组合
- 回测窗口: `2026-02-23 -> 2026-03-24T23:59:59`

## 1. 本轮筛选方法

这轮不是盲目全量扫 profile，而是分两步做:

1. 先扫描仓库历史 summary，确认在 `90-300` 笔区间内，历史上确实存在远高于当前 `+44.37%` 的结果。
2. 再基于当前 HEAD 只重跑最有信息量的候选:
   - 现有 profile 候选
   - 围绕当前唯一稳定出单的默认 profile 做最小参数扰动

## 2. 历史上限证据

扫描 `output/backtest` 历史 summary 后，`90-300` 区间内的历史高收益上限如下:

| 工件 | profile | trades | return_pct | win_rate | max_dd | PF |
|---|---|---:|---:|---:|---:|---:|
| `v2_summary_20260426_092316.json` | `macd_v2_disable_short_filter` | `265` | `+229.06%` | `78.49%` | `12.01%` | `4.19` |
| `v2_summary_20260425_135324.json` | `macd_v2_disable_short_filter` | `260` | `+226.79%` | `78.08%` | `12.01%` | `4.16` |
| `v2_summary_20260323_224510.json` | `macd_v2_disable_short_filter` | `250` | `+166.72%` | `79.60%` | `9.38%` | `4.57` |

这只能说明:

- 当前体系历史上在 `90-300` 区间内确实有更高收益上限
- 但这些不是当前 HEAD 的 fresh 结果，不能直接当成当前可交付基准

## 3. 当前 HEAD 的 fresh screening

### 3.1 先筛现有 profile

本轮直接重跑了这些 profile:

- `macd_v2_disable_short_filter`
- `macd_v2_v11_vwap_score_tiers`
- `macd_v2_ablation_remove_trial_promotion`
- `top100_binance_rot_20260319`

结果非常明确:

| profile | 结果 |
|---|---|
| `macd_v2_disable_short_filter` | 正常出单 |
| `macd_v2_v11_vwap_score_tiers` | `0` 笔交易 |
| `macd_v2_ablation_remove_trial_promotion` | `0` 笔交易 |
| `top100_binance_rot_20260319` | `0` 笔交易 |

结论:

- 当前 HEAD 下，现有 profile 候选里，只有默认 `macd_v2_disable_short_filter` 还能稳定形成交易。
- 其它 profile 由于回到高阈值/强 VWAP 过滤结构，当前窗口内全部塌成 `0` 笔。

### 3.2 围绕默认 profile 做最小参数筛选

在默认 `macd_v2_disable_short_filter` 基础上，我额外测试了三组小改动:

1. `breakeven_trigger_pnl_ratio = 0.015`, `breakeven_lock_ratio = 0.005`
2. `max_active_symbols = 4`
3. `max_active_symbols = 5`
4. `max_active_symbols = 4` + 更宽 breakeven

对应临时配置:

- [screen_be15_lock05.json](</D:/AIDCA/AI2/config/candidates/screen_be15_lock05.json:1>)
- [screen_max_active_4.json](</D:/AIDCA/AI2/config/candidates/screen_max_active_4.json:1>)
- [screen_max_active_5.json](</D:/AIDCA/AI2/config/candidates/screen_max_active_5.json:1>)
- [screen_be15_lock05_max_active_4.json](</D:/AIDCA/AI2/config/candidates/screen_be15_lock05_max_active_4.json:1>)

## 4. Fresh 结果对比

| 组合 | trades | return_pct | win_rate | PF | max_dd | candidate_entries | submitted | filled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline `disable_short_filter` | `94` | `+44.37%` | `87.23%` | `7.20` | `6.12%` | `558` | `224` | `94` |
| `max_active_symbols = 4` | `107` | `+40.86%` | `85.05%` | `5.17` | `9.66%` | `525` | `252` | `107` |
| `max_active_symbols = 5` | `118` | `+40.16%` | `84.75%` | `4.82` | `10.27%` | `502` | `274` | `118` |
| `be=1.5%/0.5%` | `73` | `+27.98%` | `79.45%` | `2.88` | `7.43%` | `580` | `176` | `73` |
| `be=1.5%/0.5% + max_active=4` | `88` | `+31.04%` | `79.55%` | `2.78` | `10.51%` | `545` | `201` | `88` |

工件:

- baseline: [v2_summary_20260429_214056.json](</D:/AIDCA/AI2/output/backtest/v2_summary_20260429_214056.json:1>)
- `max_active=4`: [v2_summary_20260429_221214.json](</D:/AIDCA/AI2/output/backtest/v2_summary_20260429_221214.json:1>)
- `max_active=5`: [v2_summary_20260429_222625.json](</D:/AIDCA/AI2/output/backtest/v2_summary_20260429_222625.json:1>)
- `be wider`: [v2_summary_20260429_221219.json](</D:/AIDCA/AI2/output/backtest/v2_summary_20260429_221219.json:1>)
- `be wider + max_active=4`: [v2_summary_20260429_221218.json](</D:/AIDCA/AI2/output/backtest/v2_summary_20260429_221218.json:1>)

## 5. 结果解读

### 5.1 当前最强组合仍然是 baseline

如果只按 `90-300` 区间内的收益最大化来排，当前 HEAD 最强 fresh 组合仍然是:

- `macd_v2_disable_short_filter`
- `94` 笔
- `+44.37%`
- `87.23%` 胜率
- `6.12%` DD

这说明:

- 当前版本最有效的部分，仍是默认 profile 这条主链
- 其它现成 profile 并没有给出更好的 fresh 结果

### 5.2 扩容 `max_active_symbols` 能提交易数，但没有提收益

`max_active_symbols = 4`:

- 交易数从 `94 -> 107`
- 收益从 `44.37% -> 40.86%`
- 回撤从 `6.12% -> 9.66%`

`max_active_symbols = 5`:

- 交易数从 `94 -> 118`
- 收益从 `44.37% -> 40.16%`
- 回撤从 `6.12% -> 10.27%`

结论:

- 扩容确实能把开仓数拉进更宽区间
- 但当前版本里，新增交易的边际质量明显低于 baseline
- 也就是: “更多单” 不是当前 HEAD 的主收益杠杆

### 5.3 放宽 breakeven 在当前版本里是负贡献

`be=1.5%/0.5%` 的结果很差:

- 交易数掉到 `73`
- 收益掉到 `27.98%`
- 胜率掉到 `79.45%`
- PF 掉到 `2.88`

这和我上一轮“利润被切得太早”的归因并不矛盾，说明两件事同时成立:

1. 当前 baseline 的利润确实高度依赖少数 runner
2. 但把 breakeven 直接整体放宽到 `1.5%/0.5%`，会让大量原本能小赢出场的单变成回撤后亏损出场

也就是说:

- “breakeven 太早” 不是一句简单的 `把它放宽` 就能解决
- 更像是需要做路径分层，而不是全局统一放宽

## 6. 当前版本最值得继续逼近的高收益候选组合

### 候选 1: baseline `macd_v2_disable_short_filter`

这是当前 HEAD 的冠军组合。

优点:

- 收益最高: `+44.37%`
- 胜率最高: `87.23%`
- DD 最低: `6.12%`
- 在 `90-300` 约束内合法

缺点:

- 只在约束区间下边缘 `94` 笔
- 仍明显低于历史高水位

结论:

- 这是当前版本最值得保留的锚点组合
- 后续所有优化都应该以它为基线比较

### 候选 2: `max_active_symbols = 4`

这是当前最值得继续逼近的“扩容型候选”。

优点:

- 交易数抬到 `107`
- 仍在低 DD 区间内: `9.66%`
- 胜率 `85.05%` 仍然健康

缺点:

- 收益反而比 baseline 低 `3.51` 个百分点

结论:

- 这不是当前冠军
- 但它是“最有希望把交易数往上推，同时不立刻崩掉质量”的第二候选

### 候选 3: `max_active_symbols = 5`

这是“继续扩容”的上界参考。

优点:

- 交易数进一步抬到 `118`
- 仍在 `90-300` 区间里

缺点:

- 收益继续小幅下降
- DD 升到 `10.27%`
- PF 下滑到 `4.82`

结论:

- 当前更像容量扩张的边界点，而不是最优点
- 适合作为上界参考，不适合作为下一个主推组合

## 7. 哪些方向可以直接排除

这轮可以先排除的方向:

- 现有非默认 profile 直接切换
  - 因为当前 fresh rerun 下大多直接 `0` 笔
- 全局统一放宽 breakeven 到 `1.5%/0.5%`
  - 因为结果明显变差
- “只追求把交易数堆高”
  - 因为从 `94 -> 107 -> 118` 的过程中，收益没有同步提升

## 8. 我建议的下一轮逼近方向

如果目标是继续在 `90-300` 区间里逼近更高收益，当前最值得继续做的不是“换 profile”，而是“围绕 baseline 做局部结构优化”。

优先级建议:

1. 以 baseline 为锚点，继续做 `max_active_symbols` 小步扫描
   - 例如 `3 -> 3.5逻辑等效 -> 4`
   - 重点看是否能通过竞争筛选而不是硬扩容来提高新增交易质量

2. 不做全局 breakeven 放宽，改做路径分层
   - 只对 `red_bar_growing` / `flip_bearish` runner 路径放宽
   - 不要让所有普通单一起放宽

3. 先解决 `capacity_competition_dropped` 的质量问题
   - baseline 里已经有 `71` 笔 same-bar competition 丢弃
   - 比单纯扩 `max_active_symbols` 更值得优化的，可能是“高分优先替换低分仓位”

4. 如果继续做 profile 方向，只值得围绕默认 profile 新建“组合型 profile”
   - 不能再期待当前这些历史 profile 名字直接在 HEAD 上复活

## 9. 本轮结论

当前 HEAD 下，按 `90-300` 约束做 fresh screening 的结论是:

- **冠军组合**: `macd_v2_disable_short_filter` baseline
- **最值得继续逼近的第二候选**: `max_active_symbols = 4`
- **容量扩张上界参考**: `max_active_symbols = 5`
- **不值得继续的方向**:
  - 当前现有非默认 profile
  - 全局统一放宽 breakeven

换句话说:

- 当前版本的问题不是“还没找到更高收益的 profile”
- 而是“默认 profile 之外几乎没有能稳定出单的候选”
- 所以下一轮最有价值的工作，应该是围绕 baseline 做更细粒度的参数/执行层优化，而不是再盲扫旧 profile 名单

