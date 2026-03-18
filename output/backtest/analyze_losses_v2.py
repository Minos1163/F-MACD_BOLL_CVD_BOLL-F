#!/usr/bin/env python
"""亏损交易分析脚本"""
import pandas as pd
import numpy as np

# 读取交易数据
df = pd.read_csv('output/backtest/backtest_trades_20260318_213620.csv')

# 基本统计
print('='*60)
print('回测交易亏损分析报告')
print('='*60)

total_trades = len(df)
win_trades = len(df[df['pnl'] > 0])
loss_trades = len(df[df['pnl'] < 0])
breakeven_trades = len(df[df['pnl'] == 0])

print(f'\n总交易数: {total_trades}')
print(f'盈利交易: {win_trades} ({win_trades/total_trades*100:.1f}%)')
print(f'亏损交易: {loss_trades} ({loss_trades/total_trades*100:.1f}%)')
print(f'保本交易: {breakeven_trades}')

# 亏损交易分析
loss_df = df[df['pnl'] < 0].copy()

print(f'\n--- 亏损交易详情 ---')
print(f'总亏损金额: {loss_df["pnl"].sum():.2f} USDT')
print(f'平均亏损: {loss_df["pnl"].mean():.2f} USDT')
print(f'最大单笔亏损: {loss_df["pnl"].min():.2f} USDT')

# 按出场原因分析
print(f'\n--- 按出场原因分析亏损 ---')
exit_loss = loss_df.groupby('exit_reason').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
exit_loss.columns = ['亏损次数', '亏损总额', '平均亏损']
print(exit_loss.sort_values('亏损总额'))

# 按做多/做空分析
print(f'\n--- 按方向分析亏损 ---')
side_loss = loss_df.groupby('side').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
side_loss.columns = ['亏损次数', '亏损总额', '平均亏损']
print(side_loss)

# 全部交易按方向分析
print(f'\n--- 全部交易按方向统计 ---')
for side in ['long', 'short']:
    side_df = df[df['side'] == side]
    wins = len(side_df[side_df['pnl'] > 0])
    losses = len(side_df[side_df['pnl'] < 0])
    total_pnl = side_df['pnl'].sum()
    print(f'{side}: 总数={len(side_df)}, 胜率={wins/len(side_df)*100:.1f}%, 总盈亏={total_pnl:.2f}')

# 按币种分析亏损
print(f'\n--- 按币种分析亏损TOP10 ---')
symbol_loss = loss_df.groupby('symbol').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
symbol_loss.columns = ['亏损次数', '亏损总额', '平均亏损']
symbol_loss = symbol_loss.sort_values('亏损总额')
print(symbol_loss.head(10))

# 入场评分与亏损关系
print(f'\n--- 入场评分与亏损关系 ---')
loss_df['score_bin'] = pd.cut(loss_df['entry_score'], bins=[50,60,70,80,90,100], labels=['50-60','60-70','70-80','80-90','90-100'])
score_loss = loss_df.groupby('score_bin').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
score_loss.columns = ['亏损次数', '亏损总额', '平均亏损']
print(score_loss)

# 持仓时间与亏损关系
print(f'\n--- 持仓时间与亏损关系 ---')
loss_df['bars_bin'] = pd.cut(loss_df['bars_held'], bins=[0,2,5,10,20,100], labels=['1-2根','3-5根','6-10根','11-20根','>20根'])
bars_loss = loss_df.groupby('bars_bin').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
bars_loss.columns = ['亏损次数', '亏损总额', '平均亏损']
print(bars_loss)

# 大额亏损交易详情
print(f'\n--- 大额亏损交易详情(亏损>30 USDT) ---')
big_loss = loss_df[loss_df['pnl'] < -30].sort_values('pnl')
print(big_loss[['symbol', 'side', 'entry_score', 'exit_reason', 'bars_held', 'pnl', 'max_drawdown_pct']].head(20).to_string())

# 止损出场交易分析
print(f'\n--- 止损出场交易分析 ---')
sl_trades = df[df['exit_reason'] == 'stop_loss']
print(f'止损出场交易数: {len(sl_trades)}')
print(f'止损交易平均亏损: {sl_trades["pnl"].mean():.2f} USDT')

# 做多vs做空止损分析
print(f'\n做多止损:')
long_sl = sl_trades[sl_trades['side'] == 'long']
print(f'  交易数: {len(long_sl)}, 平均亏损: {long_sl["pnl"].mean():.2f}')

print(f'\n做空止损:')
short_sl = sl_trades[sl_trades['side'] == 'short']
print(f'  交易数: {len(short_sl)}, 平均亏损: {short_sl["pnl"].mean():.2f}')

# 分析持仓时间过短的止损
print(f'\n--- 极短持仓止损分析 (<=2根K线) ---')
quick_sl = sl_trades[sl_trades['bars_held'] <= 2]
print(f'极短持仓止损数: {len(quick_sl)}')
print(f'平均亏损: {quick_sl["pnl"].mean():.2f}')
print(f'做多数: {len(quick_sl[quick_sl["side"]=="long"])}, 做空数: {len(quick_sl[quick_sl["side"]=="short"])}')

# 分析入场评分高的亏损交易
print(f'\n--- 高评分(>=80)亏损交易分析 ---')
high_score_loss = loss_df[loss_df['entry_score'] >= 80]
print(f'高评分亏损交易数: {len(high_score_loss)}')
print(f'平均亏损: {high_score_loss["pnl"].mean():.2f}')
print(f'止损出场比例: {len(high_score_loss[high_score_loss["exit_reason"]=="stop_loss"])/len(high_score_loss)*100:.1f}%')

# 币种胜率分析
print(f'\n--- 币种胜率排名 ---')
symbol_stats = df.groupby('symbol').agg({
    'pnl': ['count', lambda x: (x > 0).sum(), 'sum']
})
symbol_stats.columns = ['总交易', '盈利次数', '总盈亏']
symbol_stats['胜率'] = symbol_stats['盈利次数'] / symbol_stats['总交易'] * 100
symbol_stats = symbol_stats.sort_values('总盈亏')
print(symbol_stats.head(15).round(2))
