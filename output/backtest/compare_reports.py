#!/usr/bin/env python
"""对比两次回测结果"""
import pandas as pd

print("="*60)
print("回测结果对比")
print("="*60)

print("\n优化前 (backtest_trades_20260318_213620.csv):")
df1 = pd.read_csv('output/backtest/backtest_trades_20260318_213620.csv')
total_pnl1 = df1['pnl'].sum()
wins1 = len(df1[df1['pnl'] > 0])
losses1 = len(df1[df1['pnl'] < 0])
win_rate1 = wins1 / len(df1) * 100
avg_win1 = df1[df1['pnl'] > 0]['pnl'].mean() if wins1 > 0 else 0
avg_loss1 = df1[df1['pnl'] < 0]['pnl'].mean() if losses1 > 0 else 0
rr1 = abs(avg_win1 / avg_loss1) if avg_loss1 != 0 else 0

print(f"  总交易: {len(df1)}")
print(f"  总盈亏: {total_pnl1:.2f} USDT")
print(f"  胜率: {win_rate1:.1f}%")
print(f"  盈亏比: {rr1:.2f}")

print("\n优化后 (backtest_trades_20260318_214325.csv):")
df2 = pd.read_csv('output/backtest/backtest_trades_20260318_214325.csv')
total_pnl2 = df2['pnl'].sum()
wins2 = len(df2[df2['pnl'] > 0])
losses2 = len(df2[df2['pnl'] < 0])
win_rate2 = wins2 / len(df2) * 100
avg_win2 = df2[df2['pnl'] > 0]['pnl'].mean() if wins2 > 0 else 0
avg_loss2 = df2[df2['pnl'] < 0]['pnl'].mean() if losses2 > 0 else 0
rr2 = abs(avg_win2 / avg_loss2) if avg_loss2 != 0 else 0

print(f"  总交易: {len(df2)}")
print(f"  总盈亏: {total_pnl2:.2f} USDT")
print(f"  胜率: {win_rate2:.1f}%")
print(f"  盈亏比: {rr2:.2f}")

print("\n改进:")
print(f"  盈亏变化: {total_pnl2 - total_pnl1:+.2f} USDT ({(total_pnl2/total_pnl1-1)*100:+.1f}%)")
print(f"  胜率变化: {win_rate2 - win_rate1:+.1f}%")
print(f"  盈亏比变化: {rr2 - rr1:+.2f}")

# 分析优化后的亏损
print("\n" + "="*60)
print("优化后亏损分析")
print("="*60)

loss_df = df2[df2['pnl'] < 0]
print(f"\n亏损交易数: {len(loss_df)}")
print(f"总亏损: {loss_df['pnl'].sum():.2f} USDT")

# 按出场原因
print("\n按出场原因:")
exit_loss = loss_df.groupby('exit_reason').agg({'pnl': ['count', 'sum']})
print(exit_loss)

# 按方向
print("\n按方向:")
for side in ['long', 'short']:
    side_loss = loss_df[loss_df['side'] == side]
    print(f"  {side}: {len(side_loss)}笔, 平均亏损{side_loss['pnl'].mean():.2f}")

# 问题币种
print("\n问题币种（亏损>50 USDT）:")
symbol_pnl = df2.groupby('symbol')['pnl'].sum()
problem_symbols = symbol_pnl[symbol_pnl < -50].sort_values()
print(problem_symbols)

# 止损分析
print("\n止损出场分析:")
sl_trades = df2[df2['exit_reason'] == 'stop_loss']
print(f"止损交易数: {len(sl_trades)}")
print(f"止损平均亏损: {sl_trades['pnl'].mean():.2f}")

# 极短持仓止损
quick_sl = sl_trades[sl_trades['bars_held'] <= 2]
print(f"极短持仓(<=2根K)止损: {len(quick_sl)}笔, 平均{quick_sl['pnl'].mean():.2f}")
