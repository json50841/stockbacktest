import matplotlib
matplotlib.use('Agg')

import backtrader as bt
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# ---------------- Strategy ----------------
class SmaCrossStrategy(bt.Strategy):
    params = dict(
        fast=10,                    # 快速均线周期
        slow=30,                    # 慢速均线周期
        initial_size=1,             # 初始手数（例如 1 股）
        max_capital_usage_pct=0.5,  # 单笔最多使用本金比例（例如 0.5 表示 50%）
        stop_loss_points=4.0,       # 固定点数止损（价格差）
        take_profit_points=4.0,     # 固定点数止盈（价格差）
        recovery_mult=2             # 亏损后翻倍系数
    )

    def __init__(self):
        # 指标
        self.fast_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.fast)
        self.slow_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.slow)

        # 恢复（加倍）逻辑状态
        self.in_recovery = False
        self.recovery_size = self.p.initial_size
        self.last_trade_direction = None  # 'long' or 'short'

        # 记录用
        self.trade_log = []       # 每笔已平仓记录（字典）
        self.equity_curve = []    # 每根bar记录的净值

        # 用于入/出场识别（记录上次已知仓位）
        self._pos_size = 0
        # 当开仓时暂存 entry 信息（只保留单仓情形）
        self._current_entry = None  # dict: {'date','price','size','side'}

    # 资金检查：单笔仓位的名义金额是否超出允许比例（以账户净值衡量）
    def check_capital(self, size):
        cost = abs(self.data.close[0] * size)
        max_allowed = self.broker.getvalue() * self.p.max_capital_usage_pct
        return cost <= max_allowed

    def next(self):
        # 记录当时净值（每根bar）
        self.equity_curve.append(self.broker.getvalue())

        # 无持仓时决定开仓（正常均线或恢复模式）
        if not self.position:

            # 正常均线策略
            if not self.in_recovery:
                size = self.p.initial_size
                if not self.check_capital(size):
                    return

                if self.fast_sma[0] > self.slow_sma[0]:
                    self.last_trade_direction = "long"
                    self.buy(size=size)
                elif self.fast_sma[0] < self.slow_sma[0]:
                    self.last_trade_direction = "short"
                    self.sell(size=size)

            # 恢复模式（反向并按 recovery_size）
            else:
                size = self.recovery_size
                if not self.check_capital(size):
                    # 资金不足则跳过本次恢复下单
                    # 保持 in_recovery 状态，等待下一次机会
                    return

                # 如果上次方向是 long（即多单亏了），这次做空；反之亦然
                if self.last_trade_direction == "long":
                    self.sell(size=size)
                else:
                    self.buy(size=size)

        # 已有持仓 → 固定点数止盈止损
        else:
            entry_price = self.position.price
            price = self.data.close[0]

            if self.position.size > 0:  # 多单
                if price <= entry_price - self.p.stop_loss_points:
                    self.close()
                elif price >= entry_price + self.p.take_profit_points:
                    self.close()

            elif self.position.size < 0:  # 空单
                if price >= entry_price + self.p.stop_loss_points:
                    self.close()
                elif price <= entry_price - self.p.take_profit_points:
                    self.close()

    # 订单回调：用于记录开仓和平仓（更可靠地捕获 entry/exit price）
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return  # 忽略未执行/部分状态

        if order.status in [order.Completed]:
            # 新仓位规模（Backtrader 通常在这里 position 已经是更新后的）
            new_pos = self.position.size
            prev_pos = self._pos_size

            executed_price = None
            executed_dt = None
            executed_size = None

            # 从 order.executed 中取执行信息（可能多段，但对于你的策略一般单段）
            if hasattr(order, 'executed') and order.executed is not None:
                try:
                    executed_price = order.executed.price
                    executed_size = order.executed.size
                    # order.executed.dt 可能为 bt.num2date(...) 的 timestamp-like
                    executed_dt = bt.num2date(order.executed.dt) if getattr(order.executed, 'dt', None) else None
                except Exception:
                    executed_price = order.executed.price if hasattr(order.executed, 'price') else None
                    executed_size = order.executed.size if hasattr(order.executed, 'size') else None

            # ---------- 识别开仓（prev_pos == 0 -> new_pos != 0） ----------
            if prev_pos == 0 and new_pos != 0:
                # 记为 entry
                side = "long" if new_pos > 0 else "short"
                entry = {
                    "date": executed_dt.strftime("%Y-%m-%d %H:%M") if executed_dt else datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                    "price": executed_price,
                    "size": new_pos,
                    "side": side
                }
                # 缓存当前仓位信息（用于后续平仓计算）
                self._current_entry = entry

            # ---------- 识别平仓（prev_pos != 0 -> new_pos == 0） ----------
            if prev_pos != 0 and new_pos == 0 and self._current_entry is not None:
                # 这是一次完整平仓（entry 已缓存）
                exit_side = "exit"
                exit_date = executed_dt.strftime("%Y-%m-%d %H:%M") if executed_dt else datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                exit_price = executed_price
                exit_size = executed_size if executed_size is not None else abs(prev_pos)

                # 计算 PnL：区分多/空
                entry_price = self._current_entry["price"]
                entry_size = self._current_entry["size"]
                entry_side = self._current_entry["side"]

                # 当 entry_size 和 exit_size 的符号可能不同（Backtrader 的 size 表示仓位），我们取绝对值用于计算量
                qty = abs(exit_size) if exit_size is not None else abs(entry_size)

                if entry_side == "long":
                    pnl = (exit_price - entry_price) * qty
                else:  # short
                    pnl = (entry_price - exit_price) * qty

                # 记录到 trade_log
                record = {
                    "Entry Date": self._current_entry["date"],
                    "Exit Date": exit_date,
                    "Entry Price": entry_price,
                    "Exit Price": exit_price,
                    "Size": qty,
                    "PnL": pnl,
                    "Recovery Mode": bool(self.in_recovery)
                }
                self.trade_log.append(record)

                # 清空 current entry（单仓逻辑）
                self._current_entry = None

            # 更新最后已知仓位规模
            self._pos_size = new_pos

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            # 取消/拒单的情况：不记录为已执行
            # 你可以在此打印日志或采取其他措施
            # print("Order Canceled/Margin/Rejected:", order)
            pass

    # 仍然保留 notify_trade 用于兼容（不作为主记录）
    def notify_trade(self, trade):
        # 保留打印或进一步处理（trade 已闭合时可用）
        if trade.isclosed:
            # 输出一行 summary 到控制台（可选）
            # print("TRADE CLOSED -- PnL:", trade.pnl)
            pass


