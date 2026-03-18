import pandas as pd
import numpy as np

# 读取交易记录
df = pd.read_csv('output/backtest/backtest_trades_20260318_210742.csv')

losing_trades = df[df['pnl'] < 0].copy()
winning_trades = df[df['pnl'] > 0].copy()

print('='*70)
print('深度亏损分析')
print('='*70)

print('\n' + '='*70)
print('一、做多vs做空亏损深度分析')
print('='*70)
long_losses = losing_trades[losing_trades['side'] == 'long']
short_losses = losing_trades[losing_trades['side'] == 'short']

print(f'\n做多亏损:')
print(f'  交易数: {len(long_losses)}')
print(f'  总亏损: {long_losses["pnl"].sum():.2f} USDT')
print(f'  平均单笔亏损: {long_losses["pnl"].mean():.2f} USDT')
print(f'  最大单笔亏损: {long_losses["pnl"].min():.2f} USDT')
print(f'  止损比例: {len(long_losses[long_losses["exit_reason"]=="stop_loss"])/len(long_losses)*100:.1f}%')

print(f'\n做空亏损:')
print(f'  交易数: {len(short_losses)}')
print(f'  总亏损: {short_losses["pnl"].sum():.2f} USDT')
print(f'  平均单笔亏损: {short_losses["pnl"].mean():.2f} USDT')
print(f'  最大单笔亏损: {short_losses["pnl"].min():.2f} USDT')
print(f'  止损比例: {len(short_losses[short_losses["exit_reason"]=="stop_loss"])/len(short_losses)*100:.1f}%')

print('\n' + '='*70)
print('二、AKTUSDT亏损详细分析(最差币种)')
print('='*70)
akt_losses = losing_trades[losing_trades['symbol'] == 'AKTUSDT']
akt_wins = winning_trades[winning_trades['symbol'] == 'AKTUSDT']
print(f'\n总交易: {len(df[df["symbol"]=="AKTUSDT"])}笔')
print(f'盈利交易: {len(akt_wins)}笔')
print(f'亏损交易: {len(akt_losses)}笔')
print(f'胜率: {len(akt_wins)/(len(akt_wins)+len(akt_losses))*100:.1f}%')
print(f'\n亏损详情:')
print(f'  做多亏损: {len(akt_losses[akt_losses["side"]=="long"])}笔, 共{akt_losses[akt_losses["side"]=="long"]["pnl"].sum():.2f}U')
print(f'  做空亏损: {len(akt_losses[akt_losses["side"]=="short"])}笔, 共{akt_losses[akt_losses["side"]=="short"]["pnl"].sum():.2f}U')
print(f'\n亏损原因:')
print(akt_losses['exit_reason'].value_counts().to_string())

print('\n' + '='*70)
print('三、快速止损交易分析(<=2根K线)')
print('='*70)
quick_stops = losing_trades[losing_trades['bars_held'] <= 2]
print(f'\n快速止损交易数: {len(quick_stops)}笔')
print(f'占总亏损交易: {len(quick_stops)/len(losing_trades)*100:.1f}%')
print(f'总亏损: {quick_stops["pnl"].sum():.2f} USDT')

print(f'\n快速止损币种分布:')
quick_symbol = quick_stops.groupby('symbol')['pnl'].agg(['count', 'sum']).sort_values('count', ascending=False).head(10)
print(quick_symbol.to_string())

print('\n' + '='*70)
print('四、高信号分亏损分析(信号分>=80)')
print('='*70)
high_score_losses = losing_trades[losing_trades['entry_score'] >= 80]
print(f'\n高信号分亏损交易数: {len(high_score_losses)}笔')
print(f'总亏损: {high_score_losses["pnl"].sum():.2f} USDT')
print(f'平均单笔亏损: {high_score_losses["pnl"].mean():.2f} USDT')

print(f'\n退出原因分布:')
print(high_score_losses['exit_reason'].value_counts().to_string())

print(f'\n方向分布:')
print(high_score_losses.groupby('side')['pnl'].agg(['count', 'sum']).to_string())

print('\n' + '='*70)
print('五、入场后最大浮盈分析')
print('='*70)
# 亏损交易中曾经盈利过的
losing_trades['had_profit'] = losing_trades['max_profit_pct'] > 0.01
profit_turned_loss = losing_trades[losing_trades['had_profit']]
print(f'\n亏损交易中曾有>1%浮盈的: {len(profit_turned_loss)}笔 ({len(profit_turned_loss)/len(losing_trades)*100:.1f}%)')
print(f'这些交易总亏损: {profit_turned_loss["pnl"].sum():.2f} USDT')
print(f'平均最大浮盈: {profit_turned_loss["max_profit_pct"].mean()*100:.2f}%')
print(f'平均最终亏损: {profit_turned_loss["pnl_pct"].mean()*100:.2f}%')

print('\n' + '='*70)
print('六、止损距离分析')
print('='*70)
stop_loss_trades = losing_trades[losing_trades['exit_reason'] == 'stop_loss']
# 计算止损距离
stop_loss_trades['stop_distance'] = abs(stop_loss_trades['pnl_pct'])
print(f'\n止损交易止损距离统计:')
print(f'平均止损距离: {stop_loss_trades["stop_distance"].mean()*100:.2f}%')
print(f'最小止损距离: {stop_loss_trades["stop_distance"].min()*100:.2f}%')
print(f'最大止损距离: {stop_loss_trades["stop_distance"].max()*100:.2f}%')

# 止损距离分布
bins = [0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.20, 1.0]
labels = ['0-2%', '2-4%', '4-6%', '6-8%', '8-10%', '10-15%', '15-20%', '>20%']
stop_loss_trades['stop_range'] = pd.cut(stop_loss_trades['stop_distance'], bins=bins, labels=labels)
stop_dist = stop_loss_trades.groupby('stop_range', observed=True)['pnl'].agg(['count', 'sum'])
print(f'\n止损距离分布:')
print(stop_dist.to_string())

print('\n' + '='*70)
print('七、问题总结与建议')
print('='*70)
print('''
【关键问题】:
1. 做多亏损严重(7814U vs 4391U)，建议优化做多入场条件

2. AKTUSDT/FLOWUSDT等币种单笔亏损过大，建议:
   - 从交易对列表中移除或降低仓位

3. 38.6%亏损在3根K线内止损，说明:
   - 入场时机不佳，可能在震荡行情中入场
   - 止损设置可能过紧

4. 高信号分(>=80)反而亏损最多，说明:
   - 信号评分机制可能过度拟合
   - 高分信号可能出现在趋势末端

5. 曾有>1%浮盈后转为亏损的交易占比较大
   - 建议优化移动止盈策略
''')
