import pandas as pd
import numpy as np

# 读取交易记录
df = pd.read_csv('output/backtest/backtest_trades_20260318_210742.csv')

# 筛选亏损交易
losing_trades = df[df['pnl'] < 0].copy()
winning_trades = df[df['pnl'] > 0].copy()

print('='*70)
print('亏损交易分析报告')
print('='*70)
print(f'\n总交易数: {len(df)}')
print(f'盈利交易: {len(winning_trades)} ({len(winning_trades)/len(df)*100:.1f}%)')
print(f'亏损交易: {len(losing_trades)} ({len(losing_trades)/len(df)*100:.1f}%)')
print(f'保本交易: {len(df[df["pnl"] == 0])}')

print('\n' + '='*70)
print('一、亏损原因分布')
print('='*70)
exit_reasons = losing_trades['exit_reason'].value_counts()
print(exit_reasons.to_string())
print(f'\n止损出场比例: {exit_reasons.get("stop_loss", 0) / len(losing_trades) * 100:.1f}%')

print('\n' + '='*70)
print('二、亏损交易信号评分分布')
print('='*70)
bins = [0, 50, 60, 70, 80, 90, 100]
labels = ['0-50', '50-60', '60-70', '70-80', '80-90', '90-100']
losing_trades['score_range'] = pd.cut(losing_trades['entry_score'], bins=bins, labels=labels)
score_dist = losing_trades.groupby('score_range', observed=True)['pnl'].agg(['count', 'sum', 'mean'])
print(score_dist.to_string())

print('\n' + '='*70)
print('三、亏损最严重的10笔交易')
print('='*70)
worst_trades = losing_trades.nsmallest(10, 'pnl')[['symbol', 'side', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'entry_time', 'exit_reason', 'entry_score', 'max_drawdown_pct']]
print(worst_trades.to_string())

print('\n' + '='*70)
print('四、亏损交易币种排名(亏损最多的币种)')
print('='*70)
symbol_loss = losing_trades.groupby('symbol')['pnl'].agg(['count', 'sum', 'mean']).sort_values('sum')
print(symbol_loss.head(15).to_string())

print('\n' + '='*70)
print('五、连续亏损分析')
print('='*70)
df_sorted = df.sort_values('entry_time')
df_sorted['is_loss'] = df_sorted['pnl'] < 0
consecutive_losses = []
current_streak = 0
max_streak = 0
for is_loss in df_sorted['is_loss']:
    if is_loss:
        current_streak += 1
        max_streak = max(max_streak, current_streak)
    else:
        if current_streak > 0:
            consecutive_losses.append(current_streak)
        current_streak = 0
if current_streak > 0:
    consecutive_losses.append(current_streak)

print(f'最大连续亏损次数: {max_streak}')
print(f'连续亏损3次以上次数: {sum(1 for x in consecutive_losses if x >= 3)}')

print('\n' + '='*70)
print('六、止损效果分析')
print('='*70)
stop_loss_trades = losing_trades[losing_trades['exit_reason'] == 'stop_loss']
print(f'止损交易数: {len(stop_loss_trades)}')
print(f'止损平均亏损: {stop_loss_trades["pnl"].mean():.2f} USDT')
print(f'止损总亏损: {stop_loss_trades["pnl"].sum():.2f} USDT')
print(f'止损亏损占总亏损比例: {abs(stop_loss_trades["pnl"].sum()) / abs(losing_trades["pnl"].sum()) * 100:.1f}%')

print('\n最大回撤分析:')
print(f'止损交易平均最大回撤: {stop_loss_trades["max_drawdown_pct"].mean()*100:.2f}%')
print(f'止损交易最大回撤范围: {stop_loss_trades["max_drawdown_pct"].min()*100:.2f}% ~ {stop_loss_trades["max_drawdown_pct"].max()*100:.2f}%')

print('\n' + '='*70)
print('七、亏损交易方向分析')
print('='*70)
side_loss = losing_trades.groupby('side')['pnl'].agg(['count', 'sum', 'mean'])
print(side_loss.to_string())

print('\n' + '='*70)
print('八、亏损交易持仓时间分析')
print('='*70)
losing_trades['duration'] = losing_trades['bars_held']
print(f'平均持仓时间: {losing_trades["duration"].mean():.1f} 根K线')
print(f'持仓1根K线止损: {len(losing_trades[losing_trades["duration"] == 1])} 笔')
print(f'持仓2根K线止损: {len(losing_trades[losing_trades["duration"] == 2])} 笔')
print(f'持仓<=3根K线止损: {len(losing_trades[losing_trades["duration"] <= 3])} 笔 ({len(losing_trades[losing_trades["duration"] <= 3])/len(losing_trades)*100:.1f}%)')

print('\n' + '='*70)
print('九、盈利vs亏损交易对比')
print('='*70)
print(f'盈利交易平均持仓: {winning_trades["bars_held"].mean():.1f} 根K线')
print(f'亏损交易平均持仓: {losing_trades["bars_held"].mean():.1f} 根K线')
print(f'盈利交易平均信号分: {winning_trades["entry_score"].mean():.1f}')
print(f'亏损交易平均信号分: {losing_trades["entry_score"].mean():.1f}')

print('\n' + '='*70)
print('十、关键发现与问题点')
print('='*70)

# 问题1: 止损触发后立即反向的价格行为
quick_stops = losing_trades[(losing_trades['exit_reason'] == 'stop_loss') & (losing_trades['bars_held'] <= 2)]
print(f'问题1: 快速止损(<=2根K线): {len(quick_stops)} 笔')
print(f'       这些交易可能在震荡行情中频繁触发止损')

# 问题2: 高信号分亏损
high_score_loss = losing_trades[losing_trades['entry_score'] >= 80]
print(f'\n问题2: 高信号分(>=80)仍亏损: {len(high_score_loss)} 笔')
print(f'       高信号分可能是过度拟合或趋势反转信号')

# 问题3: 特定币种问题
problem_symbols = symbol_loss[symbol_loss['count'] >= 5].head(5)
print(f'\n问题3: 亏损最多的币种:')
for idx, row in problem_symbols.iterrows():
    print(f'       {idx}: {row["count"]}笔, 总亏损{row["sum"]:.2f}U')