# ---------------- Data Loader ----------------
def get_minute_data(symbol, period='60d', interval='30m'):
    df = yf.download(symbol, interval=interval, period=period, auto_adjust=True, progress=False)

    # 处理多层列索引
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 统一列名为小写 backtrader 需要的字段
    df = df.rename(columns={
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume'
    })

    # 补充 openinterest
    df['openinterest'] = 0

    # 确保顺序
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df.index = pd.to_datetime(df.index)
    return df


# ---------------- HTML Export ----------------
def save_html_from_csv(csv_file, html_file, equity_curve_img=None):
    df = pd.read_csv(csv_file)
    img_html = f'<img src="{equity_curve_img}" width="600">' if equity_curve_img else ""
    html = f"""
    <html>
    <body>
    <h1>Backtest Report</h1>
    {img_html}
    {df.to_html(index=False)}
    </body>
    </html>
    """
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------- Main ----------------
if __name__ == "__main__":
    symbol = "AAPL"

    # 拉取 30 分钟数据（60 天）
    df = get_minute_data(symbol, period='60d', interval='30m')

    data_feed = bt.feeds.PandasData(
        dataname=df,
        timeframe=bt.TimeFrame.Minutes,
        compression=30
    )

    cerebro = bt.Cerebro()
    cerebro.adddata(data_feed)

    cerebro.addstrategy(
        SmaCrossStrategy,
        initial_size=10,
        max_capital_usage_pct=0.5,
        stop_loss_points=4,
        take_profit_points=4,
        recovery_mult=2
    )

    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)  # 若需改为百分比可调

    # 运行
    cerebro.run()

    # 从策略实例中读取记录并保存
    # 注意：Cerebro.run() 可能返回多个策略实例，如果你要严格取第一个：
    # strategies = cerebro.run(); strat = strategies[0]
    # 但上面我们直接多策略也能工作。这里为安全起见再运行一次获取策略对象：
    # (更稳妥的方式是在 cerebro.run() 时 capture 返回值；此处简化取上次策略)
    # 为兼容，各种运行环境，请尝试以下以从 cerebro 来拿到策略（若为空可直接改为前面接收返回值）
    # strategies = cerebro.run()
    # strat = strategies[0]

    # 由于上面没有捕获返回值（为了代码简短），我们再演示如何在实际中保存：
    # 假设你有 strat = strategies[0]，下面代码等价保存 strat.trade_log 和 strat.equity_curve

    # 为了避免错误，这里直接重新运行并拿到 strategies（推荐）
    strategies = cerebro.run()
    strat = strategies[0]

    trades_df = pd.DataFrame(strat.trade_log)
    trades_df.to_csv("trades.csv", index=False)
    print("Saved trades.csv")

    # equity curve
    plt.figure(figsize=(12, 6))
    plt.plot(strat.equity_curve)
    plt.title("Equity Curve")
    plt.tight_layout()
    plt.savefig("equity_curve.png")
    plt.close()
    print("Saved equity_curve.png")

    save_html_from_csv("trades.csv", "backtest_report.html", "equity_curve.png")
    print("Saved backtest_report.html")
    print("Backtest completed!")
